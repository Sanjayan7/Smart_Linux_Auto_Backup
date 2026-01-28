from typing import Callable, Optional
import threading
import datetime
import os
import subprocess
import shutil
import sys

from autobackup.models.backup_config import BackupConfig
from autobackup.models.backup_job import BackupJob
from autobackup.core.rsync_engine import RsyncEngine
from autobackup.utils.logger import logger


class BackupManager:
    CRON_JOB_MARKER = "# AUTOBACKUP_CRON_JOB"

    def __init__(self, config: BackupConfig):
        self.config = config
        self._current_job: Optional[BackupJob] = None
        self._rsync_engine = RsyncEngine()
        self._backup_thread: Optional[threading.Thread] = None

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

            backup_dir = self._create_backup_dir(job)

            link_dest = None
            if job.config.incremental and not job.config.encryption:
                link_dest = self._find_last_backup()

            # Capture rsync stats output
            rsync_stats = self._rsync_engine.run_rsync(
                source=job.config.source,
                destination=backup_dir,
                exclude_patterns=job.config.exclude_patterns,
                dry_run=job.config.dry_run,
                progress_callback=self._progress_callback,
                link_dest=link_dest,
                compress=job.config.compression,
            )

            # Use rsync stats for file count and size
            # For dry-run, use the parsed stats; for real backup, verify with actual calculation
            if job.config.dry_run:
                # In dry-run mode, use rsync's parsed statistics
                job.files_transferred = rsync_stats.get("number_of_files", 0)
                job.total_size_bytes = rsync_stats.get("total_file_size", 0)
            else:
                # For real backups, calculate actual size from created files
                files, size = self._calculate_backup_size(backup_dir)
                job.files_transferred = files
                job.total_size_bytes = size

            if job.config.encryption and not job.config.dry_run:
                self._encrypt_backup(backup_dir, job.config.password)

            job.end_time = datetime.datetime.now()
            job.duration_seconds = (job.end_time - job.start_time).total_seconds()

            job.status = "completed"

            if self._completion_callback:
                self._completion_callback(job)

        except Exception as e:
            job.status = "failed"
            job.end_time = datetime.datetime.now()
            if job.start_time:
                job.duration_seconds = (job.end_time - job.start_time).total_seconds()
            logger.exception(e)
            self._error(str(e))


    # -------------------------------------------------
    # HELPER METHODS (CLASS LEVEL)
    # -------------------------------------------------

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

    def _encrypt_backup(self, path: str, password: str):
        for root, _, files in os.walk(path):
            for f in files:
                if f.endswith(".gpg"):
                    continue
                src = os.path.join(root, f)
                dst = src + ".gpg"
                p = subprocess.Popen(
                    ["gpg", "--symmetric", "--batch", "--passphrase-fd", "0","--output", dst, src],
                    stdin=subprocess.PIPE,
                )
                p.communicate((password + "\n").encode())
                os.remove(src)

    def _apply_retention(self, dest: str, policy: str):
        if not policy or policy == "none":
            return

        count, unit = policy.split("_")
        count = int(count)
        now = datetime.datetime.now()

        delta = {
            "days": datetime.timedelta(days=count),
            "weeks": datetime.timedelta(weeks=count),
            "months": datetime.timedelta(days=count * 30),
            "years": datetime.timedelta(days=count * 365),
        }.get(unit)

        if not delta:
            return

        cutoff = now - delta

        for d in os.listdir(dest):
            p = os.path.join(dest, d)
            try:
                ts = d.split("_")[-2] + "_" + d.split("_")[-1]
                dt = datetime.datetime.strptime(ts, "%Y-%m-%d_%H-%M-%S")
                if dt < cutoff:
                    shutil.rmtree(p)
            except Exception:
                pass

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

    def list_backup_versions(self) -> list[str]:
        """List all available backup versions in the destination directory."""
        dest = self.config.destination
        if not os.path.isdir(dest):
            return []
        
        versions = []
        for item in os.listdir(dest):
            item_path = os.path.join(dest, item)
            if os.path.isdir(item_path):
                versions.append(item)
        
        # Sort by name (which includes timestamp) in reverse order (newest first)
        versions.sort(reverse=True)
        return versions

    def list_files_in_backup(self, backup_version_name: str, path_in_backup: str) -> list[dict]:
        """
        List files and directories in a specific path within a backup version.
        
        Args:
            backup_version_name: Name of the backup folder (e.g., "2026-01-28_10-27-06")
            path_in_backup: Relative path within the backup (empty string for root)
        
        Returns:
            List of dicts with keys: name, type (file/directory), size
        """
        backup_path = os.path.join(self.config.destination, backup_version_name)
        full_path = os.path.join(backup_path, path_in_backup) if path_in_backup else backup_path
        
        if not os.path.isdir(full_path):
            return []
        
        items = []
        try:
            for entry in os.listdir(full_path):
                entry_path = os.path.join(full_path, entry)
                is_dir = os.path.isdir(entry_path)
                
                item = {
                    "name": entry,
                    "type": "directory" if is_dir else "file",
                    "size": "" if is_dir else os.path.getsize(entry_path)
                }
                items.append(item)
        except PermissionError as e:
            logger.error(f"Permission denied accessing {full_path}: {e}")
        
        return items

    def restore_items(self, backup_version_name: str, items_to_restore: list[str], 
                     restore_dest: str, decryption_password: str = "") -> bool:
        """
        Restore selected items from a backup to a destination.
        
        Args:
            backup_version_name: Name of the backup folder
            items_to_restore: List of relative paths within the backup to restore
            restore_dest: Destination directory for restored files
            decryption_password: Password for decrypting .gpg files (if needed)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            backup_path = os.path.join(self.config.destination, backup_version_name)
            
            if not os.path.isdir(backup_path):
                raise ValueError(f"Backup version not found: {backup_version_name}")
            
            os.makedirs(restore_dest, exist_ok=True)
            
            for item_path in items_to_restore:
                source_path = os.path.join(backup_path, item_path)
                dest_path = os.path.join(restore_dest, item_path)
                
                if not os.path.exists(source_path):
                    logger.warning(f"Source path does not exist: {source_path}")
                    continue
                
                # Create parent directory for destination
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                
                if os.path.isdir(source_path):
                    # Copy entire directory
                    shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                else:
                    # Copy single file
                    shutil.copy2(source_path, dest_path)
                
                # Decrypt if it's a .gpg file and password provided
                if dest_path.endswith('.gpg') and decryption_password:
                    self._decrypt_file(dest_path, decryption_password)
            
            logger.info(f"Restore completed: {len(items_to_restore)} items to {restore_dest}")
            return True
            
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def _decrypt_file(self, gpg_file_path: str, password: str):
        """Decrypt a single .gpg file in place."""
        if not gpg_file_path.endswith('.gpg'):
            return
        
        output_file = gpg_file_path[:-4]  # Remove .gpg extension
        
        try:
            p = subprocess.Popen(
                ["gpg", "--decrypt", "--batch", "--passphrase-fd", "0", 
                 "--output", output_file, gpg_file_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            p.communicate((password + "\n").encode())
            
            if p.returncode == 0:
                # Decryption successful, remove .gpg file
                os.remove(gpg_file_path)
                logger.info(f"Decrypted: {gpg_file_path}")
            else:
                logger.error(f"Failed to decrypt {gpg_file_path}")
        except Exception as e:
            logger.error(f"Error decrypting {gpg_file_path}: {e}")
