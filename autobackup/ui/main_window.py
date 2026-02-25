import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import time

from autobackup.cloud.credentials import CredentialManager
from autobackup.cloud.rclone_provider import RcloneProvider

from autobackup.core.backup_manager import BackupManager
from autobackup.config.settings import settings
from autobackup.models.backup_config import BackupConfig
from autobackup.models.backup_job import BackupJob
from autobackup.utils.logger import logger
from autobackup.utils.cron_detector import get_short_status_message, is_cron_available
from autobackup.ui.restore_dialog import RestoreDialog
from autobackup.ui.history_panel import HistoryPanel
from autobackup.core.scheduler_engine import (
    SchedulerEngine, FREQUENCY_DAILY, FREQUENCY_WEEKLY, FREQUENCY_CUSTOM,
    DAYS_OF_WEEK,
)




from autobackup.cloud.credentials import CredentialManager
from autobackup.cloud.rclone_provider import RcloneProvider

class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AutoBackup - Professional Edition")
        self.geometry("700x900")  # Increased height for cloud section


        self.backup_config: BackupConfig = settings.get_backup_config()
        self.backup_manager = BackupManager(self.backup_config)

        self.backup_manager.set_progress_callback(self._update_progress_ui)
        self.backup_manager.set_completion_callback(self._on_backup_completion)
        self.backup_manager.set_error_callback(self._on_backup_error)

        self._ui_update_queue: list[dict] = []

        # Scheduler engine — must be created BEFORE _load_config_to_ui()
        # because loading config calls _on_scheduler_toggle() which needs _scheduler.
        self._scheduler = SchedulerEngine(
            backup_callback=self._on_scheduled_backup_trigger,
            status_callback=lambda msg: self.after(0, lambda m=msg: self._update_scheduler_status(m)),
        )

        self._create_widgets()
        self._load_config_to_ui()

        # Initial check for cloud toggle rules
        self._on_cloud_toggle()

        self.after(100, self._check_for_ui_updates)

        # Auto-start scheduler if it was enabled in config
        self.after(1500, self._auto_start_scheduler)

        # Graceful shutdown
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

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

        # ---------- SAFETY WARNING ----------
        # Non-intrusive warning near destination field
        self.safety_label = ttk.Label(
            config_frame,
            text="⚠ Safety Note: Do not manually delete backup files",
            foreground="#d35400",  # Professional dark orange
            cursor="hand2",
            font=("TkDefaultFont", 8, "bold")
        )
        self.safety_label.grid(row=2, column=1, sticky="w", padx=5, pady=(0, 5))
        self.safety_label.bind("<Button-1>", lambda e: self._show_deletion_warning())
        
        # Add a clear helper explaining why
        ttk.Label(
            config_frame, 
            text="[?]", 
            foreground="blue", 
            cursor="hand2",
            font=("TkDefaultFont", 8)
        ).grid(row=2, column=2, sticky="w", padx=5)
        # Bind the help icon too
        config_frame.children[list(config_frame.children.keys())[-1]].bind("<Button-1>", lambda e: self._show_deletion_warning())

        # ---------- OPTIONS ----------
        self.dry_run_var = tk.BooleanVar()
        ttk.Checkbutton(config_frame, text="Dry Run", variable=self.dry_run_var).grid(row=3, column=0, columnspan=3, sticky="w")

        self.incremental_var = tk.BooleanVar()
        ttk.Checkbutton(config_frame, text="Incremental Backup", variable=self.incremental_var).grid(row=4, column=0, columnspan=3, sticky="w")

        self.encryption_var = tk.BooleanVar()
        ttk.Checkbutton(
            config_frame,
            text="Enable Encryption (GPG)",
            variable=self.encryption_var,
            command=self._toggle_password_entry,
        ).grid(row=5, column=0, sticky="w")

        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(config_frame, show="*", textvariable=self.password_var, state="disabled")
        self.password_entry.grid(row=5, column=1, sticky="ew", padx=5)
        
        # Help label for encryption
        self.encryption_help_label = ttk.Label(
            config_frame,
            text="⚠️ Encrypted files (.gpg) need decryption via Restore",
            foreground="orange",
            font=("TkDefaultFont", 8)
        )
        self.encryption_help_label.grid(row=5, column=2, sticky="w", padx=5)
        self.encryption_help_label.grid_remove()  # Hide initially

        self.compression_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(config_frame, text="Enable Compression", variable=self.compression_var).grid(
            row=6, column=0, columnspan=3, sticky="w"
        )


        # ---------- RETENTION POLICY ----------
        retention_frame = ttk.LabelFrame(config_frame, text="🗑 Retention Policy", padding="6")
        retention_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(5, 0))

        self.retention_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            retention_frame,
            text="Enable Retention Policy",
            variable=self.retention_enabled_var,
            command=self._on_retention_toggle,
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(retention_frame, text="Keep last:").grid(
            row=0, column=1, sticky="e", padx=(20, 5)
        )
        self.retention_count_var = tk.IntVar(value=5)
        self.retention_count_spin = ttk.Spinbox(
            retention_frame,
            from_=1, to=100,
            textvariable=self.retention_count_var,
            width=5,
            state="disabled",
        )
        self.retention_count_spin.grid(row=0, column=2, sticky="w")
        ttk.Label(retention_frame, text="backups").grid(
            row=0, column=3, sticky="w", padx=(3, 0)
        )

        self.retention_hint = ttk.Label(
            retention_frame,
            text="Automatically deletes oldest local + cloud backups after each backup.",
            font=("TkDefaultFont", 8),
            foreground="gray",
        )
        self.retention_hint.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))
        retention_frame.columnconfigure(1, weight=1)

        # Keep the old retention_policy_var for backward compatibility
        self.retention_policy_var = tk.StringVar(value="none")

        ttk.Label(config_frame, text="Auto Backup Interval (Days):").grid(row=8, column=0, sticky="w")
        self.backup_interval_days_var = tk.IntVar()
        self.backup_interval_days_entry = ttk.Entry(config_frame, textvariable=self.backup_interval_days_var)
        self.backup_interval_days_entry.grid(row=8, column=1, sticky="ew", padx=5)
        
        # Cron status indicator
        cron_status = get_short_status_message()
        cron_available = is_cron_available()
        self.cron_status_label = ttk.Label(
            config_frame, 
            text=cron_status,
            foreground="green" if cron_available else "orange"
        )
        self.cron_status_label.grid(row=8, column=2, sticky="w", padx=5)
        
        # Disable auto backup field if cron not available
        if not cron_available:
            self.backup_interval_days_entry.config(state="disabled")

        self.local_enabled_var = tk.BooleanVar(value=True)
        self.local_chk = ttk.Checkbutton(
            config_frame,
            text="Enable Local Backup (Default)",
            variable=self.local_enabled_var,
            command=self._on_local_toggle
        )
        self.local_chk.grid(row=9, column=0, columnspan=2, sticky="w")

        self.notifications_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(
            config_frame,
            text="Desktop Notifications",
            variable=self.notifications_enabled_var,
        ).grid(row=9, column=2, sticky="w")



        # ---------- CLOUD BACKUP ----------
        cloud_frame = ttk.LabelFrame(config_frame, text="☁ Remote Offsite Backup (via rclone)", padding="10")
        cloud_frame.grid(row=10, column=0, columnspan=3, sticky="ew", pady=10)
        
        self.cloud_enabled_var = tk.BooleanVar()
        self.cloud_chk = ttk.Checkbutton(
            cloud_frame, 
            text="Enable Cloud Backup", 
            variable=self.cloud_enabled_var,
            command=self._on_cloud_toggle
        )
        self.cloud_chk.grid(row=0, column=0, columnspan=2, sticky="w")
        
        # Connect Button (rclone based)
        self.connect_drive_btn = ttk.Button(
            cloud_frame, 
            text="Check gdrive Connection", 
            command=self._check_cloud_status_silent
        )
        self.connect_drive_btn.grid(row=1, column=0, pady=5, sticky="w")
        
        self.drive_status_label = ttk.Label(cloud_frame, text="⚪ Not Checked", foreground="gray")
        self.drive_status_label.grid(row=1, column=1, pady=5, sticky="w", padx=10)

        # Cloud backups are always archived — no user toggle needed.
        ttk.Label(
            cloud_frame,
            text="✔ Cloud backups are always archived for reliability.",
            font=("TkDefaultFont", 9, "bold"),
            foreground="#2e7d32",  # dark green — positive confirmation
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Label(
            cloud_frame,
            text="Archive (.tar/.tar.gz/.gpg) is uploaded directly — no folder sync.",
            font=("TkDefaultFont", 8),
            foreground="gray",
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=20)


        # ---------- SCHEDULER ----------
        sched_frame = ttk.LabelFrame(config_frame, text="⏰ Scheduler", padding="8")
        sched_frame.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        self.scheduler_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            sched_frame,
            text="Enable Scheduled Backup",
            variable=self.scheduler_enabled_var,
            command=self._on_scheduler_toggle,
        ).grid(row=0, column=0, sticky="w")

        self.scheduler_status_label = ttk.Label(
            sched_frame, text="⏸ Inactive", foreground="gray",
            font=("TkDefaultFont", 8, "bold"),
        )
        self.scheduler_status_label.grid(row=0, column=1, columnspan=3, sticky="e")

        ttk.Label(sched_frame, text="Frequency:").grid(row=1, column=0, sticky="w", pady=4)
        self.scheduler_freq_var = tk.StringVar(value="daily")
        self.scheduler_freq_combo = ttk.Combobox(
            sched_frame,
            values=["daily", "weekly", "custom"],
            textvariable=self.scheduler_freq_var,
            state="disabled",
            width=10,
        )
        self.scheduler_freq_combo.grid(row=1, column=1, sticky="w", padx=5)
        self.scheduler_freq_combo.bind("<<ComboboxSelected>>", self._on_scheduler_freq_change)

        ttk.Label(sched_frame, text="Time (HH:MM):").grid(row=1, column=2, sticky="e", padx=(10, 5))
        self.scheduler_time_var = tk.StringVar(value="22:00")
        self.scheduler_time_entry = ttk.Entry(
            sched_frame, textvariable=self.scheduler_time_var, width=6, state="disabled",
        )
        self.scheduler_time_entry.grid(row=1, column=3, sticky="w")

        ttk.Label(sched_frame, text="Day:").grid(row=2, column=0, sticky="w", pady=2)
        self.scheduler_day_var = tk.StringVar(value="Sunday")
        self.scheduler_day_combo = ttk.Combobox(
            sched_frame,
            values=DAYS_OF_WEEK,
            textvariable=self.scheduler_day_var,
            state="disabled",
            width=10,
        )
        self.scheduler_day_combo.grid(row=2, column=1, sticky="w", padx=5)

        ttk.Label(sched_frame, text="Interval (min):").grid(row=2, column=2, sticky="e", padx=(10, 5))
        self.scheduler_interval_var = tk.IntVar(value=60)
        self.scheduler_interval_spin = ttk.Spinbox(
            sched_frame, from_=1, to=1440,
            textvariable=self.scheduler_interval_var, width=6, state="disabled",
        )
        self.scheduler_interval_spin.grid(row=2, column=3, sticky="w")

        sched_frame.columnconfigure(2, weight=1)


        config_frame.columnconfigure(1, weight=1)

        # ------------------------------------------------------------------
        # CONTROL BUTTONS
        # ------------------------------------------------------------------

        control_frame = ttk.Frame(self, padding="10")
        control_frame.pack(fill="x")

        self.start_backup_btn = ttk.Button(control_frame, text="Start Backup", command=self._on_start_backup)
        self.start_backup_btn.pack(side="left", padx=5)
        ttk.Button(control_frame, text="Restore", command=self._on_restore).pack(side="left", padx=5)
        ttk.Button(control_frame, text="📋 History", command=self._on_show_history).pack(side="left", padx=5)
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

    def _show_deletion_warning(self):
        """Show a detailed warning about backup file deletion"""
        msg = (
            "IMPORTANT SAFETY INFORMATION\n\n"
            "1. Manual deletion of backup files will make restore impossible.\n"
            "   The backup system relies on the integrity of all files in the destination folder.\n\n"
            "2. Encryption does not protect against file deletion.\n"
            "   While encryption secures your data content, the files can still be deleted by "
            "anyone with access to the folder.\n\n"
            "Please manage backups only through this application to ensure data safety."
        )
        messagebox.showwarning("Backup Safety Warning", msg)

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
        self.backup_interval_days_var.set(cfg.backup_interval_days) 
        self.notifications_enabled_var.set(cfg.notifications_enabled)
        self.local_enabled_var.set(getattr(cfg, 'local_enabled', True))
        
        # Load Cloud Config
        self.cloud_enabled_var.set(cfg.cloud_enabled)
        # cloud_archive is always True — no checkbox needed

        # Retention config
        self.retention_enabled_var.set(getattr(cfg, 'retention_enabled', False))
        self.retention_count_var.set(getattr(cfg, 'retention_count', 5))
        self._on_retention_toggle()

        # Scheduler config
        self.scheduler_enabled_var.set(getattr(cfg, 'scheduler_enabled', False))
        self.scheduler_freq_var.set(getattr(cfg, 'scheduler_frequency', 'daily'))
        self.scheduler_time_var.set(getattr(cfg, 'scheduler_time', '22:00'))
        self.scheduler_day_var.set(getattr(cfg, 'scheduler_day', 'Sunday'))
        self.scheduler_interval_var.set(getattr(cfg, 'scheduler_interval_minutes', 60))
        self._on_scheduler_toggle()  # sync widget states
        
        # Cloud status initialized to 'Checking...' to avoid startup delay but show intent
        self.drive_status_label.config(text="⚪ Checking...", foreground="gray")

        self._toggle_password_entry()
        self._on_local_toggle() 
        
        # Non-blocking cloud check after window renders
        self.after(500, self._check_cloud_status_silent)

    def _check_cloud_status_silent(self):
        """Rule 6: Fast, non-blocking check for gdrive remote"""
        import threading
        def _check():
            try:
                provider = RcloneProvider()
                if not provider.is_rclone_available():
                    self.after(10, lambda: self.drive_status_label.config(text="❌ rclone missing", foreground="red"))
                    return

                is_connected = provider.test_connection()
                self.after(10, lambda: self._update_cloud_status_label(is_connected))
            except Exception:
                self.after(10, lambda: self.drive_status_label.config(text="⚪ Status Unknown", foreground="gray"))
        
        threading.Thread(target=_check, daemon=True).start()

    def _update_cloud_status_label(self, is_connected: bool):
        if is_connected:
            self.drive_status_label.config(text="✓ gdrive connected", foreground="green")
        else:
            self.drive_status_label.config(text="⚠ gdrive not found", foreground="orange")





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
        
        # Cloud Config
        cfg.local_enabled = self.local_enabled_var.get()
        cfg.cloud_enabled = self.cloud_enabled_var.get()
        cfg.cloud_archive = True   # always archive mode — folder sync removed
        cfg.cloud_provider = "rclone"

        # Retention Config
        cfg.retention_enabled = self.retention_enabled_var.get()
        try:
            count = self.retention_count_var.get()
            cfg.retention_count = max(1, count)
        except (tk.TclError, ValueError):
            cfg.retention_count = 5

        # Scheduler Config
        cfg.scheduler_enabled = self.scheduler_enabled_var.get()
        cfg.scheduler_frequency = self.scheduler_freq_var.get()
        cfg.scheduler_time = self.scheduler_time_var.get()
        cfg.scheduler_day = self.scheduler_day_var.get()
        try:
            cfg.scheduler_interval_minutes = max(1, self.scheduler_interval_var.get())
        except (tk.TclError, ValueError):
            cfg.scheduler_interval_minutes = 60

        return cfg

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def _on_save_config(self):
        try:
            cfg = self._get_config_from_ui()
            settings.save_backup_config(cfg)
            messagebox.showinfo("Saved", "Configuration saved successfully")
        except Exception as e:
            logger.exception(e)
            messagebox.showerror("Error", str(e))

    def _on_start_backup(self):
        cfg = self._get_config_from_ui()

        if not cfg.source:
            messagebox.showwarning("Missing Path", "Please select a source folder.")
            return
            
        if cfg.local_enabled and not cfg.destination:
            messagebox.showwarning("Missing Path", "Please select a destination folder for local backup.")
            return

        if cfg.encryption and not cfg.password:
            messagebox.showerror("Error", "Encryption enabled but password is empty")
            return

        # Validate retention count
        if cfg.retention_enabled:
            try:
                count = self.retention_count_var.get()
                if count < 1:
                    raise ValueError("Must be at least 1")
            except (tk.TclError, ValueError) as exc:
                messagebox.showerror(
                    "Invalid Retention",
                    f"Retention count must be a number >= 1.\n\n{exc}",
                )
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
        self.start_backup_btn.config(state="disabled") # Rule 10
        self.backup_manager.start_backup(dry_run=cfg.dry_run)

    def _on_restore(self):
        RestoreDialog(self, self.backup_manager)

    def _on_show_history(self):
        """Open the backup history panel."""
        HistoryPanel(self)

    def _on_local_toggle(self):
        """Rule: Local is independent of Cloud. Update UI state if needed."""
        pass

    def _on_cloud_toggle(self):
        """Rule: Cloud is independent of Local. Update UI state if needed."""
        pass

    def _on_retention_toggle(self):
        """Enable/disable the retention count spinbox based on checkbox."""
        if self.retention_enabled_var.get():
            self.retention_count_spin.config(state="normal")
            self.retention_hint.config(foreground="black")
        else:
            self.retention_count_spin.config(state="disabled")
            self.retention_hint.config(foreground="gray")

    # ------------------------------------------------------------------
    # SCHEDULER HANDLERS
    # ------------------------------------------------------------------

    def _on_scheduler_toggle(self, *_):
        """Enable/disable scheduler widgets and start/stop the engine."""
        enabled = self.scheduler_enabled_var.get()

        state = "readonly" if enabled else "disabled"
        entry_state = "normal" if enabled else "disabled"

        self.scheduler_freq_combo.config(state=state)
        self.scheduler_time_entry.config(state=entry_state)
        self.scheduler_day_combo.config(state=state if self.scheduler_freq_var.get() == "weekly" else "disabled")
        self.scheduler_interval_spin.config(state=entry_state if self.scheduler_freq_var.get() == "custom" else "disabled")

        if enabled:
            self._start_scheduler()
        else:
            self._scheduler.stop()
            self.scheduler_status_label.config(text="⏸ Inactive", foreground="gray")

    def _on_scheduler_freq_change(self, *_):
        """Adjust visible fields based on selected frequency."""
        freq = self.scheduler_freq_var.get()
        enabled = self.scheduler_enabled_var.get()

        if freq == "weekly" and enabled:
            self.scheduler_day_combo.config(state="readonly")
            self.scheduler_time_entry.config(state="normal")
            self.scheduler_interval_spin.config(state="disabled")
        elif freq == "custom" and enabled:
            self.scheduler_day_combo.config(state="disabled")
            self.scheduler_time_entry.config(state="disabled")
            self.scheduler_interval_spin.config(state="normal")
        elif enabled:
            # daily
            self.scheduler_day_combo.config(state="disabled")
            self.scheduler_time_entry.config(state="normal")
            self.scheduler_interval_spin.config(state="disabled")

        # Restart scheduler with new frequency if it's running
        if enabled and self._scheduler.is_running:
            self._start_scheduler()

    def _start_scheduler(self):
        """Configure and start (or restart) the scheduler engine."""
        self._scheduler.stop()
        self._scheduler.configure(
            frequency=self.scheduler_freq_var.get(),
            time_str=self.scheduler_time_var.get(),
            day_of_week=self.scheduler_day_var.get(),
            interval_minutes=self.scheduler_interval_var.get(),
        )
        self._scheduler.start()

    def _on_scheduled_backup_trigger(self):
        """
        Called by the scheduler engine from its daemon thread.
        We use after() to bounce to the main thread for safety.
        """
        self.after(0, self._run_scheduled_backup)

    def _run_scheduled_backup(self):
        """Run a scheduled backup on the main thread (UI-safe)."""
        # Guard: don't start if a backup is already in progress
        if str(self.start_backup_btn.cget("state")) == "disabled":
            logger.info("Scheduled backup skipped — another backup is in progress.")
            self._update_scheduler_status("⏰ Skipped (backup already running)")
            return

        logger.info("Scheduled backup triggered.")
        self._append_status("\n⏰ SCHEDULED BACKUP starting automatically...\n")

        # Read current config and start backup (reuses the same pipeline)
        cfg = self._get_config_from_ui()
        cfg.dry_run = False  # scheduled backups are always real

        self.start_backup_btn.config(state="disabled")
        self.progress_bar["value"] = 0
        self.progress_label.config(text="Starting scheduled backup...")

        self.backup_manager.config = cfg
        self.backup_manager.start_backup(dry_run=False)

    def _update_scheduler_status(self, msg: str):
        """Update the scheduler status label (must be called on main thread)."""
        if "active" in msg.lower() or "next" in msg.lower():
            self.scheduler_status_label.config(text=msg, foreground="#2e7d32")
        elif "stop" in msg.lower() or "inactive" in msg.lower():
            self.scheduler_status_label.config(text=msg, foreground="gray")
        else:
            self.scheduler_status_label.config(text=msg, foreground="blue")

    def _auto_start_scheduler(self):
        """Called once at startup — start scheduler if config says enabled."""
        if self.scheduler_enabled_var.get():
            logger.info("Auto-starting scheduler from saved config.")
            self._start_scheduler()

    def _on_closing(self):
        """Graceful shutdown — stop scheduler, then quit."""
        self._scheduler.stop()
        logger.info("AutoBackup application closed.")
        self.destroy()


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
            elif item.get("type") == "incremental_analysis":
                self._handle_incremental_analysis(item)
            elif item.get("type") == "cloud_progress":
                self._handle_cloud_progress(item)
            elif item.get("type") == "status_message":
                self._handle_status_message(item)
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
        
        # Smart size label based on mode and compression
        if is_dry_run:
            # Dry-run: show pre-compression size with appropriate label
            if job.config.compression:
                size_label = f"Estimated Size: {size_mb:.2f} MB (pre-compression)"
            else:
                size_label = f"Estimated Size: {size_mb:.2f} MB"
        else:
            # Real backup: show actual size
            if job.config.compression:
                # For compressed backups, show actual compressed size
                size_label = f"Compressed Size: {size_mb:.2f} MB"
            else:
                # For uncompressed backups, show actual size
                size_label = f"Size: {size_mb:.2f} MB"
        
        # Build feature flags
        features = []
        if job.config.compression:
            features.append("📦 Compressed")
        if job.config.encryption:
            features.append("🔒 Encrypted")
        if job.config.incremental:
            features.append("📂 Incremental")
        if job.config.cloud_enabled:
            features.append("☁ Cloud Uploaded")
        
        feature_text = f"\nFeatures: {', '.join(features)}" if features else ""
        
        # Add encryption note if encryption was used
        encryption_note = ""
        if job.config.encryption and not is_dry_run:
            encryption_note = (
                "\n\n⚠️ IMPORTANT: Files are encrypted as .gpg\n"
                "To access them, use the Restore feature\n"
                "with your decryption password."
            )
        
        msg_lines = [f"✓ {mode_label}", ""]
        
        # Display stats
        if job.config.local_enabled:
            msg_lines.append(f"Local Backup:")
            msg_lines.append(f"   Files: {job.files_transferred}{estimate_suffix}")
            msg_lines.append(f"   {size_label}")
        
        if job.config.cloud_enabled and not is_dry_run:
            cloud_size_mb = getattr(job, 'cloud_total_size_bytes', 0) / (1024**2)
            msg_lines.append("")
            msg_lines.append(f"Cloud Backup:")
            msg_lines.append(f"   Artifacts Uploaded: {getattr(job, 'cloud_files_transferred', 0)}")
            msg_lines.append(f"   Total Size: {cloud_size_mb:.2f} MB")
        
        msg_lines.append("")
        msg_lines.append(f"Duration: {job.duration_seconds:.2f}s")
        
        if feature_text:
            msg_lines.append(feature_text.strip())
            
        if encryption_note:
            msg_lines.append(encryption_note)

        # Retention summary
        retention_msg = getattr(job, 'retention_summary', None)
        if retention_msg and not is_dry_run:
            msg_lines.append("")
            msg_lines.append(f"🗑 {retention_msg}")

        msg = "\n".join(msg_lines)

        
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
        
        self._append_status("\n" + "="*60 + "\n")
        self._append_status("📋 DRY RUN DETAILED REPORT\n")
        self._append_status("="*60 + "\n\n")
        
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
                # Handle both dict (with size info) and string formats
                if isinstance(f, dict):
                    path = f.get('path', 'unknown')
                    size = f.get('size_human', 'N/A')
                    self._append_status(f"   {i}. {path:<45} ({size})\n")
                else:
                    self._append_status(f"   {i}. {f}\n")
            if len(new_files) > 20:
                self._append_status(f"   ... and {len(new_files) - 20} more\n")
            self._append_status("\n")
        
        # Show updated files (limit to first 20)
        if updated_files:
            self._append_status(f"🔄 UPDATED FILES ({len(updated_files)}):\n")
            for i, f in enumerate(updated_files[:20], 1):
                # Handle both dict (with size info) and string formats
                if isinstance(f, dict):
                    path = f.get('path', 'unknown')
                    size = f.get('size_human', 'N/A')
                    self._append_status(f"   {i}. {path:<45} ({size})\n")
                else:
                    self._append_status(f"   {i}. {f}\n")
            if len(updated_files) > 20:
                self._append_status(f"   ... and {len(updated_files) - 20} more\n")
            self._append_status("\n")
        
        # Show deleted files (limit to first 20)
        if deleted_files:
            self._append_status(f"🗑️  DELETED FILES ({len(deleted_files)}):\n")
            for i, f in enumerate(deleted_files[:20], 1):
                # Deleted files are usually just strings
                if isinstance(f, dict):
                    path = f.get('path', 'unknown')
                    self._append_status(f"   {i}. {path}\n")
                else:
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

    def _handle_cloud_progress(self, data: dict):
        """Handle cloud upload status updates"""
        percent = data.get("cloud_percent", 0)
        msg = data.get("message", "")
        # Different color or indicator?
        self.progress_label.config(text=msg)
        # Maybe use a secondary progress bar? Or just reuse main but change color style?
        # For simplicity, reuse main bar
        self.progress_bar["value"] = percent
        if msg and "Uploading" in msg:
            if not "Uploading" in self.status_text.get("end-2l", "end-1l"): # naive debounce
                 self._append_status(f"{msg}\n")

    # ------------------------------------------------------------------

    def _toggle_password_entry(self):
        is_encrypted = self.encryption_var.get()
        self.password_entry.config(state="normal" if is_encrypted else "disabled")
        # Show/hide encryption help label
        if is_encrypted:
            self.encryption_help_label.grid()
        else:
            self.encryption_help_label.grid_remove()

    def _handle_status_message(self, data: dict):
        """Append a generic status message to the log"""
        msg = data.get("message", "")
        if msg:
            self._append_status(f"{msg}\n")

    def _append_status(self, text: str):

        self.status_text.config(state="normal")
        self.status_text.insert(tk.END, text)
        self.status_text.see(tk.END)
        self.status_text.config(state="disabled")
