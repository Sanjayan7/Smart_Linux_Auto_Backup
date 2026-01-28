import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import threading
from typing import List, Dict

from autobackup.core.backup_manager import BackupManager
from autobackup.utils.logger import logger

class RestoreDialog(tk.Toplevel):
    def __init__(self, parent, backup_manager: BackupManager):
        super().__init__(parent)
        self.parent = parent
        self.backup_manager = backup_manager
        self.title("Restore Files/Folders")
        self.geometry("800x600")
        self.transient(parent) # Make dialog appear on top of the parent window
        self.grab_set() # Modal dialog

        self._create_widgets()

    def _create_widgets(self):
        # Frame for backup selection
        backup_selection_frame = ttk.LabelFrame(self, text="Select Backup Version", padding="10")
        backup_selection_frame.pack(padx=10, pady=5, fill="x")

        ttk.Label(backup_selection_frame, text="Backup Destination:").grid(row=0, column=0, sticky="w", pady=2)
        self.backup_destination_entry = ttk.Entry(backup_selection_frame, width=60)
        self.backup_destination_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self.backup_destination_entry.insert(0, self.backup_manager.config.destination)
        self.backup_destination_entry.config(state="readonly") # Should reflect configured destination

        ttk.Label(backup_selection_frame, text="Available Backups:").grid(row=1, column=0, sticky="w", pady=2)
        self.backup_version_combobox = ttk.Combobox(backup_selection_frame, state="readonly")
        self.backup_version_combobox.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        self.backup_version_combobox.bind("<<ComboboxSelected>>", self._on_backup_version_selected)
        
        self.refresh_backups_button = ttk.Button(backup_selection_frame, text="Refresh", command=self._load_backup_versions)
        self.refresh_backups_button.grid(row=1, column=2, padx=5, pady=2)

        backup_selection_frame.grid_columnconfigure(1, weight=1)

        # Frame for file/folder browsing within selected backup
        files_frame = ttk.LabelFrame(self, text="Browse Backup Contents", padding="10")
        files_frame.pack(padx=10, pady=5, fill="both", expand=True)

        self.tree = ttk.Treeview(files_frame, columns=("type", "size"), show="tree headings")
        self.tree.heading("#0", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("size", text="Size")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open) # Handle folder expansion

        # Frame for restore destination and actions
        restore_frame = ttk.LabelFrame(self, text="Restore Options", padding="10")
        restore_frame.pack(padx=10, pady=5, fill="x")

        ttk.Label(restore_frame, text="Restore To:").grid(row=0, column=0, sticky="w", pady=2)
        self.restore_destination_entry = ttk.Entry(restore_frame, width=60)
        self.restore_destination_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self.restore_destination_browse_button = ttk.Button(restore_frame, text="Browse", command=self._browse_restore_destination)
        self.restore_destination_browse_button.grid(row=0, column=2, padx=5, pady=2)
        
        # Encryption password for restore
        ttk.Label(restore_frame, text="Decryption Password:").grid(row=1, column=0, sticky="w", pady=2)
        self.decryption_password_var = tk.StringVar()
        self.decryption_password_entry = ttk.Entry(restore_frame, width=30, show="*", textvariable=self.decryption_password_var)
        self.decryption_password_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=2)

        self.restore_button = ttk.Button(restore_frame, text="Restore Selected", command=self._on_restore_selected)
        self.restore_button.grid(row=2, column=0, columnspan=3, pady=10)

        restore_frame.grid_columnconfigure(1, weight=1)
        
        self._load_backup_versions() # Load versions on startup


    def _load_backup_versions(self):
        logger.info("Loading backup versions...")
        # Use a thread to avoid blocking UI
        threading.Thread(target=self._do_load_backup_versions).start()

    def _do_load_backup_versions(self):
        try:
            versions = self.backup_manager.list_backup_versions()
            self.parent.after(0, lambda: self._update_backup_versions_ui(versions))
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error loading backup versions: {error_msg}")
            self.parent.after(0, lambda msg=error_msg: messagebox.showerror("Error", f"Error loading backup versions: {msg}"))

    def _update_backup_versions_ui(self, versions: List[str]):
        self.backup_version_combobox['values'] = versions
        if versions:
            self.backup_version_combobox.set(versions[0])
            self._on_backup_version_selected() # Load contents of the latest backup
        else:
            self.backup_version_combobox.set("")
            self.tree.delete(*self.tree.get_children()) # Clear treeview
            messagebox.showinfo("No Backups", "No backup versions found in the destination.")

    def _on_backup_version_selected(self, event=None):
        selected_version = self.backup_version_combobox.get()
        if selected_version:
            logger.info(f"Selected backup version: {selected_version}")
            self.tree.delete(*self.tree.get_children()) # Clear current display
            # Load contents of the selected backup
            threading.Thread(target=self._do_load_backup_contents, args=(selected_version, "")).start() # Load root of backup

    def _do_load_backup_contents(self, backup_version_name: str, path_in_backup: str, parent_iid=""):
        try:
            items = self.backup_manager.list_files_in_backup(backup_version_name, path_in_backup)
            self.parent.after(0, lambda: self._update_treeview_ui(items, parent_iid))
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error loading contents of {backup_version_name}/{path_in_backup}: {error_msg}")
            self.parent.after(0, lambda msg=error_msg: messagebox.showerror("Error", f"Error loading backup contents: {msg}"))

    def _update_treeview_ui(self, items: List[Dict], parent_iid=""):
        for item in items:
            is_dir = item["type"] == "directory"
            item_iid = self.tree.insert(parent_iid, "end", text=item["name"], 
                                       values=(item["type"], item["size"] if not is_dir else ""), 
                                       tags=("directory" if is_dir else "file",),
                                       open=False)
            if is_dir:
                # Add a dummy child to make the folder expandable
                self.tree.insert(item_iid, "end", text="loading...", values=("", ""), tags=("dummy",))

    def _on_tree_open(self, event):
        item_iid = self.tree.focus()
        if not item_iid:
            return

        item_text = self.tree.item(item_iid, "text")
        item_values = self.tree.item(item_iid, "values")

        # Check if this is a directory with a dummy child
        if item_values and item_values[0] == "directory":
            children = self.tree.get_children(item_iid)
            if children:
                # Check if the first child is the dummy "loading..." item
                first_child = children[0]
                if self.tree.item(first_child, "text") == "loading...":
                    # Remove the dummy child
                    self.tree.delete(first_child)
                    
                    # Load actual contents
                    selected_version = self.backup_version_combobox.get()
                    current_path = self._get_path_from_iid(item_iid)
                    
                    threading.Thread(target=self._do_load_backup_contents, 
                                   args=(selected_version, current_path, item_iid)).start()

    def _get_path_from_iid(self, iid):
        """Constructs the full path of a treeview item from its iid."""
        path_parts = []
        while iid:
            path_parts.insert(0, self.tree.item(iid, "text"))
            iid = self.tree.parent(iid)
        # The first part is the root of the tree, which is the backup version name itself
        # We only want the path *within* the backup version
        if len(path_parts) > 1:
            return os.path.join(*path_parts[1:])
        return ""


    def _browse_restore_destination(self):
        directory = filedialog.askdirectory(parent=self, title="Select Restore Destination")
        if directory:
            self.restore_destination_entry.delete(0, tk.END)
            self.restore_destination_entry.insert(0, directory)

    def _on_restore_selected(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Restore", "No items selected for restore.")
            return

        selected_version_name = self.backup_version_combobox.get()
        if not selected_version_name:
            messagebox.showwarning("Restore", "No backup version selected.")
            return
        
        restore_dest = self.restore_destination_entry.get()
        if not restore_dest:
            messagebox.showwarning("Restore", "Please select a restore destination.")
            return
        
        decryption_password = self.decryption_password_var.get()

        items_to_restore = []
        for iid in selected_items:
            # Skip dummy "loading..." items
            item_text = self.tree.item(iid, "text")
            if item_text == "loading...":
                continue
                
            full_path_in_backup = self._get_path_from_iid(iid)
            if full_path_in_backup:  # Only add non-empty paths
                items_to_restore.append(full_path_in_backup)

        if not items_to_restore:
            messagebox.showwarning("Restore", "No valid items selected for restore.")
            return

        logger.info(f"Restoring {len(items_to_restore)} items from {selected_version_name} to {restore_dest}")
        # Run restore in a separate thread
        threading.Thread(target=self._do_restore_items, 
                        args=(selected_version_name, items_to_restore, restore_dest, decryption_password)).start()


    def _do_restore_items(self, backup_version_name: str, items_to_restore: List[str], restore_dest: str, decryption_password: str):
        try:
            success = self.backup_manager.restore_items(backup_version_name, items_to_restore, restore_dest, decryption_password)
            if success:
                self.parent.after(0, lambda: messagebox.showinfo("Restore Complete", "Selected items restored successfully."))
                logger.info("Restore completed successfully.")
            else:
                self.parent.after(0, lambda: messagebox.showerror("Restore Failed", "Failed to restore some items. Check logs."))
                logger.error("Restore failed.")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Unexpected error during restore: {error_msg}")
            self.parent.after(0, lambda msg=error_msg: messagebox.showerror("Restore Error", f"An unexpected error occurred during restore: {msg}"))
        finally:
            self.parent.after(0, self.destroy)
