"""
history_panel.py
================
Backup History panel — a Toplevel window showing a table of all past
backups with a Clear History button.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from autobackup.core.backup_history import history_manager
from autobackup.utils.logger import logger


class HistoryPanel(tk.Toplevel):
    """Modal-style window displaying backup history in a Treeview table."""

    # Column definitions: (id, heading, width, anchor)
    _COLUMNS = [
        ("timestamp",  "Date / Time",    160, "w"),
        ("mode",       "Mode",            80, "center"),
        ("size_mb",    "Size (MB)",       80, "e"),
        ("files",      "Files",           60, "e"),
        ("encrypted",  "Encrypted",       75, "center"),
        ("compressed", "Compressed",      80, "center"),
        ("cloud",      "Cloud",           65, "center"),
        ("status",     "Status",          75, "center"),
        ("duration",   "Duration",        80, "e"),
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self.title("📋 Backup History")
        self.geometry("900x480")
        self.minsize(750, 320)
        self.transient(parent)

        self._build_ui()
        self._load_history()

        # Grab focus
        self.focus_set()
        self.grab_set()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Header
        header = ttk.Frame(self, padding="8")
        header.pack(fill="x")

        ttk.Label(
            header,
            text="📋 Backup History",
            font=("TkDefaultFont", 13, "bold"),
        ).pack(side="left")

        self._count_label = ttk.Label(
            header,
            text="",
            foreground="gray",
            font=("TkDefaultFont", 9),
        )
        self._count_label.pack(side="left", padx=(12, 0))

        # Buttons
        btn_frame = ttk.Frame(header)
        btn_frame.pack(side="right")

        ttk.Button(
            btn_frame,
            text="🔄 Refresh",
            command=self._load_history,
        ).pack(side="left", padx=4)

        ttk.Button(
            btn_frame,
            text="🗑 Clear History",
            command=self._on_clear,
        ).pack(side="left", padx=4)

        ttk.Button(
            btn_frame,
            text="Close",
            command=self.destroy,
        ).pack(side="left", padx=4)

        # Separator
        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # Treeview with scrollbar
        tree_frame = ttk.Frame(self, padding="4")
        tree_frame.pack(fill="both", expand=True)

        col_ids = [c[0] for c in self._COLUMNS]
        self._tree = ttk.Treeview(
            tree_frame,
            columns=col_ids,
            show="headings",
            selectmode="browse",
        )

        for col_id, heading, width, anchor in self._COLUMNS:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, anchor=anchor, minwidth=50)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Status bar
        self._status_bar = ttk.Label(
            self,
            text="",
            font=("TkDefaultFont", 8),
            foreground="gray",
            padding="4",
        )
        self._status_bar.pack(fill="x")

        # Tag styling for status column
        self._tree.tag_configure("success", foreground="#2e7d32")
        self._tree.tag_configure("failed",  foreground="#c62828")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_history(self):
        """Populate the treeview from backup_history.json."""
        # Clear existing rows
        for item in self._tree.get_children():
            self._tree.delete(item)

        entries = history_manager.get_entries()

        for entry in entries:
            ts        = entry.get("timestamp", "—")
            mode      = entry.get("mode", "—")
            size_mb   = entry.get("size_mb", 0)
            files     = entry.get("files_count", 0)
            encrypted = "🔒" if entry.get("encrypted") else "—"
            compressed= "📦" if entry.get("compressed") else "—"
            cloud     = "☁" if entry.get("cloud_uploaded") else "—"
            status    = entry.get("status", "—")
            duration  = entry.get("duration_seconds", 0)

            dur_str = f"{duration:.1f}s" if duration else "—"
            size_str = f"{size_mb:.2f}" if size_mb else "0.00"

            tag = "success" if status == "Success" else "failed"

            self._tree.insert(
                "",
                "end",
                values=(ts, mode, size_str, files, encrypted, compressed, cloud, status, dur_str),
                tags=(tag,),
            )

        count = len(entries)
        self._count_label.config(text=f"({count} record{'s' if count != 1 else ''})")
        self._status_bar.config(text=f"Showing {count} backup record(s)")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_clear(self):
        """Clear all history after user confirmation."""
        answer = messagebox.askyesno(
            "Clear Backup History",
            "Are you sure you want to clear all backup history?\n\n"
            "This cannot be undone.",
            parent=self,
        )
        if not answer:
            return

        history_manager.clear()
        self._load_history()
        messagebox.showinfo(
            "History Cleared",
            "All backup history entries have been removed.",
            parent=self,
        )
