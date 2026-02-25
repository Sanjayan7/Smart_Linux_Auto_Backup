from typing import Callable, Optional, Tuple, List
import threading
import datetime
import os
import subprocess
import shutil
import sys
import tarfile

from autobackup.core.retention_engine import RetentionEngine, RetentionResult
from autobackup.core.backup_history import history_manager
from autobackup.core.checksum import compute_sha256, verify_sha256

from autobackup.models.backup_config import BackupConfig
from autobackup.models.backup_job import BackupJob
from autobackup.core.rsync_engine import RsyncEngine
from autobackup.core.incremental_engine import IncrementalBackupEngine
from autobackup.core.cloud_restore_engine import (
    CloudRestoreEngine,
    CloudRestoreError,
    RcloneNotConfiguredError,
    CloudFileNotFoundError,
    DownloadFailedError,
    WrongPasswordError,
    ExtractionFailedError,
)
from autobackup.utils.logger import logger
from autobackup.cloud.rclone_provider import RcloneProvider
from autobackup.cloud.credentials import CredentialManager
import socket  # for machine_id


class BackupManager:
    CRON_JOB_MARKER = "# AUTOBACKUP_CRON_JOB"

    def __init__(self, config: BackupConfig):
        self.config = config
        self._current_job: Optional[BackupJob] = None
        self._rsync_engine = RsyncEngine()
        self._backup_thread: Optional[threading.Thread] = None
        
        
        # Incremental Engine (initialized per job)
        self._incremental_engine: Optional[IncrementalBackupEngine] = None

        self._progress_callback: Optional[Callable[[dict], None]] = None
        self._completion_callback: Optional[Callable[[BackupJob], None]] = None
        self._error_callback: Optional[Callable[[str], None]] = None

    # -------------------------------------------------

    def set_progress_callback(self, cb):
        self._progress_callback = cb

    def set_completion_callback(self, cb):
        self._completion_callback = cb

    def set_error_callback(self, cb):
        self._error_callback = cb

    # -------------------------------------------------

    def start_backup(self, dry_run: bool = False):
        if self._backup_thread and self._backup_thread.is_alive():
            self._error("Backup already running")
            return

        self.config.dry_run = dry_run

        job_id = "backup_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        job = BackupJob(id=job_id, config=self.config, status="running")
        self._current_job = job

        self._backup_thread = threading.Thread(
            target=self._run_backup_thread,
            args=(job,),
            daemon=True,
        )
        self._backup_thread.start()

    # -------------------------------------------------

    def _run_backup_thread(self, job: BackupJob):
        try:
            job.start_time = datetime.datetime.now()
            
            # --- 1. PHASE: DECIDE FULL VS INCREMENTAL ---
            use_incremental = False
            files_to_backup = []
            
            # Metadata path is always in the user's config dir for reboot-safety
            metadata_dir = os.path.expanduser("~/.config/autobackup")
            os.makedirs(metadata_dir, exist_ok=True)
            snapshot_path = os.path.join(metadata_dir, "snapshot.json")
            
            engine = IncrementalBackupEngine(snapshot_path, job.config.source)
            
            if job.config.incremental:
                if engine.load_metadata():
                    logger.info("Incremental backup: Detecting changes...")
                    new_files, modified_files, deleted_files = engine.detect_changes(job.config.exclude_patterns)
                    files_to_backup = new_files + modified_files
                    use_incremental = True
                    
                    if self._progress_callback:
                        self._progress_callback({
                            "type": "incremental_analysis",
                            "new_files_count": len(new_files),
                            "modified_files_count": len(modified_files),
                            "deleted_files_count": len(deleted_files),
                            "unchanged_files_count": len(engine.current_metadata) - len(files_to_backup)
                        })
                else:
                    logger.info("Incremental requested but no snapshot found. Forcing full.")
                    files_to_backup = [] # Empty list = all files (handled later)
            else:
                # Rule 2: Reset snapshot if Incremental is OFF
                if os.path.exists(snapshot_path):
                    os.remove(snapshot_path)
                    logger.info("Incremental OFF: Reset snapshot.")

            # --- 2. PHASE: CREATE ONE ARCHIVE (.tar) ---
            if self._progress_callback:
                self._progress_callback({"percentage": 5, "eta": "Preparing files..."})
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            temp_dir = "/tmp/autobackup_staging"
            os.makedirs(temp_dir, exist_ok=True)
            
            base_filename = f"backup_{timestamp}.tar"
            staging_path = os.path.join(temp_dir, base_filename)
            
            # Collect files if full backup
            if not use_incremental:
                engine.current_metadata = engine.scan_source_directory(job.config.exclude_patterns)
                files_to_backup = list(engine.current_metadata.keys())

            if not files_to_backup:
                 logger.info("No files to backup.")
                 # But we still might want to "complete" if something was deleted?
                 # Rule 5: 0 files backed up if no changes.
            
            # Create the Tar archive
            total_files = len(files_to_backup)
            job.files_transferred = total_files
            
            if total_files > 0:
                with tarfile.open(staging_path, "w") as tar:
                    for i, rel_path in enumerate(files_to_backup):
                        full_path = os.path.join(job.config.source, rel_path)
                        if os.path.exists(full_path):
                            tar.add(full_path, arcname=rel_path)
                        
                        if i % 10 == 0 and self._progress_callback:
                            percent = int((i / total_files) * 40) + 5 # 5% to 45%
                            self._progress_callback({"percentage": percent, "eta": f"Archiving {i}/{total_files}..."})
            else:
                # Create empty tar if needed? Or just skip. Let's skip if 0.
                if not job.config.local_enabled and not job.config.cloud_enabled:
                     raise ValueError("Nothing to do.")
            
            # --- 3. PHASE: OPTIONAL COMPRESSION ---
            final_artifact = staging_path
            if job.config.compression and os.path.exists(staging_path):
                if self._progress_callback:
                    self._progress_callback({"percentage": 50, "eta": "Compressing..."})
                
                compressed_path = staging_path + ".gz"
                # Use system gzip for speed
                subprocess.run(["gzip", "-f", staging_path], check=True)
                final_artifact = compressed_path
                logger.info(f"Compression complete: {final_artifact}")

            # --- 4. PHASE: OPTIONAL ENCRYPTION ---
            if job.config.encryption and os.path.exists(final_artifact):
                if self._progress_callback:
                    self._progress_callback({"percentage": 70, "eta": "Encrypting..."})
                
                if not job.config.password:
                    raise ValueError("Encryption enabled but no password provided.")
                
                encrypted_path = final_artifact + ".gpg"
                # Rule 3: GPG AES-256
                cmd = [
                    "gpg", "--symmetric", "--cipher-algo", "AES256",
                    "--batch", "--yes", "--passphrase-fd", "0",
                    "--output", encrypted_path, final_artifact
                ]
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                _, stderr = p.communicate(input=job.config.password.encode())
                
                if p.returncode != 0:
                    raise RuntimeError(f"GPG failed: {stderr.decode()}")
                
                os.remove(final_artifact)
                final_artifact = encrypted_path
                logger.info(f"Encryption complete: {final_artifact}")

            # FINAL STATS for the artifact
            if os.path.exists(final_artifact):
                job.total_size_bytes = os.path.getsize(final_artifact)

            # --- 4b. CHECKSUM: compute SHA-256 of the final archive ---
            job.archive_filename = os.path.basename(final_artifact) if os.path.exists(final_artifact) else ""
            if os.path.exists(final_artifact):
                if self._progress_callback:
                    self._progress_callback({"percentage": 82, "eta": "Computing integrity checksum..."})
                job.sha256_checksum = compute_sha256(final_artifact)
            else:
                job.sha256_checksum = ""
            
            # --- 5. PHASE: LOCAL BACKUP ---
            if job.config.local_enabled and os.path.exists(final_artifact):
                if self._progress_callback:
                    self._progress_callback({"percentage": 85, "eta": "Saving to local storage..."})
                
                local_dest = os.path.join(job.config.destination, os.path.basename(final_artifact))
                shutil.copy2(final_artifact, local_dest)
                logger.info(f"Local backup saved to: {local_dest}")

            # --- 6. PHASE: CLOUD BACKUP (always archive mode) ---
            if job.config.cloud_enabled:
                if self._progress_callback:
                    self._progress_callback({
                        "type": "cloud_progress",
                        "message": "☁ Uploading archive to Cloud (gdrive)...",
                        "cloud_percent": 0
                    })

                if not os.path.exists(final_artifact):
                    logger.error("Cloud upload skipped: archive artifact missing.")
                else:
                    provider = RcloneProvider()
                    if provider.test_connection():
                        # Cloud backups are ALWAYS uploaded as a single archive file.
                        # Folder/mirror mode is not supported — archives are reliable,
                        # portable, and directly restorable.
                        logger.info(f"Cloud upload (archive mode): {final_artifact}")
                        success = provider.upload_archive(final_artifact)

                        if success:
                            job.cloud_files_transferred = 1
                            job.cloud_total_size_bytes = job.total_size_bytes

                            # Verify checksum after upload (local file integrity)
                            if job.sha256_checksum and os.path.exists(final_artifact):
                                if not verify_sha256(final_artifact, job.sha256_checksum):
                                    raise RuntimeError(
                                        "Checksum mismatch after cloud upload — "
                                        "archive may be corrupted."
                                    )

                            if self._progress_callback:
                                self._progress_callback({
                                    "type": "cloud_progress",
                                    "message": "✔ Cloud backup completed",
                                    "cloud_percent": 100
                                })
                        else:
                            logger.error("Cloud archive upload failed.")
                            if self._progress_callback:
                                self._progress_callback({
                                    "type": "cloud_progress",
                                    "message": "❌ Cloud upload failed",
                                    "cloud_percent": 0
                                })
                    else:
                        logger.error("Cloud 'gdrive' remote not found or inaccessible.")
                        if self._progress_callback:
                            self._progress_callback({
                                "type": "cloud_progress",
                                "message": "❌ Cloud error: 'gdrive' remote not found",
                                "cloud_percent": 0
                            })

            # --- 7. CLEANUP & METADATA UPDATE ---
            # Rule 8: Metadata updated ONLY on successful backup
            engine.save_metadata("incremental" if use_incremental else "full")
            
            if os.path.exists(final_artifact) and final_artifact.startswith("/tmp"):
                 os.remove(final_artifact)

            job.end_time = datetime.datetime.now()
            job.duration_seconds = (job.end_time - job.start_time).total_seconds()
            job.status = "completed"

            # --- 8. RETENTION POLICY ---
            self._apply_retention(job)

            # --- 9. LOG TO BACKUP HISTORY ---
            history_manager.record_from_job(job)

            if self._completion_callback:
                self._completion_callback(job)

        except Exception as e:
            logger.exception(f"Backup failed: {e}")
            job.status = "failed"
            job.end_time = datetime.datetime.now()
            if job.start_time:
                job.duration_seconds = (job.end_time - job.start_time).total_seconds()
            self._error(str(e))
            # Log failed backup to history
            history_manager.record_from_job(job)
            if self._completion_callback:
                self._completion_callback(job)

    # -------------------------------------------------
    # RETENTION POLICY
    # -------------------------------------------------

    def _apply_retention(self, job) -> None:
        """
        Apply retention policy after a successful backup.

        Safety: never runs on dry-run or if retention is disabled.
        """
        cfg = job.config
        if not getattr(cfg, 'retention_enabled', False):
            return
        if getattr(cfg, 'dry_run', False):
            logger.info("Retention skipped (dry-run mode).")
            return

        keep = max(1, getattr(cfg, 'retention_count', 5))
        logger.info(f"Retention policy: keeping newest {keep} backup(s)")

        if self._progress_callback:
            self._progress_callback({
                "percentage": 97,
                "eta": f"Applying retention (keep {keep})..."
            })

        try:
            def _retention_progress(msg: str):
                if self._progress_callback:
                    self._progress_callback({
                        "percentage": 98,
                        "eta": msg,
                    })

            engine = RetentionEngine(
                keep_count=keep,
                progress_cb=_retention_progress,
            )
            result = engine.apply(
                local_dir=cfg.destination,
                cloud_enabled=cfg.cloud_enabled,
            )

            # Store result summary on the job for UI display
            job.retention_summary = result.summary_message()
            job.retention_deleted = result.total_deleted

        except Exception as exc:
            logger.error(f"Retention policy error: {exc}")
            job.retention_summary = f"Retention error: {exc}"
            job.retention_deleted = 0

    # -------------------------------------------------
    # HELPER METHODS (CLASS LEVEL)
    # -------------------------------------------------

    def _prepare_incremental_engine(self, config: BackupConfig) -> Tuple[bool, Optional[IncrementalBackupEngine]]:
        """
        Prepare and validate the incremental engine.
        
        Returns:
            (use_incremental: bool, engine: IncrementalBackupEngine)
        """
        # Rule 4: Incremental mode must be enabled AND no encryption
        if not config.incremental or config.encryption:
            logger.info(f"Configuring FULL backup: incremental={config.incremental}, encryption={config.encryption}")
            return False, None
            
        metadata_path = os.path.join(config.destination, "backup_metadata.json")
        engine = IncrementalBackupEngine(metadata_path, config.source)
        
        # Rule 10: Missing metadata = Full
        if not engine.metadata_exists():
            logger.info("Rule 1: No metadata found. Falling back to FULL backup.")
            return False, engine
            
        # Rule 10: Corrupted metadata = Full
        if not engine.load_metadata():
            logger.warning("Rule 10: Metadata corrupted. Falling back to FULL backup.")
            return False, engine
            
        logger.info(f"Metadata valid - using INCREMENTAL backup ({len(engine.stored_metadata)} tracked files)")
        return True, engine

    def _calculate_dry_run_size(self, dry_run_details: dict) -> int:
        """
        Calculate total size from dry-run file list.
        
        FALLBACK: Used when rsync --stats parsing returns 0 or fails.
        This ensures dry-run always shows realistic size, never 0.00 MB.
        
        Args:
            dry_run_details: Dict with 'new_files', 'updated_files', etc.
            
        Returns:
            Total size in bytes (0 if no data available)
        """
        total_bytes = 0
        
        # Iterate through files that would be transferred
        for file_list_name in ['new_files', 'updated_files']:
            file_list = dry_run_details.get(file_list_name, [])
            for file_item in file_list:
                # Preferred: Files are dicts with 'size_bytes' key
                if isinstance(file_item, dict):
                    total_bytes += file_item.get('size_bytes', 0)
                # Backward compatibility: Files might be strings (just filenames)
                elif isinstance(file_item, str):
                    try:
                        file_path = os.path.join(self.config.source, file_item)
                        if os.path.exists(file_path):
                            total_bytes += os.path.getsize(file_path)
                    except (OSError, TypeError):
                        pass  # Skip files we can't stat
        
        return total_bytes

    def _create_backup_dir(self, job: BackupJob) -> str:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = job.config.backup_name_template.replace("{timestamp}", ts)
        path = os.path.join(job.config.destination, name)
        os.makedirs(path, exist_ok=True)
        return path

    def _find_last_backup(self) -> Optional[str]:
        dest = self.config.destination
        if not os.path.isdir(dest):
            return None
        dirs = [os.path.join(dest, d) for d in os.listdir(dest)]
        dirs = [d for d in dirs if os.path.isdir(d)]
        return max(dirs, default=None)

    def _calculate_backup_size(self, path: str):
        total_size = 0
        file_count = 0
        for root, _, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    file_count += 1
                    total_size += os.path.getsize(fp)
        return file_count, total_size

    def _create_compressed_archive(self, backup_dir: str) -> Optional[str]:
        """
        Create a compressed tar.gz archive from backup directory.
        
        This creates an actual compressed archive file, replacing the
        backup directory with a single .tar.gz file. This ensures:
        
        1. Actual compressed size is reported (not pre-compression)
        2. Compressed backups are genuinely smaller than originals
        3. Users see different sizes for compressed vs uncompressed backups
        
        Args:
            backup_dir: Path to the backup directory
            
        Returns:
            Path to the created archive file, or None if creation failed
        """
        if not os.path.isdir(backup_dir):
            logger.error(f"Backup directory not found: {backup_dir}")
            return None
        
        try:
            # Create archive path: /dest/2026-02-04_14-30-00.tar.gz
            archive_path = backup_dir + ".tar.gz"
            
            logger.info(f"Creating compressed archive: {archive_path}")
            
            # Create tar.gz archive
            # arcname="." makes the archive contain just the contents, not the directory itself
            with tarfile.open(archive_path, "w:gz", compresslevel=9) as tar:
                # Get parent directory and backup directory name
                parent_dir = os.path.dirname(backup_dir)
                dir_name = os.path.basename(backup_dir)
                
                # Add entire backup directory to archive
                tar.add(backup_dir, arcname=dir_name, recursive=True)
            
            logger.info(f"Archive created successfully: {archive_path}")
            return archive_path
            
        except Exception as e:
            logger.error(f"Failed to create compressed archive: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _encrypt_archive(self, archive_path: str, password: str) -> Optional[str]:
        """
        Rule 2, 4: Encrypt archive using GPG AES-256 and delete original.
        
        Args:
            archive_path: Path to .tar.gz file
            password: User provided password
        
        Returns:
            Path to .tar.gz.gpg file if successful, None otherwise
        """
        if not os.path.exists(archive_path):
            return None
        
        output_path = archive_path + ".gpg"
        
        try:
            # Rule 2: GPG, Symmetric, AES-256
            cmd = [
                "gpg", "--symmetric", 
                "--cipher-algo", "AES256",
                "--batch", "--yes",
                "--passphrase-fd", "0",
                "--output", output_path,
                archive_path
            ]
            
            logger.info(f"Running GPG encryption: {output_path}")
            
            p = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = p.communicate(input=(password).encode())
            
            if p.returncode != 0:
                logger.error(f"GPG encryption failed: {stderr.decode()}")
                if os.path.exists(output_path):
                    os.remove(output_path)
                return None
            
            # Rule 4: Delete unencrypted source immediately
            os.remove(archive_path)
            logger.info(f"Encryption successful. insecure file deleted: {archive_path}")
            
            return output_path

        except Exception as e:
            logger.error(f"Encryption error: {e}")
            return None

    def _process_local_artifact(self, job: BackupJob, backup_dir: str):
        """Helper to handle compression and encryption of local backup."""
        # 1. Handle Compression
        if job.config.compression:
            if self._progress_callback:
                self._progress_callback({"percentage": 95, "eta": "Compressing..."})
            
            archive_path = self._create_compressed_archive(backup_dir)
            if archive_path and os.path.exists(archive_path):
                job.files_transferred = 1
                job.total_size_bytes = os.path.getsize(archive_path)
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
                if self._progress_callback:
                    self._progress_callback({"type": "status_message", "message": "✔ Backup compressed"})
            else:
                self._error("Compression failed.")
                return

        # 2. Handle Encryption
        if job.config.encryption:
            if self._progress_callback:
                self._progress_callback({"percentage": 97, "eta": "Encrypting..."})
            
            # Ensure we have an archive (encryption requires a single file)
            archive_path = backup_dir + ".tar.gz"
            if not os.path.exists(archive_path):
                archive_path = self._create_compressed_archive(backup_dir)
            
            if archive_path and os.path.exists(archive_path):
                encrypted_path = self._encrypt_archive(archive_path, job.config.password)
                if encrypted_path:
                    job.files_transferred = 1
                    job.total_size_bytes = os.path.getsize(encrypted_path)
                    if os.path.exists(backup_dir): shutil.rmtree(backup_dir)
                    if self._progress_callback:
                        self._progress_callback({"type": "status_message", "message": "✔ Backup encrypted"})
                else:
                    self._error("Encryption failed.")
            else:
                self._error("Failed to create archive for encryption.")
        
        # 3. Final Fallback (if no processing)
        if not job.config.compression and not job.config.encryption and os.path.exists(backup_dir):
            files, size = self._calculate_backup_size(backup_dir)
            job.files_transferred = files
            job.total_size_bytes = size
            if self._progress_callback:
                self._progress_callback({"type": "status_message", "message": "✔ Local backup completed"})

    # -------------------------------------------------
    # CLOUD HELPERS
    # -------------------------------------------------

    def _get_machine_id(self) -> str:
        """Get unique identifier for this machine."""
        return socket.gethostname()

    def _handle_cloud_upload(self, job: BackupJob, archive_path: str):
        """
        Handle the upload of an artifact to the cloud using rclone.
        Returns: True if successful, False otherwise.
        """
        logger.info(f"Starting cloud upload for: {archive_path}")
        
        # UI Update (Rule 9)
        if self._progress_callback:
            self._progress_callback({
                "type": "cloud_progress", 
                "message": "☁ Uploading to cloud...", 
                "cloud_percent": 0
            })
            
        try:
            provider = RcloneProvider()
            if not provider.test_connection():
                logger.error("Rclone 'gdrive' remote not found or inaccessible.")
                if self._progress_callback:
                    self._progress_callback({"type": "cloud_progress", "message": "❌ Rclone Config Error", "cloud_percent": 0})
                return False

            # Upload
            machine_id = self._get_machine_id() 
            filename = os.path.basename(archive_path)
            # Use machine_id as prefix for clarity in the cloud
            remote_path = f"{machine_id}_{filename}"
            
            def _upload_progress(bytes_sent, total):
                percent = int((bytes_sent / total) * 100)
                if self._progress_callback:
                    self._progress_callback({
                        "type": "cloud_progress",
                        "status": "uploading",
                        "cloud_percent": percent,
                        "message": f"☁ Uploading: {percent}%"
                    })

            success = provider.upload_file(
                local_path=archive_path,
                remote_path=remote_path,
                progress_callback=_upload_progress
            )
            
            if success:
                logger.info(f"Cloud upload successful: {remote_path}")
                if self._progress_callback:
                    self._progress_callback({
                        "type": "cloud_progress", 
                        "message": "✔ Cloud backup completed", 
                        "cloud_percent": 100
                    })
                return True

            else:
                logger.error("Cloud upload failed via rclone.")
                if self._progress_callback:
                    self._progress_callback({
                        "type": "cloud_progress", 
                        "message": "❌ Cloud upload failed", 
                        "cloud_percent": 0
                    })
                return False
        except Exception as e:
            logger.error(f"Cloud upload error: {e}")
            return False


    # -------------------------------------------------

    def _error(self, msg: str):
        logger.error(msg)
        if self._error_callback:
            self._error_callback(msg)

    def get_current_job_status(self) -> Optional[BackupJob]:
        return self._current_job

    # -------------------------------------------------
    # RESTORE METHODS
    # -------------------------------------------------

    def list_backup_versions(self) -> List[str]:
        """
        List both local and cloud backup versions.
        Cloud listing uses --files-only so plain cloud directories
        (e.g. 'Mirror') are never included.
        """
        versions = []
        
        # 1. Local versions
        if os.path.isdir(self.config.destination):
            for item in os.listdir(self.config.destination):
                if item.endswith(('.tar', '.tar.gz', '.tar.gz.gpg', '.gpg')):
                    versions.append(item)
                elif os.path.isdir(os.path.join(self.config.destination, item)):
                    versions.append(item)
        
        # 2. Cloud versions (files only — directories like 'Mirror' excluded)
        try:
            provider = RcloneProvider()
            if provider.test_connection():
                cloud_files = provider.list_cloud_backups()   # uses --files-only
                for item in cloud_files:
                    # Mark as cloud to distinguish in UI
                    versions.append(f"[Cloud] {item}")
        except Exception as e:
            logger.error(f"Failed to list cloud versions: {e}")
            
        # Sort newest first
        versions.sort(reverse=True)
        return versions

    def list_files_in_backup(self, backup_version_name: str, path_in_backup: str) -> list[dict]:
        """List files in archive or cloud mirror."""
        if backup_version_name.startswith("[Cloud]"):
             name_on_cloud = backup_version_name.replace("[Cloud] ", "")
             # If it's a directory (like 'Mirror') or a subfolder of it
             if not any(name_on_cloud.endswith(ext) for ext in [".tar", ".tar.gz", ".gpg"]):
                 provider = RcloneProvider()
                 remote_path = os.path.join(name_on_cloud, path_in_backup) if path_in_backup else name_on_cloud
                 return provider.list_directory(remote_path)
             
             return [{"name": "Cloud Archive (Full Restore Only)", "type": "file", "size": ""}]

        backup_path = os.path.join(self.config.destination, backup_version_name)
        
        # Handle Encrypted
        if backup_path.endswith((".gpg", ".enc")) or os.path.exists(backup_path + ".gpg"):
             return [{"name": "Encrypted Archive (Enter password to restore)", "type": "file", "size": ""}]

        # Handle Tarballs
        effective_path = backup_path
        if not os.path.exists(effective_path):
             if os.path.exists(backup_path + ".tar.gz"): effective_path = backup_path + ".tar.gz"
             elif os.path.exists(backup_path + ".tar"): effective_path = backup_path + ".tar"

        if os.path.isfile(effective_path) and effective_path.endswith((".tar", ".tar.gz")):
            items = []
            try:
                mode = "r:gz" if effective_path.endswith(".gz") else "r"
                with tarfile.open(effective_path, mode) as tar:
                    seen = set()
                    for member in tar.getmembers():
                        name = member.name.lstrip("/")
                        if path_in_backup and not name.startswith(path_in_backup):
                            continue
                        rel = name[len(path_in_backup):].lstrip("/")
                        if not rel: continue
                        part = rel.split("/")[0]
                        if part not in seen:
                            is_dir = member.isdir() or "/" in rel
                            items.append({
                                "name": part,
                                "type": "directory" if is_dir else "file",
                                "size": member.size if not is_dir else 0
                            })
                            seen.add(part)
                return items
            except Exception as e:
                logger.error(f"Tar listing failed: {e}")
                return []

        # Handle Directory
        if os.path.isdir(backup_path):
            items = []
            target = os.path.join(backup_path, path_in_backup) if path_in_backup else backup_path
            if os.path.exists(target):
                for e in os.listdir(target):
                    p = os.path.join(target, e)
                    d = os.path.isdir(p)
                    items.append({"name": e, "type": "directory" if d else "file", "size": os.path.getsize(p) if not d else 0})
            return items
            
        return []

    def restore_items(self, backup_version_name: str, items_to_restore: list[str], 
                      restore_dest: str, decryption_password: str = "") -> bool:
        temp_artifact = None
        try:
            logger.info(f"Restore requested for: {backup_version_name}")
            artifact_path = ""
            
            # Cloud Download
            if backup_version_name.startswith("[Cloud]"):
                filename = backup_version_name.replace("[Cloud] ", "")
                temp_artifact = os.path.join("/tmp", f"restore_{filename}")
                provider = RcloneProvider()
                if not provider.download_file(filename, temp_artifact):
                    raise RuntimeError("Cloud download failed.")
                artifact_path = temp_artifact
            else:
                artifact_path = os.path.join(self.config.destination, backup_version_name)
                # handle missing extensions if passed name without them
                if not os.path.exists(artifact_path):
                     for ext in [".tar.gz.gpg", ".tar.gz", ".tar"]:
                          if os.path.exists(artifact_path + ext):
                               artifact_path += ext
                               break

            if not os.path.exists(artifact_path):
                 raise FileNotFoundError(f"Restore artifact not found: {artifact_path}")

            # 1. Encrypted
            if artifact_path.endswith(".gpg"):
                return self._restore_from_encrypted_stream(artifact_path, items_to_restore, restore_dest, decryption_password)

            # 2. Tarball
            if artifact_path.endswith((".tar", ".tar.gz")):
                mode = "r:gz" if artifact_path.endswith(".gz") else "r"
                with tarfile.open(artifact_path, mode) as tar:
                    if not items_to_restore or backup_version_name.startswith("[Cloud]"):
                        tar.extractall(path=restore_dest)
                    else:
                        m = [mem for mem in tar.getmembers() if any(mem.name == iter or mem.name.startswith(iter+"/") for iter in items_to_restore)]
                        tar.extractall(path=restore_dest, members=m)
                return True

            # 3. Directory
            if os.path.isdir(artifact_path):
                if not items_to_restore:
                     # Full restore
                     shutil.copytree(artifact_path, restore_dest, dirs_exist_ok=True)
                     return True

                # Selective restore
                for item in items_to_restore:
                    source_path = os.path.join(artifact_path, item)
                    dest_path = os.path.join(restore_dest, item)
                    
                    if not os.path.exists(source_path):
                        logger.warning(f"Source path does not exist: {source_path}")
                        continue
                    
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    
                    if os.path.isdir(source_path):
                        shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                    else:
                        shutil.copy2(source_path, dest_path)
                return True
                
            return False
        finally:
            if temp_artifact and os.path.exists(temp_artifact):
                os.remove(temp_artifact)

    def _restore_from_encrypted_stream(self, gpg_path, items, dest, password):
        """Streaming decrypt and extract."""
        try:
            gpg_cmd = ["gpg", "--decrypt", "--batch", "--quiet", "--passphrase-fd", "0", gpg_path]
            # Use -z for gz decompression in tar if it was a .tar.gz.gpg
            tar_cmd = ["tar", "-x", "-C", dest]
            if ".gz" in gpg_path: tar_cmd.insert(1, "-z")

            gpg_p = subprocess.Popen(gpg_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            tar_p = subprocess.Popen(tar_cmd, stdin=gpg_p.stdout, stderr=subprocess.PIPE)
            gpg_p.stdout.close()
            
            gpg_p.stdin.write(password.encode() + b"\n")
            gpg_p.stdin.close()
            
            tar_p.communicate()
            gpg_p.wait()
            
            return gpg_p.returncode == 0 and tar_p.returncode == 0
        except Exception as e:
            logger.error(f"Decryption restore failed: {e}")
            return False

    # -------------------------------------------------
    # CLOUD RESTORE (delegated to CloudRestoreEngine)
    # -------------------------------------------------

    def list_cloud_backup_files(self) -> list[str]:
        """
        Return filenames available in gdrive:AutoBackup/.
        
        Raises CloudRestoreError subclasses on failure.
        Callers should catch those and surface the message to the UI.
        """
        engine = CloudRestoreEngine()
        return engine.list_cloud_backups()

    def restore_from_cloud(
        self,
        remote_filename: str,
        restore_destination: str,
        decryption_password: str = "",
        status_callback: "Optional[Callable[[str], None]]" = None,
        confirm_overwrite_callback: "Optional[Callable[[str], bool]]" = None,
    ) -> None:
        """
        Full cloud restore pipeline.

        Steps (executed by CloudRestoreEngine):
          1. Download  gdrive:AutoBackup/<remote_filename> → /tmp
          2. Decrypt   (if .gpg / .enc)
          3. Extract   (if .tar.gz / .tar)
          4. Restore   extracted files to restore_destination

        Parameters
        ----------
        remote_filename          : Filename as listed in the cloud.
        restore_destination      : Local folder to restore into.
        decryption_password      : GPG password (required only for encrypted archives).
        status_callback          : Called with each step's status message (thread-safe
                                   scheduling is the caller's responsibility).
        confirm_overwrite_callback: Called when destination is non-empty;
                                   should return True to proceed, False to abort.

        Raises
        ------
        RcloneNotConfiguredError   rclone / gdrive not ready
        CloudFileNotFoundError     selected file missing from cloud
        DownloadFailedError        rclone reported an error
        WrongPasswordError         GPG rejected the password
        ExtractionFailedError      tar extraction failed
        CloudRestoreError          any other failure
        """
        engine = CloudRestoreEngine(
            progress_cb=status_callback or (lambda msg: None),
            confirm_overwrite_cb=confirm_overwrite_callback or (lambda path: True),
        )
        engine.restore(
            remote_filename=remote_filename,
            restore_destination=restore_destination,
            decryption_password=decryption_password,
        )
