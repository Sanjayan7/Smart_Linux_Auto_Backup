# 🏗️ Software Architecture Design: AutoBackup Pro

**Role:** Senior Software Architect  
**Paradigm:** Modular Layered Architecture  

---

## 1. Core Principles
1.  **Separation of Concerns:** UI code strictly handles display; Logic code handles data. UI never calls `boto3` or `rsync` directly.
2.  **Dependency Injection:** The `BackupController` receives its dependencies (like `S3Provider` or `RsyncEngine`) at runtime, making testing easy.
3.  **Single Source of Truth:** `Configuration` is loaded once into a Model object and passed down, rather than reading files deeply in utility functions.

---

## 2. Directory Structure & Responsibilities

### `autobackup/main.py`
The **Composition Root**. It initializes the Config, sets up the Logger, creates the Controller, and launches the UI. It wires everything together.

### `autobackup/config/`
*   **Responsibility:** Loading/Saving user preferences and secrets.
*   **Key Components:**
    *   `SettingsManager`: Reads `settings.json`, validates schema, returns a `BackupConfig` object.
    *   `CredentialStore`: Securely wraps `keyring` library interactions.

### `autobackup/core/`
*   **Responsibility:** The "Brain" of the application.
*   **Key Components:**
    *   `BackupController`: The primary API for the UI. Methods: `start_backup()`, `cancel_backup()`, `restore_files()`. It coordinates the *Sequence of Events* (e.g., "Scan -> Detect Changes -> Upload -> Save Metadata").
    *   `Scheduler`: If running partially in background, manages cron or timer threads.

### `autobackup/storage/`
*   **Responsibility:** Talking to the File System.
*   **Key Components:**
    *   `RsyncEngine`: Wraps the `rsync` subprocess calls, parsing stdout for progress bars.
    *   `IncrementalEngine`: Your recently built metadata tracker. It scans folders and returns `ChangedFile` lists.

### `autobackup/cloud/`
*   **Responsibility:** Talking to the Internet.
*   **Key Components:**
    *   `CloudProvider` (Interface): Defines `upload_file()`, `list_backups()`.
    *   `S3Provider`: Implements the interface for AWS.

### `autobackup/ui/`
*   **Responsibility:** Talking to the User.
*   **Key Components:**
    *   `MainForm`: The primary frame.
    *   `DashboardViewModel`: (Optional) Holds the state of the UI (progress %, status text) to decouple logic from widgets.

---

## 3. Data Flow Example: "Start Backup"

1.  **User** clicks "Start" in `ui/views/dashboard.py`.
2.  **UI** calls `controller.start_backup(dry_run=False)`.
3.  **BackupController**:
    *   Gets `config` from `SettingsManager`.
    *   Calls `IncrementalEngine.scan(source_path)`.
    *   Receives list of `changed_files`.
    *   **Loop:**
        *   Calls `RsyncEngine.sync(files)` (for local).
        *   Calls `S3Provider.upload(files)` (for cloud).
        *   Updates `JobStatus` object.
        *   Fires `on_progress` callback (UI updates progress bar).
4.  **Controller** calls `IncrementalEngine.save_metadata()`.
5.  **Controller** returns "Success".

---

## 4. Scalability Strategy

*   **Plugin System:** Adding "Google Drive" only requires adding `google_provider.py` implementing the defined Interface. No core logic changes needed.
*   **Background Workers:** The architecture supports moving `BackupController` logic into a separate `systemd` service or `Daemon`, with the UI just being a remote control (communicating via IPC/Sockets), if we need to scale to server-grade reliability later.

