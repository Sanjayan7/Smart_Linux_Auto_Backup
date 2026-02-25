"""
retention_engine.py
===================
Production-grade retention policy engine for AutoBackup.

Cleans up old backups after a successful backup, keeping only the most
recent N archives.  Operates on both local and cloud (gdrive) storage.

Rules
-----
  • Parse timestamps from filenames:  backup_YYYYMMDDHHMMSS.*
  • Sort newest first.
  • If total > keep_count, delete the oldest excess backups.
  • NEVER delete the most recent backup.
  • Log every deletion.

Usage
-----
    engine = RetentionEngine(keep_count=5)
    result = engine.apply(
        local_dir="/path/to/backups",
        cloud_enabled=True,
    )
    # result.local_deleted, result.cloud_deleted
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Callable

from autobackup.utils.logger import logger


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class RetentionResult:
    """Summary returned after retention is applied."""
    local_deleted: List[str] = field(default_factory=list)
    cloud_deleted: List[str] = field(default_factory=list)

    @property
    def total_deleted(self) -> int:
        return len(self.local_deleted) + len(self.cloud_deleted)

    def summary_message(self) -> str:
        """Human-friendly one-liner for the UI."""
        parts = []
        if self.local_deleted:
            parts.append(f"{len(self.local_deleted)} local")
        if self.cloud_deleted:
            parts.append(f"{len(self.cloud_deleted)} cloud")
        if not parts:
            return "Retention policy: no old backups to remove."
        removed_text = " + ".join(parts)
        return f"Retention policy applied. {removed_text} old backup(s) removed."


# ---------------------------------------------------------------------------
# Timestamp extraction
# ---------------------------------------------------------------------------

# Matches: backup_20260225211644.tar, backup_20260225211644.tar.gz,
#           backup_20260225211644.tar.gz.gpg, etc.
_TIMESTAMP_RE = re.compile(r"backup_(\d{14})")


def _extract_timestamp(filename: str) -> Optional[str]:
    """Return the 14-digit timestamp string from a backup filename, or None."""
    m = _TIMESTAMP_RE.search(filename)
    return m.group(1) if m else None


def _sort_by_timestamp_descending(filenames: List[str]) -> List[str]:
    """
    Sort backup filenames newest-first using their embedded timestamp.
    Files without a parseable timestamp are excluded.
    """
    timestamped = [
        (fn, ts)
        for fn in filenames
        if (ts := _extract_timestamp(fn)) is not None
    ]
    timestamped.sort(key=lambda pair: pair[1], reverse=True)
    return [fn for fn, _ in timestamped]


# ---------------------------------------------------------------------------
# RetentionEngine
# ---------------------------------------------------------------------------

class RetentionEngine:
    """
    Applies retention policy: keep the newest *keep_count* backups,
    delete the rest.
    """

    REMOTE_NAME  = "gdrive"
    CLOUD_FOLDER = "AutoBackup"

    def __init__(
        self,
        keep_count: int = 5,
        progress_cb: Optional[Callable[[str], None]] = None,
    ):
        if keep_count < 1:
            raise ValueError("keep_count must be at least 1.")
        self._keep = keep_count
        self._progress = progress_cb or (lambda msg: None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(
        self,
        local_dir: str,
        cloud_enabled: bool = False,
    ) -> RetentionResult:
        """
        Run retention for both local and (optionally) cloud backups.

        Parameters
        ----------
        local_dir       Path to the local backup directory.
        cloud_enabled   Whether to also prune cloud backups.

        Returns
        -------
        RetentionResult with lists of deleted filenames.
        """
        result = RetentionResult()

        # ── Local retention ───────────────────────────────────────────
        try:
            result.local_deleted = self._apply_local(local_dir)
        except Exception as exc:
            logger.error(f"Local retention failed: {exc}")

        # ── Cloud retention ───────────────────────────────────────────
        if cloud_enabled:
            try:
                result.cloud_deleted = self._apply_cloud()
            except Exception as exc:
                logger.error(f"Cloud retention failed: {exc}")

        # ── Summary ──────────────────────────────────────────────────
        msg = result.summary_message()
        logger.info(msg)
        self._progress(msg)

        return result

    # ------------------------------------------------------------------
    # Local retention
    # ------------------------------------------------------------------

    def _apply_local(self, local_dir: str) -> List[str]:
        """Delete excess local backup archives, return list of deleted names."""
        if not os.path.isdir(local_dir):
            logger.warning(f"Local backup directory does not exist: {local_dir}")
            return []

        # List only archive files (tar, tar.gz, gpg variants)
        all_files = [
            f for f in os.listdir(local_dir)
            if os.path.isfile(os.path.join(local_dir, f))
            and _extract_timestamp(f) is not None
        ]

        sorted_files = _sort_by_timestamp_descending(all_files)
        logger.info(
            f"Retention (local): {len(sorted_files)} backup(s) found, "
            f"keeping newest {self._keep}"
        )

        if len(sorted_files) <= self._keep:
            return []

        to_delete = sorted_files[self._keep:]
        deleted = []

        for filename in to_delete:
            filepath = os.path.join(local_dir, filename)
            try:
                os.remove(filepath)
                logger.info(f"  [LOCAL DELETE] {filename}")
                deleted.append(filename)
            except OSError as exc:
                logger.error(f"  [LOCAL DELETE FAILED] {filename}: {exc}")

        return deleted

    # ------------------------------------------------------------------
    # Cloud retention
    # ------------------------------------------------------------------

    def _apply_cloud(self) -> List[str]:
        """Delete excess cloud backup archives, return list of deleted names."""
        cloud_files = self._list_cloud_files()

        sorted_files = _sort_by_timestamp_descending(cloud_files)
        logger.info(
            f"Retention (cloud): {len(sorted_files)} backup(s) found, "
            f"keeping newest {self._keep}"
        )

        if len(sorted_files) <= self._keep:
            return []

        to_delete = sorted_files[self._keep:]
        deleted = []

        for filename in to_delete:
            if self._delete_cloud_file(filename):
                deleted.append(filename)

        return deleted

    def _list_cloud_files(self) -> List[str]:
        """List archive files in gdrive:AutoBackup/ (files only)."""
        remote_path = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/"
        result = subprocess.run(
            ["rclone", "lsf", "--files-only", remote_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error(f"rclone lsf failed: {result.stderr.strip()}")
            return []

        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _delete_cloud_file(self, filename: str) -> bool:
        """Delete a single file from gdrive:AutoBackup/."""
        remote_path = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/{filename}"
        logger.info(f"  [CLOUD DELETE] {filename}")

        try:
            result = subprocess.run(
                ["rclone", "deletefile", remote_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error(
                    f"  [CLOUD DELETE FAILED] {filename}: {result.stderr.strip()}"
                )
                return False
            return True
        except Exception as exc:
            logger.error(f"  [CLOUD DELETE FAILED] {filename}: {exc}")
            return False
