import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import time

from autobackup.core.backup_manager import BackupManager
from autobackup.config.settings import settings
from autobackup.models.backup_config import BackupConfig
from autobackup.models.backup_job import BackupJob
from autobackup.utils.logger import logger
from autobackup.utils.cron_detector import get_short_status_message, is_cron_available
from autobackup.ui.restore_dialog import RestoreDialog


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AutoBackup - Professional Edition")
        self.geometry("650x730")

        self.backup_config: BackupConfig = settings.get_backup_config()
        self.backup_manager = BackupManager(self.backup_config)

        self.backup_manager.set_progress_callback(self._update_progress_ui)
        self.backup_manager.set_completion_callback(self._on_backup_completion)
        self.backup_manager.set_error_callback(self._on_backup_error)

        self._ui_update_queue: list[dict] = []

        self._create_widgets()
        self._load_config_to_ui()

        self.after(100, self._check_for_ui_updates)

    # ------------------------------------------------------------------
    # UI CREATION
    # ------------------------------------------------------------------

    def _create_widgets(self):
        config_frame = ttk.LabelFrame(self, text="Backup Configuration", padding="10")
        config_frame.pack(padx=10, pady=10, fill="x")

        # ---------- SOURCE ----------
        ttk.Label(config_frame, text="Source:").grid(row=0, column=0, sticky="w")
        self.source_entry = ttk.Entry(config_frame)
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(config_frame, text="Browse", command=self._browse_source).grid(row=0, column=2, padx=5)

        # ---------- DESTINATION ----------
        ttk.Label(config_frame, text="Destination:").grid(row=1, column=0, sticky="w")
        self.destination_entry = ttk.Entry(config_frame)
        self.destination_entry.grid(row=1, column=1, sticky="ew", padx=5)
        ttk.Button(config_frame, text="Browse", command=self._browse_destination).grid(row=1, column=2, padx=5)

        # ---------- OPTIONS ----------
        self.dry_run_var = tk.BooleanVar()
        ttk.Checkbutton(config_frame, text="Dry Run", variable=self.dry_run_var).grid(row=2, column=0, columnspan=3, sticky="w")

        self.incremental_var = tk.BooleanVar()
        ttk.Checkbutton(config_frame, text="Incremental Backup", variable=self.incremental_var).grid(row=3, column=0, columnspan=3, sticky="w")

        self.encryption_var = tk.BooleanVar()
        ttk.Checkbutton(
            config_frame,
            text="Enable Encryption (GPG)",
            variable=self.encryption_var,
            command=self._toggle_password_entry,
        ).grid(row=4, column=0, sticky="w")

        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(config_frame, show="*", textvariable=self.password_var, state="disabled")
        self.password_entry.grid(row=4, column=1, sticky="ew", padx=5)
        
        # Help label for encryption
        self.encryption_help_label = ttk.Label(
            config_frame,
            text="⚠️ Encrypted files (.gpg) need decryption via Restore",
            foreground="orange",
            font=("TkDefaultFont", 8)
        )
        self.encryption_help_label.grid(row=4, column=2, sticky="w", padx=5)
        self.encryption_help_label.grid_remove()  # Hide initially

        self.compression_var = tk.BooleanVar()
        ttk.Checkbutton(config_frame, text="Enable Compression", variable=self.compression_var).grid(
            row=5, column=0, columnspan=3, sticky="w"
        )

        ttk.Label(config_frame, text="Retention Policy:").grid(row=6, column=0, sticky="w")
        self.retention_policy_var = tk.StringVar()
        policies = ["none", "1_day", "3_days", "7_days", "1_week", "4_weeks", "1_month", "1_year"]
        ttk.Combobox(
            config_frame,
            values=policies,
            textvariable=self.retention_policy_var,
            state="readonly",
        ).grid(row=6, column=1, sticky="ew", padx=5)

        ttk.Label(config_frame, text="Auto Backup Interval (Days):").grid(row=7, column=0, sticky="w")
        self.backup_interval_days_var = tk.IntVar()
        self.backup_interval_days_entry = ttk.Entry(config_frame, textvariable=self.backup_interval_days_var)
        self.backup_interval_days_entry.grid(row=7, column=1, sticky="ew", padx=5)
        
        # Cron status indicator
        cron_status = get_short_status_message()
        cron_available = is_cron_available()
        self.cron_status_label = ttk.Label(
            config_frame, 
            text=cron_status,
            foreground="green" if cron_available else "orange"
        )
        self.cron_status_label.grid(row=7, column=2, sticky="w", padx=5)
        
        # Disable auto backup field if cron not available
        if not cron_available:
            self.backup_interval_days_entry.config(state="disabled")

        self.notifications_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(
            config_frame,
            text="Enable Desktop Notifications",
            variable=self.notifications_enabled_var,
        ).grid(row=8, column=0, columnspan=3, sticky="w")

        config_frame.columnconfigure(1, weight=1)

        # ------------------------------------------------------------------
        # CONTROL BUTTONS
        # ------------------------------------------------------------------

        control_frame = ttk.Frame(self, padding="10")
        control_frame.pack(fill="x")

        self.start_backup_btn = ttk.Button(control_frame, text="Start Backup", command=self._on_start_backup)
        self.start_backup_btn.pack(side="left", padx=5)
        ttk.Button(control_frame, text="Restore", command=self._on_restore).pack(side="left", padx=5)
        ttk.Button(control_frame, text="Save Config", command=self._on_save_config).pack(side="right", padx=5)

        # ------------------------------------------------------------------
        # PROGRESS
        # ------------------------------------------------------------------

        progress_frame = ttk.LabelFrame(self, text="Backup Progress", padding="10")
        progress_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill="x")

        self.progress_label = ttk.Label(progress_frame, text="Idle")
        self.progress_label.pack()

        self.status_text = tk.Text(progress_frame, height=6, state="disabled")
        self.status_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # BROWSE HELPERS
    # ------------------------------------------------------------------

    def _browse_source(self):
        path = filedialog.askdirectory(title="Select Source Folder")
        if path:
            self.source_entry.delete(0, tk.END)
            self.source_entry.insert(0, path)

    def _browse_destination(self):
        path = filedialog.askdirectory(title="Select Destination Folder")
        if path:
            self.destination_entry.delete(0, tk.END)
            self.destination_entry.insert(0, path)

    # ------------------------------------------------------------------
    # CONFIG HANDLING
    # ------------------------------------------------------------------

    def _load_config_to_ui(self):
        cfg = self.backup_config
        self.source_entry.insert(0, cfg.source)
        self.destination_entry.insert(0, cfg.destination)
        self.dry_run_var.set(cfg.dry_run)
        self.incremental_var.set(cfg.incremental)
        self.encryption_var.set(cfg.encryption)
        self.password_var.set(cfg.password or "")
        self.compression_var.set(cfg.compression)
        self.retention_policy_var.set(cfg.retention_policy)
        self.backup_interval_days_var.set(cfg.backup_interval_days) # Load new field
        self.notifications_enabled_var.set(cfg.notifications_enabled)
        self._toggle_password_entry()

    def _get_config_from_ui(self) -> BackupConfig:
        cfg = self.backup_config
        cfg.source = self.source_entry.get()
        cfg.destination = self.destination_entry.get()
        cfg.dry_run = self.dry_run_var.get()
        cfg.incremental = self.incremental_var.get()
        cfg.encryption = self.encryption_var.get()
        cfg.password = self.password_var.get() if cfg.encryption else None
        cfg.compression = self.compression_var.get()
        cfg.retention_policy = self.retention_policy_var.get()
        cfg.backup_interval_days = self.backup_interval_days_var.get() # Get new field
        cfg.notifications_enabled = self.notifications_enabled_var.get()
        return cfg

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def _on_save_config(self):
        try:
            settings.save_backup_config(self._get_config_from_ui())
            messagebox.showinfo("Saved", "Configuration saved successfully")
        except Exception as e:
            logger.exception(e)
            messagebox.showerror("Error", str(e))

    def _on_start_backup(self):
        cfg = self._get_config_from_ui()

        if not cfg.source or not cfg.destination:
            messagebox.showwarning("Missing Path", "Please select both source and destination folders.")
            return

        if cfg.encryption and not cfg.password:
            messagebox.showerror("Error", "Encryption enabled but password is empty")
            return

        # Disable the start button to prevent multiple concurrent backups
        self.start_backup_btn.config(state="disabled")
        
        self.progress_bar["value"] = 0
        
        # Clear status messages on dry-run vs real backup
        mode_text = "DRY-RUN backup" if cfg.dry_run else "REAL backup"
        self.progress_label.config(text=f"Starting {mode_text}...")
        self._append_status(f"\n{'='*50}\n")
        self._append_status(f"Starting {mode_text}...\n")
        
        # Show enabled features
        features = []
        if cfg.compression:
            features.append("📦 Compression")
        if cfg.encryption:
            features.append("🔒 Encryption")
        if cfg.incremental:
            features.append("📂 Incremental")
        if features:
            self._append_status(f"Features: {', '.join(features)}\n")

        self.backup_manager.config = cfg
        self.backup_manager.start_backup(dry_run=cfg.dry_run)

    def _on_restore(self):
        RestoreDialog(self, self.backup_manager)

    # ------------------------------------------------------------------
    # CALLBACKS FROM BACKUP THREAD
    # ------------------------------------------------------------------

    def _update_progress_ui(self, data: dict):
        self._ui_update_queue.append(data)

    def _on_backup_completion(self, job: BackupJob):
        self._ui_update_queue.append({"type": "completion", "job": job})

    def _on_backup_error(self, msg: str):
        self._ui_update_queue.append({"type": "error", "message": msg})

    def _check_for_ui_updates(self):
        while self._ui_update_queue:
            item = self._ui_update_queue.pop(0)
            if item.get("type") == "completion":
                self._handle_completion(item["job"])
            elif item.get("type") == "error":
                self._handle_error(item["message"])
            elif item.get("type") == "dry_run_summary":
                self._handle_dry_run_summary(item)
            elif item.get("type") == "incremental_analysis":
                self._handle_incremental_analysis(item)
            else:
                self._handle_progress(item)

        self.after(100, self._check_for_ui_updates)

    def _handle_progress(self, data: dict):
        percent = int(data.get("percentage", 0))
        self.progress_bar["value"] = percent
        self.progress_label.config(text=f"Progress: {percent}%")

    def _handle_completion(self, job: BackupJob):
        # Re-enable the start backup button
        self.start_backup_btn.config(state="normal")
        
        # Determine if this was a dry-run
        is_dry_run = job.config.dry_run
        mode_label = "Dry-Run Complete" if is_dry_run else "Backup Complete"
        estimate_suffix = " (estimated)" if is_dry_run else ""
        
        # Format size nicely
        size_mb = job.total_size_bytes / (1024**2)
        
        # Build feature flags
        features = []
        if job.config.compression:
            features.append("📦 Compressed")
        if job.config.encryption:
            features.append("🔒 Encrypted")
        if job.config.incremental:
            features.append("📂 Incremental")
        
        feature_text = f"\nFeatures: {', '.join(features)}" if features else ""
        
        # Add encryption note if encryption was used
        encryption_note = ""
        if job.config.encryption and not is_dry_run:
            encryption_note = (
                "\n\n⚠️ IMPORTANT: Files are encrypted as .gpg\n"
                "To access them, use the Restore feature\n"
                "with your decryption password."
            )
        
        msg = (
            f"✓ {mode_label}\n\n"
            f"Files: {job.files_transferred}{estimate_suffix}\n"
            f"Size: {size_mb:.2f} MB{estimate_suffix}\n"
            f"Duration: {job.duration_seconds:.2f}s"
            f"{feature_text}"
            f"{encryption_note}"
        )
        
        messagebox.showinfo(mode_label, msg)
        self._append_status(msg + "\n")
        self.progress_label.config(text=f"✓ {mode_label}")
        self.progress_bar["value"] = 100

    def _handle_error(self, msg: str):
        # Re-enable the start backup button
        self.start_backup_btn.config(state="normal")
        
        messagebox.showerror("Backup Failed", msg)
        self._append_status("❌ ERROR: " + msg + "\n")
        self.progress_label.config(text="❌ Backup failed")

    def _handle_dry_run_summary(self, data: dict):
        """Display detailed dry run summary with file lists"""
        new_files = data.get("new_files", [])
        updated_files = data.get("updated_files", [])
        deleted_files = data.get("deleted_files", [])
        total_would_transfer = data.get("total_would_transfer", 0)
        
        self._append_status("\n" + "="*50 + "\n")
        self._append_status("📋 DRY RUN DETAILED REPORT\n")
        self._append_status("="*50 + "\n\n")
        
        # Summary statistics
        self._append_status(f"📊 Summary:\n")
        self._append_status(f"   • Total files that would be transferred: {total_would_transfer}\n")
        self._append_status(f"   • New files: {len(new_files)}\n")
        self._append_status(f"   • Updated files: {len(updated_files)}\n")
        self._append_status(f"   • Deleted files: {len(deleted_files)}\n\n")
        
        # Show new files (limit to first 20)
        if new_files:
            self._append_status(f"✨ NEW FILES ({len(new_files)}):\n")
            for i, f in enumerate(new_files[:20], 1):
                self._append_status(f"   {i}. {f}\n")
            if len(new_files) > 20:
                self._append_status(f"   ... and {len(new_files) - 20} more\n")
            self._append_status("\n")
        
        # Show updated files (limit to first 20)
        if updated_files:
            self._append_status(f"🔄 UPDATED FILES ({len(updated_files)}):\n")
            for i, f in enumerate(updated_files[:20], 1):
                self._append_status(f"   {i}. {f}\n")
            if len(updated_files) > 20:
                self._append_status(f"   ... and {len(updated_files) - 20} more\n")
            self._append_status("\n")
        
        # Show deleted files (limit to first 20)
        if deleted_files:
            self._append_status(f"🗑️  DELETED FILES ({len(deleted_files)}):\n")
            for i, f in enumerate(deleted_files[:20], 1):
                self._append_status(f"   {i}. {f}\n")
            if len(deleted_files) > 20:
                self._append_status(f"   ... and {len(deleted_files) - 20} more\n")
            self._append_status("\n")
        
        if not new_files and not updated_files and not deleted_files:
            self._append_status("✓ No changes detected - backup is already up to date!\n\n")

    def _handle_incremental_analysis(self, data: dict):
        """Display incremental backup analysis statistics"""
        new_count = data.get("new_files_count", 0)
        modified_count = data.get("modified_files_count", 0)
        deleted_count = data.get("deleted_files_count", 0)
        unchanged_count = data.get("unchanged_files_count", 0)
        
        self._append_status("\n📊 INCREMENTAL BACKUP ANALYSIS\n")
        self._append_status(f"   ✨ New files: {new_count}\n")
        self._append_status(f"   🔄 Modified files: {modified_count}\n")
        self._append_status(f"   🗑️  Deleted files: {deleted_count}\n")
        self._append_status(f"   ✓ Unchanged files: {unchanged_count}\n")
        self._append_status(f"   💾 Efficiency: Only backing up {new_count + modified_count} changed files\n\n")

    # ------------------------------------------------------------------

    def _toggle_password_entry(self):
        is_encrypted = self.encryption_var.get()
        self.password_entry.config(state="normal" if is_encrypted else "disabled")
        # Show/hide encryption help label
        if is_encrypted:
            self.encryption_help_label.grid()
        else:
            self.encryption_help_label.grid_remove()

    def _append_status(self, text: str):
        self.status_text.config(state="normal")
        self.status_text.insert(tk.END, text)
        self.status_text.see(tk.END)
        self.status_text.config(state="disabled")
