
# ☁️ Cloud Backup Design Specification

**Role:** Senior Cloud Architect
**Project:** AutoBackup Professional
**Date:** 2026-02-07

---

## 1. High-Level Architecture Explanation
We utilize a **Hybrid-First Architecture** where the local machine remains the "Source of Truth". Cloud storage acts as an off-site immutable replica.

### Components:
1.  **Backup Core (Local)**: Performs the heavy lifting (Rsync, Compression, Encryption). This ensures CPU-intensive tasks happen locally, not slowing down the network.
2.  **Cloud Bridge (Middleware)**: A non-blocking asynchronous worker that watches for completed local backup jobs. It owns the "Internet connection" state and manages upload queues.
3.  **Storage Provider (S3 Interface)**: A polymorphic interface (currently AWS S3) that receives **only** pre-encrypted binary blobs. It has zero visibility into file contents (Zero-Knowledge Architecture).

### Diagram
```mermaid
graph LR
    User[User System] -->|1. Files| LocalEngine[Local Backup Engine]
    LocalEngine -->|2. Encrypt| Archive[Encrypted Archive (.gpg)]
    
    subgraph "Trust Boundary (Local)"
        Archive
        Creds[Keyring Credentials]
    end
    
    Archive -->|3. Streaming Upload| CloudBridge[Cloud Connector]
    Creds -->|Auth| CloudBridge
    
    subgraph "Public Internet"
        CloudBridge -->|4. Encrypted Blob| S3[AWS S3 Bucket]
    end
    
    S3 -.->|No Knowledge of Keys| Hacker[Attacker]
```

---

## 2. Cloud Upload Flow (Step-by-Step)

This flow is designed to be **fail-safe**. A cloud failure never jeopardizes the local backup.

1.  **Local Completion**: The `BackupManager` finishes creating the local encrypted archive (`backup_2026...tar.gz.gpg`).
2.  **Condition Check**:
    *   Verify `Cloud Backup` is enabled in config.
    *   Verify `Internet Connection` is active (ping check).
3.  **Authentication**:
    *   Retrieve Access/Secret keys from the **System Keyring** (not config file).
    *   Initialize `S3Provider` session.
4.  **Pathing Strategy**:
    *   Define Remote Path: `s3://bucket/machine_id/backups/YYYY-MM-DD_time.tar.gz.gpg`
5.  **Upload**:
    *   Initiate `multipart_upload` (boto3) for reliability on large files.
    *   Update UI Progress Bar (separate from local backup progress).
6.  **Verification**:
    *   Compare `Local file size` vs `S3 Object size`.
    *   (Optional) Compare `MD5 Checksum`.
7.  **Finalization**:
    *   Log success: "Cloud upload completed: [Remote Path]".
    *   *Note*: We do **not** delete the local file yet (retention policy handles that).

---

## 3. Cloud Restore Flow (Step-by-Step)

Reuse is key. We leverage the existing secure restore pipeline.

1.  **Discovery**:
    *   User opens "Restore" -> Selects "Cloud" tab.
    *   App lists objects in S3 bucket matching `machine_id/`.
2.  **Selection**: 
    *   User selects a backup timestamp (e.g., "Yesterday 4PM").
3.  **Staging**:
    *   App creates a secure temporary directory (`/tmp/autobackup_restore_xyz`).
    *   Downloads the specific `.gpg` object to this directory.
    *   *UI Message*: "Downloading encrypted archive (200MB)..."
4.  **Handover**:
    *   The app invokes the distinct `BackupManager.restore_items()` method, passing the path to the **downloaded temp file** as the source.
5.  **Decryption (Standard)**:
    *   Existing logic prompts for Password.
    *   Existing logic performs GPG decryption -> Untar -> Restore.
6.  **Cleanup**:
    *   Temporary downloaded file is securely wiped.

---

## 4. Failure Handling & Security

### Failure Scenarios
| Scenario | Action | User Feedback |
| :--- | :--- | :--- |
| **No Internet** | Skip Upload | Log warning: "Cloud skipped (Offline)". Icon turns gray. |
| **Invalid Creds** | Abort 403 | "Cloud Auth Failed. Check settings." Disable cloud to prevent locking. |
| **Quota Exceeded** | Abort 507 | "Cloud Storage Full." |
| **Interrupted Upload** | Retry chunk -> Abort | "Upload incomplete." (Partials are cleaned up by S3 Lifecycle) |

### Security Enforcement
1.  **Zero-Knowledge**: Valid GPG keys are **never** sent to the cloud. Only the encrypted blob goes out.
2.  **Credential Isolation**: AWS Keys are stored in `python-keyring` (D-Bus Secret Service / macOS Keychain), never in `settings.json`.
3.  **Sanitized Logs**: Logger explicitly filters out any string matching the "Secret Key" pattern.

---

## 5. UI/UX Wording & Options

**Settings Window:**
> **[ ] Enable Cloud Backup (Beta)**
> *Requires "Local Backup" to be enabled.*
>
> **Provider**: [ AWS S3 ▼ ]
> **Bucket**: `[ my-backup-bucket ]`
> **Credentials**: `[ Set Cloud Credentials... ]` (Opens secure dialog)
>
> *Status: ⚪ Idle*

**During Backup:**
> "Local Backup: 100% ✓"
> "Cloud Upload: 45% (Uploading encrypted archive...)"

**During Restore:**
> "Source: [☁ Cloud Storage]"
> "Available Snapshots: 5 found"

---

## 6. Python Implementation Snippets

### A. Cloud Upload Integration (in `BackupManager`)

```python
def _handle_cloud_upload(self, job: BackupJob, archive_path: str):
    """
    Called after successful local encryption.
    """
    if not job.config.cloud_enabled:
        return

    logger.info("Starting Cloud Upload phase...")
    
    # 1. Load Secure Credentials
    creds_mgr = CredentialManager(job.config.cloud_provider)
    creds = creds_mgr.load_credentials()
    if not creds:
        self._error("Cloud upload failed: No credentials found.")
        return

    # 2. Upload
    try:
        provider = S3Provider(creds)
        
        # Unique remote path
        filename = os.path.basename(archive_path)
        machine_id = self._get_machine_id() 
        remote_path = f"{machine_id}/{filename}"
        
        # Define progress callback for UI
        def _upload_progress(bytes_sent, total):
            percent = int((bytes_sent / total) * 100)
            if self._progress_callback:
                self._progress_callback({
                    "status": "uploading",
                    "cloud_percent": percent,
                    "message": f"Uploading to Cloud: {percent}%"
                })

        success = provider.upload_file(
            local_path=archive_path,
            remote_path=remote_path,
            progress_callback=_upload_progress
        )
        
        if success:
            logger.info(f"Cloud upload successful: {remote_path}")
        else:
            self._error("Cloud upload reported failure.")

    except Exception as e:
        logger.error(f"Cloud Exception: {e}")
```

### B. List Cloud Backups (in `BackupManager`)

```python
def list_cloud_backups(self) -> List[Dict]:
    """
    Connects to cloud to fetch available recovery points.
    """
    if not self.config.cloud_enabled:
        return []
        
    try:
        creds = CredentialManager(self.config.cloud_provider).load_credentials()
        provider = S3Provider(creds)
        
        machine_id = self._get_machine_id()
        # Assume provider has list_objects method (needs adding to Base/S3)
        objects = provider.list_objects(prefix=f"{machine_id}/")
        
        backups = []
        for obj in objects:
            # Parse filename "2026-02-07_10-00-00.tar.gz.gpg"
            # obj is dict: {'key': '...', 'size': 123, 'last_modified': datetime}
            backups.append({
                "name": os.path.basename(obj['key']),
                "size": obj['size'],
                "date": obj['last_modified'],
                "path": obj['key']
            })
        return sorted(backups, key=lambda x: x['date'], reverse=True)
            
    except Exception as e:
        logger.error(f"Failed to list cloud backups: {e}")
        return []
```

### C. Cloud Restore (in `BackupManager`)

```python
def download_cloud_backup(self, remote_key: str, download_dir: str) -> Optional[str]:
    """
    Downloads encrypted archive to a temp location for restoration.
    """
    try:
        creds = CredentialManager(self.config.cloud_provider).load_credentials()
        provider = S3Provider(creds)
        
        local_filename = os.path.basename(remote_key)
        local_path = os.path.join(download_dir, local_filename)
        
        logger.info(f"Downloading {remote_key}...")
        success = provider.download_file(remote_key, local_path)
        
        return local_path if success else None
        
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None
```

---

## 7. Professionalism & "Toy" Avoidance Strategy

This design avoids the "student project" look by:

1.  **Asynchronous Architecture**: We don't freeze the UI during a 2GB upload. We use callbacks and threading.
2.  **Proper Abstraction**: We don't hardcode `boto3.client` calls in the main window. We use a `CloudProvider` interface, allowing future expansion to Google Drive or Azure without rewriting the UI.
3.  **Security First**: We explicitly address the "hard problem" of credential storage using `keyring`. A toy app would save passwords in `config.txt`.
4.  **Resilience**: We check for network states and handle partial failures (Cloud fails != Backup fails).
5.  **Namespace Management**: We use `machine_id/` prefixes in the bucket, anticipating that a user might back up *multiple* computers to the same bucket.

Terminating design specification.
