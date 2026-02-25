"""
backup_history.py
=================
Persistent backup history storage.

Maintains a JSON file with one entry per backup (success or failure).
Thread-safe.  Handles missing / corrupted files gracefully.

Location:  ~/.config/autobackup/backup_history.json
"""

import json
import os
import threading
import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional

from autobackup.utils.logger import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HISTORY_DIR  = os.path.expanduser("~/.config/autobackup")
HISTORY_FILE = os.path.join(HISTORY_DIR, "backup_history.json")
MAX_ENTRIES  = 500  # cap to avoid unbounded growth


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class HistoryEntry:
    """One row in the backup history table."""
    timestamp: str            # "2026-02-25 21:31:47"
    mode: str                 # "Full" or "Incremental"
    size_mb: float            # archive size in MB
    files_count: int          # number of files backed up
    encrypted: bool
    compressed: bool
    cloud_uploaded: bool
    status: str               # "Success" or "Failed"
    duration_seconds: float = 0.0
    retention_note: str = ""  # e.g. "2 old backups removed"
    sha256: str = ""          # hex digest of final archive
    archive_filename: str = ""  # e.g. "backup_20260225220902.tar"


# ---------------------------------------------------------------------------
# History Manager
# ---------------------------------------------------------------------------

class BackupHistoryManager:
    """
    Thread-safe manager for reading / writing backup history.
    """

    def __init__(self, path: str = HISTORY_FILE):
        self._path = path
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_entry(self, entry: HistoryEntry) -> None:
        """Append a new entry and persist to disk."""
        with self._lock:
            entries = self._load_entries()
            entries.insert(0, asdict(entry))  # newest first

            # Cap size
            if len(entries) > MAX_ENTRIES:
                entries = entries[:MAX_ENTRIES]

            self._save_entries(entries)
            logger.info(
                f"Backup history: logged entry "
                f"({entry.status}, {entry.mode}, {entry.size_mb:.2f} MB)"
            )

    def get_entries(self) -> List[dict]:
        """Return all entries, newest first."""
        with self._lock:
            return self._load_entries()

    def clear(self) -> None:
        """Delete all history entries."""
        with self._lock:
            self._save_entries([])
            logger.info("Backup history cleared.")

    def record_from_job(self, job) -> None:
        """
        Convenience: build a HistoryEntry from a BackupJob and add it.

        Works for both successful and failed jobs.
        """
        cfg = job.config
        is_success = getattr(job, 'status', 'failed') == 'completed'

        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if job.end_time:
            ts = job.end_time.strftime("%Y-%m-%d %H:%M:%S")

        size_bytes = getattr(job, 'total_size_bytes', 0) or 0
        size_mb = round(size_bytes / (1024 ** 2), 2)

        mode = "Incremental" if getattr(cfg, 'incremental', False) else "Full"

        # Cloud: consider it uploaded only if cloud was enabled AND we transferred something
        cloud_ok = (
            getattr(cfg, 'cloud_enabled', False)
            and getattr(job, 'cloud_files_transferred', 0) > 0
        )

        retention_note = getattr(job, 'retention_summary', "") or ""

        entry = HistoryEntry(
            timestamp=ts,
            mode=mode,
            size_mb=size_mb,
            files_count=getattr(job, 'files_transferred', 0),
            encrypted=getattr(cfg, 'encryption', False),
            compressed=getattr(cfg, 'compression', False),
            cloud_uploaded=cloud_ok,
            status="Success" if is_success else "Failed",
            duration_seconds=round(getattr(job, 'duration_seconds', 0), 2),
            retention_note=retention_note,
            sha256=getattr(job, 'sha256_checksum', '') or '',
            archive_filename=getattr(job, 'archive_filename', '') or '',
        )
        self.add_entry(entry)

    def find_checksum_for_file(self, filename: str) -> Optional[str]:
        """
        Look up the SHA-256 checksum for a given archive filename.

        Returns the hex digest string, or None if not found or missing.
        """
        entries = self.get_entries()
        for entry in entries:
            stored_name = entry.get('archive_filename', '')
            if stored_name and stored_name == filename:
                sha = entry.get('sha256', '')
                return sha if sha else None
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_entries(self) -> List[dict]:
        """Load from disk, returning [] on any error."""
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            logger.warning(f"Backup history file has unexpected format, resetting.")
            return []
        except json.JSONDecodeError as exc:
            logger.warning(f"Backup history JSON corrupted ({exc}), resetting.")
            return []
        except Exception as exc:
            logger.error(f"Failed to load backup history: {exc}")
            return []

    def _save_entries(self, entries: List[dict]) -> None:
        """Write entries to disk atomically."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp_path = self._path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(entries, f, indent=2)
            os.replace(tmp_path, self._path)  # atomic on POSIX
        except Exception as exc:
            logger.error(f"Failed to save backup history: {exc}")
            # Clean up temp file if it exists
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

history_manager = BackupHistoryManager()
