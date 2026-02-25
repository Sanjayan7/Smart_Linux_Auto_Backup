"""
restore_dialog.py
=================
Professional restore dialog supporting both Local and Cloud restore.

UI layout:
  ┌ Restore Source ──────────────────────────────────────────┐
  │  (•) Local Backup   ( ) Cloud Backup                     │
  └──────────────────────────────────────────────────────────┘
  ┌ Backup Selection ────────────────────────────────────────┐
  │  [LOCAL]  combobox of local archives  + [Refresh]        │
  │  [CLOUD]  combobox of cloud files     + [Refresh Cloud]  │
  └──────────────────────────────────────────────────────────┘
  ┌ Browse Backup Contents (Local only treeview) ────────────┐
  └──────────────────────────────────────────────────────────┘
  ┌ Restore Options ──────────────────────────────────────────┐
  │  Restore To:  [path entry]  [Browse]                      │
  │  Decryption Password: [***]                               │
  │  [Restore Selected / Restore from Cloud]                  │
  │  Status: ...                                              │
  └──────────────────────────────────────────────────────────┘
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import threading
from typing import List, Dict, Optional

from autobackup.core.backup_manager import BackupManager
from autobackup.core.cloud_restore_engine import (
    CloudRestoreError,
    RcloneNotConfiguredError,
    CloudFileNotFoundError,
    DownloadFailedError,
    WrongPasswordError,
    ExtractionFailedError,
    STEP_DOWNLOADING,
    STEP_DECRYPTING,
    STEP_EXTRACTING,
    STEP_VERIFYING,
    STEP_RESTORING,
    STEP_DONE,
)
from autobackup.utils.logger import logger


# Step → human label mapping for the status area
_STEP_LABELS = {
    STEP_DOWNLOADING : "☁ Downloading from cloud...",
    STEP_VERIFYING   : "🔐 Verifying archive integrity...",
    STEP_DECRYPTING  : "🔓 Decrypting...",
    STEP_EXTRACTING  : "📦 Extracting archive...",
    STEP_RESTORING   : "📂 Restoring folder structure...",
    STEP_DONE        : "✅ Cloud restore completed successfully",
}


class RestoreDialog(tk.Toplevel):
    """Modal dialog for restoring from local or cloud backup."""

    # ------------------------------------------------------------------ #
    def __init__(self, parent, backup_manager: BackupManager):
        super().__init__(parent)
        self.parent = parent
        self.backup_manager = backup_manager

        self.title("Restore Files / Folders")
        self.geometry("860x680")
        self.minsize(700, 580)
        self.transient(parent)
        self.grab_set()

        # ---------- state ----------
        self._restore_source = tk.StringVar(value="local")   # "local" | "cloud"
        self._cloud_files: List[str] = []
        self._restore_running = False

        self._build_ui()

    # ================================================================== #
    # UI CONSTRUCTION
    # ================================================================== #

    def _build_ui(self):
        # ── Restore Source radio buttons ──────────────────────────────
        src_frame = ttk.LabelFrame(self, text="Restore Source", padding="10")
        src_frame.pack(padx=10, pady=(10, 5), fill="x")

        ttk.Radiobutton(
            src_frame,
            text="  Local Backup",
            variable=self._restore_source,
            value="local",
            command=self._on_source_changed,
        ).pack(side="left", padx=(0, 30))

        ttk.Radiobutton(
            src_frame,
            text="  ☁ Cloud Backup  (gdrive:AutoBackup/)",
            variable=self._restore_source,
            value="cloud",
            command=self._on_source_changed,
        ).pack(side="left")

        # ── Backup Selection ──────────────────────────────────────────
        sel_frame = ttk.LabelFrame(self, text="Backup Selection", padding="10")
        sel_frame.pack(padx=10, pady=5, fill="x")

        # -- Local row --
        self._local_panel = ttk.Frame(sel_frame)
        self._local_panel.grid(row=0, column=0, sticky="ew")

        ttk.Label(self._local_panel, text="Backup Destination:").grid(
            row=0, column=0, sticky="w", pady=2
        )
        self._local_dest_entry = ttk.Entry(self._local_panel, width=55)
        self._local_dest_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self._local_dest_entry.insert(0, self.backup_manager.config.destination)
        self._local_dest_entry.config(state="readonly")

        ttk.Label(self._local_panel, text="Available Backups:").grid(
            row=1, column=0, sticky="w", pady=2
        )
        self._local_combo = ttk.Combobox(self._local_panel, state="readonly", width=52)
        self._local_combo.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        self._local_combo.bind("<<ComboboxSelected>>", self._on_local_version_selected)

        self._refresh_local_btn = ttk.Button(
            self._local_panel, text="Refresh", command=self._load_local_versions
        )
        self._refresh_local_btn.grid(row=1, column=2, padx=5, pady=2)
        self._local_panel.grid_columnconfigure(1, weight=1)

        # -- Cloud row --
        self._cloud_panel = ttk.Frame(sel_frame)
        self._cloud_panel.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        ttk.Label(self._cloud_panel, text="Cloud Backup File:").grid(
            row=0, column=0, sticky="w", pady=2
        )
        self._cloud_combo = ttk.Combobox(self._cloud_panel, state="readonly", width=52)
        self._cloud_combo.grid(row=0, column=1, sticky="ew", padx=5, pady=2)

        self._refresh_cloud_btn = ttk.Button(
            self._cloud_panel,
            text="🔄 Refresh Cloud",
            command=self._load_cloud_files,
        )
        self._refresh_cloud_btn.grid(row=0, column=2, padx=5, pady=2)
        self._cloud_panel.grid_columnconfigure(1, weight=1)

        # Cloud hint label
        self._cloud_hint = ttk.Label(
            self._cloud_panel,
            text="Select a file from gdrive:AutoBackup/ to restore.",
            foreground="gray",
            font=("TkDefaultFont", 8),
        )
        self._cloud_hint.grid(row=1, column=0, columnspan=3, sticky="w", padx=5)

        sel_frame.grid_columnconfigure(0, weight=1)

        # ── Browse Backup Contents (treeview – local only) ────────────
        self._tree_frame = ttk.LabelFrame(self, text="Browse Backup Contents", padding="10")
        self._tree_frame.pack(padx=10, pady=5, fill="both", expand=True)

        self._tree = ttk.Treeview(
            self._tree_frame, columns=("type", "size"), show="tree headings"
        )
        self._tree.heading("#0", text="Name")
        self._tree.heading("type", text="Type")
        self._tree.heading("size", text="Size")
        self._tree.column("type", width=100, anchor="center")
        self._tree.column("size", width=100, anchor="e")

        tree_scroll = ttk.Scrollbar(
            self._tree_frame, orient="vertical", command=self._tree.yview
        )
        self._tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.bind("<<TreeviewOpen>>", self._on_tree_open)

        # ── Restore Options ───────────────────────────────────────────
        opt_frame = ttk.LabelFrame(self, text="Restore Options", padding="10")
        opt_frame.pack(padx=10, pady=(5, 10), fill="x")

        ttk.Label(opt_frame, text="Restore To:").grid(
            row=0, column=0, sticky="w", pady=3
        )
        self._dest_entry = ttk.Entry(opt_frame, width=55)
        self._dest_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=3)
        ttk.Button(
            opt_frame, text="Browse", command=self._browse_restore_dest
        ).grid(row=0, column=2, padx=5, pady=3)

        ttk.Label(opt_frame, text="Decryption Password:").grid(
            row=1, column=0, sticky="w", pady=3
        )
        self._password_var = tk.StringVar()
        self._password_entry = ttk.Entry(
            opt_frame, show="*", textvariable=self._password_var, width=35
        )
        self._password_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=3)
        self._pw_hint = ttk.Label(
            opt_frame,
            text="Required only for encrypted backups (.gpg)",
            foreground="gray",
            font=("TkDefaultFont", 8),
        )
        self._pw_hint.grid(row=1, column=2, sticky="w", padx=5)

        self._restore_btn = ttk.Button(
            opt_frame,
            text="▶ Restore Selected",
            command=self._on_restore_clicked,
        )
        self._restore_btn.grid(row=2, column=0, columnspan=3, pady=12)

        # Status line
        self._status_var = tk.StringVar(value="")
        self._status_lbl = ttk.Label(
            opt_frame, textvariable=self._status_var, foreground="blue"
        )
        self._status_lbl.grid(row=3, column=0, columnspan=3, pady=(0, 5))

        opt_frame.grid_columnconfigure(1, weight=1)

        # ── Initial state ─────────────────────────────────────────────
        self._apply_source_state()
        self._load_local_versions()

    # ================================================================== #
    # SOURCE TOGGLE
    # ================================================================== #

    def _on_source_changed(self):
        self._apply_source_state()
        if self._restore_source.get() == "cloud" and not self._cloud_files:
            self._load_cloud_files()

    def _apply_source_state(self):
        is_cloud = self._restore_source.get() == "cloud"

        # Update restore button label
        self._restore_btn.config(
            text="☁ Restore from Cloud" if is_cloud else "▶ Restore Selected"
        )

        # Show/hide treeview for cloud (cloud = full restore, no item selection)
        if is_cloud:
            self._tree_frame.pack_forget()
        else:
            self._tree_frame.pack(padx=10, pady=5, fill="both", expand=True,
                                  before=self.children[list(self.children.keys())[-1]])

        # Visually dim the non-active panel
        self._set_panel_state(self._local_panel, "disabled" if is_cloud else "normal")
        self._set_panel_state(self._cloud_panel, "normal" if is_cloud else "disabled")

        # Always keep cloud refresh button active regardless of panel state
        self._refresh_cloud_btn.config(state="normal")

    def _set_panel_state(self, panel: ttk.Frame, state: str):
        """Recursively set state of all child widgets inside a frame."""
        for child in panel.winfo_children():
            try:
                if isinstance(child, (ttk.Entry, ttk.Combobox, ttk.Button)):
                    child.config(state=state)
                elif isinstance(child, ttk.Label):
                    fg = "gray" if state == "disabled" else "black"
                    child.config(foreground=fg)
            except tk.TclError:
                pass

    # ================================================================== #
    # LOCAL BACKUP LOADING
    # ================================================================== #

    def _load_local_versions(self):
        self._refresh_local_btn.config(state="disabled")
        self._update_status("Loading local backups...", "blue")
        threading.Thread(target=self._do_load_local_versions, daemon=True).start()

    def _do_load_local_versions(self):
        try:
            versions = self.backup_manager.list_backup_versions()
            # Filter to local only (exclude [Cloud] entries)
            local_versions = [v for v in versions if not v.startswith("[Cloud]")]
            self.after(0, lambda: self._populate_local_combo(local_versions))
        except Exception as exc:
            msg = str(exc)
            logger.error(f"Error loading local versions: {msg}")
            self.after(0, lambda m=msg: self._update_status(f"Error: {m}", "red"))
        finally:
            self.after(0, lambda: self._refresh_local_btn.config(state="normal"))

    def _populate_local_combo(self, versions: List[str]):
        self._local_combo["values"] = versions
        if versions:
            self._local_combo.set(versions[0])
            self._on_local_version_selected()
            self._update_status("", "blue")
        else:
            self._local_combo.set("")
            self._tree.delete(*self._tree.get_children())
            self._update_status("No local backups found.", "gray")

    def _on_local_version_selected(self, event=None):
        selected = self._local_combo.get()
        if selected:
            self._tree.delete(*self._tree.get_children())
            threading.Thread(
                target=self._do_load_backup_contents,
                args=(selected, ""),
                daemon=True,
            ).start()

    def _do_load_backup_contents(self, version: str, path: str, parent_iid=""):
        try:
            items = self.backup_manager.list_files_in_backup(version, path)
            self.after(0, lambda: self._populate_tree(items, parent_iid))
        except Exception as exc:
            msg = str(exc)
            logger.error(f"Error loading backup contents: {msg}")
            self.after(0, lambda m=msg: messagebox.showerror(
                "Error", f"Failed to load backup contents:\n{m}", parent=self
            ))

    def _populate_tree(self, items: List[Dict], parent_iid=""):
        for item in items:
            is_dir = item["type"] == "directory"
            size_str = self._format_size(item.get("size", 0)) if not is_dir else ""
            iid = self._tree.insert(
                parent_iid, "end",
                text=item["name"],
                values=(item["type"], size_str),
                tags=("directory" if is_dir else "file",),
                open=False,
            )
            if is_dir:
                self._tree.insert(iid, "end", text="⏳ Loading...", tags=("dummy",))

    def _on_tree_open(self, event):
        iid = self._tree.focus()
        if not iid:
            return
        vals = self._tree.item(iid, "values")
        if vals and vals[0] == "directory":
            children = self._tree.get_children(iid)
            if children:
                first = children[0]
                if "Loading" in self._tree.item(first, "text"):
                    self._tree.delete(first)
                    version = self._local_combo.get()
                    path = self._path_from_iid(iid)
                    threading.Thread(
                        target=self._do_load_backup_contents,
                        args=(version, path, iid),
                        daemon=True,
                    ).start()

    def _path_from_iid(self, iid) -> str:
        parts = []
        while iid:
            parts.insert(0, self._tree.item(iid, "text"))
            iid = self._tree.parent(iid)
        return os.path.join(*parts[1:]) if len(parts) > 1 else ""

    # ================================================================== #
    # CLOUD FILE LOADING
    # ================================================================== #

    def _load_cloud_files(self):
        self._refresh_cloud_btn.config(state="disabled")
        self._cloud_combo.set("")
        self._cloud_combo["values"] = []
        self._update_status("⏳ Connecting to gdrive and listing backups...", "blue")

        threading.Thread(target=self._do_load_cloud_files, daemon=True).start()

    def _do_load_cloud_files(self):
        try:
            files = self.backup_manager.list_cloud_backup_files()
            self.after(0, lambda: self._populate_cloud_combo(files))
        except RcloneNotConfiguredError as exc:
            msg = str(exc)
            logger.error(f"rclone not configured: {msg}")
            self.after(0, lambda m=msg: self._on_cloud_load_error(
                f"rclone not configured:\n{m}"
            ))
        except Exception as exc:
            msg = str(exc)
            logger.error(f"Cloud file listing failed: {msg}")
            self.after(0, lambda m=msg: self._on_cloud_load_error(
                f"Failed to list cloud backups:\n{m}"
            ))
        finally:
            self.after(0, lambda: self._refresh_cloud_btn.config(state="normal"))

    def _populate_cloud_combo(self, files: List[str]):
        self._cloud_files = files
        if files:
            self._cloud_combo["values"] = files
            self._cloud_combo.set(files[0])
            self._update_status(
                f"✓ {len(files)} cloud backup(s) found. Select one and click Restore.",
                "green",
            )
            self._cloud_hint.config(
                text=f"gdrive:AutoBackup/ — {len(files)} file(s) available",
                foreground="green",
            )
        else:
            self._cloud_combo["values"] = []
            self._cloud_combo.set("")
            self._update_status(
                "No backups found in gdrive:AutoBackup/.", "gray"
            )
            self._cloud_hint.config(
                text="No backup files found in gdrive:AutoBackup/",
                foreground="orange",
            )

    def _on_cloud_load_error(self, msg: str):
        self._update_status(f"❌ {msg}", "red")
        self._cloud_hint.config(text=msg, foreground="red")
        messagebox.showerror("Cloud Error", msg, parent=self)

    # ================================================================== #
    # RESTORE DESTINATION
    # ================================================================== #

    def _browse_restore_dest(self):
        d = filedialog.askdirectory(parent=self, title="Select Restore Destination")
        if d:
            self._dest_entry.delete(0, tk.END)
            self._dest_entry.insert(0, d)

    # ================================================================== #
    # RESTORE ACTION DISPATCHER
    # ================================================================== #

    def _on_restore_clicked(self):
        if self._restore_running:
            return

        restore_dest = self._dest_entry.get().strip()
        if not restore_dest:
            messagebox.showwarning(
                "Restore", "Please select a restore destination folder.", parent=self
            )
            return

        if self._restore_source.get() == "cloud":
            self._start_cloud_restore(restore_dest)
        else:
            self._start_local_restore(restore_dest)

    # ================================================================== #
    # LOCAL RESTORE
    # ================================================================== #

    def _start_local_restore(self, restore_dest: str):
        selected_version = self._local_combo.get()
        if not selected_version:
            messagebox.showwarning(
                "Restore", "No backup version selected.", parent=self
            )
            return

        is_encrypted = (
            ".gpg" in selected_version or ".enc" in selected_version
        )

        items_to_restore = []
        if not is_encrypted:
            selected_iids = self._tree.selection()
            if not selected_iids:
                messagebox.showwarning(
                    "Restore", "Please select at least one item to restore.", parent=self
                )
                return
            for iid in selected_iids:
                text = self._tree.item(iid, "text")
                if "Loading" not in text:
                    path = self._path_from_iid(iid)
                    if path:
                        items_to_restore.append(path)
            if not items_to_restore:
                messagebox.showwarning(
                    "Restore", "No valid items selected.", parent=self
                )
                return

        password = self._password_var.get()

        self._lock_ui("Starting restore...")
        threading.Thread(
            target=self._do_local_restore,
            args=(selected_version, items_to_restore, restore_dest, password),
            daemon=True,
        ).start()

    def _do_local_restore(
        self,
        version: str,
        items: list,
        dest: str,
        password: str,
    ):
        try:
            success = self.backup_manager.restore_items(version, items, dest, password)
            if success:
                self.after(0, lambda: self._on_restore_success(
                    f"Successfully restored to:\n{dest}"
                ))
            else:
                self.after(0, lambda: self._on_restore_failure(
                    "Restore failed. Check the application log for details."
                ))
        except Exception as exc:
            msg = str(exc)
            logger.exception(f"Local restore error: {msg}")
            self.after(0, lambda m=msg: self._on_restore_failure(m))

    # ================================================================== #
    # CLOUD RESTORE
    # ================================================================== #

    def _start_cloud_restore(self, restore_dest: str):
        selected_file = self._cloud_combo.get()
        if not selected_file:
            messagebox.showwarning(
                "Cloud Restore",
                "No cloud backup file selected.\n\n"
                "Click 'Refresh Cloud' to load the list, then select a file.",
                parent=self,
            )
            return

        password = self._password_var.get()

        # Check if the archive likely needs a password but none was given
        needs_pw = selected_file.endswith(".gpg") or selected_file.endswith(".enc")
        if needs_pw and not password:
            answer = messagebox.askyesno(
                "Encrypted Backup",
                f"The selected backup '{selected_file}' appears to be encrypted.\n\n"
                "No decryption password was entered.\n"
                "Restore will fail if a password is required.\n\n"
                "Continue anyway?",
                parent=self,
            )
            if not answer:
                return

        self._lock_ui(STEP_DOWNLOADING)
        threading.Thread(
            target=self._do_cloud_restore,
            args=(selected_file, restore_dest, password),
            daemon=True,
        ).start()

    def _do_cloud_restore(
        self,
        remote_filename: str,
        restore_dest: str,
        password: str,
    ):
        """Execute cloud restore pipeline in a background thread."""

        def _status_cb(msg: str):
            """Relay engine step messages to the UI thread."""
            display = _STEP_LABELS.get(msg, msg)
            logger.info(f"Cloud restore step: {display}")
            self.after(0, lambda m=display: self._update_status(m, "blue"))
            # Mirror to main window log
            self.after(0, lambda m=display: self._append_main_status(
                f"CLOUD RESTORE: {m}\n"
            ))

        def _confirm_overwrite(msg: str) -> bool:
            """
            Show the engine's conflict message to the user and return their answer.
            The `msg` parameter already contains the specific conflicting item names
            formatted by the engine's _check_conflicts() method.
            """
            result = {"answer": False}
            event = threading.Event()

            def _ask():
                answer = messagebox.askyesno(
                    "Confirm Overwrite",
                    msg,
                    parent=self,
                )
                result["answer"] = answer
                event.set()

            self.after(0, _ask)
            event.wait(timeout=120)
            return result["answer"]

        try:
            self.backup_manager.restore_from_cloud(
                remote_filename=remote_filename,
                restore_destination=restore_dest,
                decryption_password=password,
                status_callback=_status_cb,
                confirm_overwrite_callback=_confirm_overwrite,
            )
            # Success
            self.after(0, lambda: self._on_restore_success(
                f"Cloud restore completed successfully.\n\nFiles restored to:\n{restore_dest}"
            ))

        except WrongPasswordError as exc:
            msg = str(exc)
            logger.error(f"Wrong password: {msg}")
            self.after(0, lambda m=msg: self._on_restore_failure(
                f"❌ Incorrect password.\n\n{m}\n\nPlease re-enter your decryption password and try again."
            ))

        except RcloneNotConfiguredError as exc:
            msg = str(exc)
            logger.error(f"rclone config error: {msg}")
            self.after(0, lambda m=msg: self._on_restore_failure(
                f"❌ rclone not configured.\n\n{m}"
            ))

        except CloudFileNotFoundError as exc:
            msg = str(exc)
            logger.error(f"Cloud file not found: {msg}")
            self.after(0, lambda m=msg: self._on_restore_failure(
                f"❌ Backup file not found in cloud.\n\n{m}"
            ))

        except DownloadFailedError as exc:
            msg = str(exc)
            logger.error(f"Download failed: {msg}")
            self.after(0, lambda m=msg: self._on_restore_failure(
                f"❌ Download failed.\n\n{m}"
            ))

        except ExtractionFailedError as exc:
            msg = str(exc)
            logger.error(f"Extraction failed: {msg}")
            self.after(0, lambda m=msg: self._on_restore_failure(
                f"❌ Archive extraction failed.\n\n{m}"
            ))

        except CloudRestoreError as exc:
            msg = str(exc)
            logger.error(f"Cloud restore error: {msg}")
            self.after(0, lambda m=msg: self._on_restore_failure(
                f"❌ Restore failed.\n\n{m}"
            ))

        except Exception as exc:
            msg = str(exc)
            logger.exception(f"Unexpected cloud restore error: {msg}")
            self.after(0, lambda m=msg: self._on_restore_failure(
                f"❌ Unexpected error during restore:\n\n{m}"
            ))

    # ================================================================== #
    # RESTORE OUTCOME HANDLERS
    # ================================================================== #

    def _on_restore_success(self, detail: str):
        self._update_status("✅ Restore completed successfully!", "green")
        self._unlock_ui()
        self._append_main_status("✅ RESTORE: Completed successfully.\n")
        messagebox.showinfo("Restore Complete", detail, parent=self)
        self.after(200, self.destroy)

    def _on_restore_failure(self, msg: str):
        self._update_status(f"❌ Restore failed.", "red")
        self._unlock_ui()
        self._append_main_status(f"❌ RESTORE FAILED: {msg}\n")
        messagebox.showerror("Restore Failed", msg, parent=self)

    # ================================================================== #
    # UI HELPERS
    # ================================================================== #

    def _lock_ui(self, status_msg: str):
        """Disable restore button and show status while operation runs."""
        self._restore_running = True
        self._restore_btn.config(state="disabled", text="⏳ Running...")
        self._refresh_cloud_btn.config(state="disabled")
        self._refresh_local_btn.config(state="disabled")
        self._update_status(status_msg, "blue")

    def _unlock_ui(self):
        """Re-enable the restore button after operation completes."""
        self._restore_running = False
        is_cloud = self._restore_source.get() == "cloud"
        self._restore_btn.config(
            state="normal",
            text="☁ Restore from Cloud" if is_cloud else "▶ Restore Selected",
        )
        self._refresh_cloud_btn.config(state="normal")
        self._refresh_local_btn.config(state="normal")

    def _update_status(self, msg: str, color: str = "blue"):
        self._status_var.set(msg)
        self._status_lbl.config(foreground=color)

    def _append_main_status(self, text: str):
        """Forward a log message to the main window status area."""
        if hasattr(self.parent, "_append_status"):
            self.parent._append_status(text)

    @staticmethod
    def _format_size(size_bytes) -> str:
        """Format a byte count as a human-readable string."""
        try:
            n = int(size_bytes)
        except (TypeError, ValueError):
            return str(size_bytes)
        if n < 1024:
            return f"{n} B"
        if n < 1024 ** 2:
            return f"{n / 1024:.1f} KB"
        return f"{n / (1024 ** 2):.2f} MB"
