"""
cloud_restore_engine.py
=======================
Modular, production-grade engine for restoring backups from cloud storage.

Restore flow (STRICT ORDER as per spec):
  Step 1: Download selected archive from gdrive:AutoBackup/<file> → /tmp
  Step 2: Decrypt if .gpg or .enc
  Step 3: Extract if .tar.gz or .tar
  Step 4: Restore extracted files to destination
  Step 5: Cleanup temp files

Security rules enforced:
  - NEVER restores directly from a cloud path
  - Always: download first → decrypt → extract → restore
  - Wrong password → raises WrongPasswordError
  - Existing files require explicit confirmation (via callback)
"""

import os
import shutil
import subprocess
import tarfile
import tempfile
import logging
from typing import Callable, Optional

from autobackup.utils.logger import logger
from autobackup.core.checksum import compute_sha256
from autobackup.core.backup_history import history_manager


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class CloudRestoreError(Exception):
    """Base class for all cloud restore errors."""


class RcloneNotConfiguredError(CloudRestoreError):
    """rclone binary missing or 'gdrive' remote not configured."""


class CloudFileNotFoundError(CloudRestoreError):
    """The selected file does not exist in the cloud."""


class DownloadFailedError(CloudRestoreError):
    """rclone download failed."""


class WrongPasswordError(CloudRestoreError):
    """GPG decryption reported a bad password or authentication error."""


class ExtractionFailedError(CloudRestoreError):
    """tar extraction failed."""


# ---------------------------------------------------------------------------
# Progress step constants
# ---------------------------------------------------------------------------

STEP_DOWNLOADING  = "Downloading from cloud..."
STEP_VERIFYING    = "Verifying archive integrity..."
STEP_DECRYPTING   = "Decrypting..."
STEP_EXTRACTING   = "Extracting archive..."
STEP_RESTORING    = "Restoring folder structure..."
STEP_DONE         = "Cloud restore completed successfully"


# ---------------------------------------------------------------------------
# CloudRestoreEngine
# ---------------------------------------------------------------------------

class CloudRestoreEngine:
    """
    Executes cloud restore in strict, ordered phases.

    Callbacks
    ---------
    progress_cb(message: str)
        Called at the start of each step with a human-readable message.
    confirm_overwrite_cb(path: str) -> bool
        Called when the restore destination is non-empty.
        Return True to proceed, False to abort.
    """

    REMOTE_NAME  = "gdrive"
    CLOUD_FOLDER = "AutoBackup"

    # Timeout for rclone download (seconds).  Generous to support large files.
    DOWNLOAD_TIMEOUT = 7200  # 2 hours

    def __init__(
        self,
        progress_cb: Optional[Callable[[str], None]] = None,
        confirm_overwrite_cb: Optional[Callable[[str], bool]] = None,
    ):
        self._progress  = progress_cb  or (lambda msg: None)
        self._confirm   = confirm_overwrite_cb or (lambda path: True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_cloud_backups(self) -> list[str]:
        """
        Return a list of ARCHIVE FILES available in gdrive:AutoBackup/.

        Uses: rclone lsf --files-only gdrive:AutoBackup/

        Using --files-only ensures that plain cloud directories (e.g. 'Mirror')
        are never included in the restore list — only downloadable archive files
        (.tar, .tar.gz, .gpg, etc.) are shown.

        Raises
        ------
        RcloneNotConfiguredError  if rclone is missing or 'gdrive' not found.
        CloudRestoreError         on any unexpected failure.
        """
        self._assert_rclone_configured()

        remote_path = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/"
        logger.info(f"Listing cloud backup files at {remote_path}")

        result = subprocess.run(
            ["rclone", "lsf", "--files-only", remote_path],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            logger.error(f"rclone lsf failed: {stderr}")
            if "didn't find section in config file" in stderr or "no such remote" in stderr.lower():
                raise RcloneNotConfiguredError(
                    "'gdrive' remote is not configured in rclone. "
                    "Run 'rclone config' to set it up."
                )
            raise CloudRestoreError(f"Failed to list cloud backups: {stderr}")

        # Each line is a filename — strip any trailing whitespace
        files = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        ]
        logger.info(f"Found {len(files)} cloud archive(s): {files}")
        return files

    def restore(
        self,
        remote_filename: str,
        restore_destination: str,
        decryption_password: str = "",
    ) -> None:
        """
        Execute full cloud restore pipeline.

        Steps (in strict order):
          1. Download  archive from gdrive:AutoBackup/<remote_filename>
          2. Decrypt   (if .gpg / .enc)
          3. Extract   archive into a temp extraction directory
          4. Conflict-check: for each top-level item in the extracted tree,
             check if it already exists in restore_destination and ask the user
             for confirmation before overwriting.
          5. Restore   items preserving full folder structure.
             TemporaryDirectory cleanup is automatic.

        Raises
        ------
        RcloneNotConfiguredError   rclone / gdrive not ready
        CloudFileNotFoundError     file missing in cloud
        DownloadFailedError        rclone copy failed
        WrongPasswordError         bad decryption password
        ExtractionFailedError      tar failed
        CloudRestoreError          any other failure
        """
        self._assert_rclone_configured()
        os.makedirs(restore_destination, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="cloud_restore_") as tmp_dir:

            # ------------------------------------------------------------------
            # STEP 1 — Download
            # ------------------------------------------------------------------
            self._progress(STEP_DOWNLOADING)
            local_archive = self._download(remote_filename, tmp_dir)

            # ------------------------------------------------------------------
            # STEP 1b — Verify integrity (SHA-256)
            # ------------------------------------------------------------------
            self._progress(STEP_VERIFYING)
            self._verify_integrity(local_archive, remote_filename)

            # ------------------------------------------------------------------
            # STEP 2 — Decrypt (if needed)
            # ------------------------------------------------------------------
            decrypted_path = local_archive
            if self._is_encrypted(local_archive):
                self._progress(STEP_DECRYPTING)
                decrypted_path = self._decrypt(
                    local_archive, tmp_dir, decryption_password
                )

            # ------------------------------------------------------------------
            # STEP 3 — Extract into a dedicated sub-directory
            # ------------------------------------------------------------------
            extracted_dir = os.path.join(tmp_dir, "extracted")
            os.makedirs(extracted_dir, exist_ok=True)

            if self._is_archive(decrypted_path):
                self._progress(STEP_EXTRACTING)
                self._extract(decrypted_path, extracted_dir)
            else:
                # Not an archive — treat decrypted file as a single restore item
                shutil.copy2(decrypted_path, extracted_dir)

            # ------------------------------------------------------------------
            # STEP 4 — Conflict check (per top-level item)
            # ------------------------------------------------------------------
            # We now know exactly what folders/files are in the archive.
            # Check each top-level item against the destination and ask the user
            # only if there is an actual conflict — never blindly refuse.
            self._check_conflicts(extracted_dir, restore_destination)

            # ------------------------------------------------------------------
            # STEP 5 — Restore preserving folder structure
            # ------------------------------------------------------------------
            self._progress(STEP_RESTORING)
            self._restore_folder_structure(extracted_dir, restore_destination)

        # TemporaryDirectory cleaned up automatically on context exit
        self._progress(STEP_DONE)
        logger.info(f"Cloud restore completed → {restore_destination}")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assert_rclone_configured(self) -> None:
        """Raise RcloneNotConfiguredError if rclone or gdrive is unavailable."""
        # Check rclone binary
        which = subprocess.run(
            ["which", "rclone"], capture_output=True, text=True, timeout=5
        )
        if which.returncode != 0:
            raise RcloneNotConfiguredError(
                "rclone is not installed. Install it from https://rclone.org/install/"
            )

        # Check gdrive remote
        result = subprocess.run(
            ["rclone", "listremotes"],
            capture_output=True, text=True, timeout=10,
        )
        remotes = [r.strip().rstrip(":") for r in result.stdout.splitlines() if r.strip()]
        if self.REMOTE_NAME not in remotes:
            raise RcloneNotConfiguredError(
                f"rclone remote '{self.REMOTE_NAME}' is not configured. "
                "Run 'rclone config' to add it."
            )

    def _is_remote_directory(self, remote_filename: str) -> bool:
        """
        Return True if the remote path is a directory, False if it is a file.

        Uses rclone lsjson on the parent folder and checks the IsDir flag for
        the specific entry.  This is the only reliable way to distinguish a
        cloud directory from a file without attempting an actual download.
        """
        parent_remote = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/"
        result = subprocess.run(
            ["rclone", "lsjson", parent_remote],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False  # Assume file if we can't check
        try:
            import json
            items = json.loads(result.stdout)
            for item in items:
                if item.get("Name") == remote_filename:
                    return bool(item.get("IsDir", False))
        except Exception:
            pass
        return False

    def _verify_remote_file_exists(self, remote_filename: str) -> None:
        """
        Raise CloudFileNotFoundError if the named file is absent from the cloud.

        Checks the parent directory listing rather than probing the path directly,
        so the check works correctly for both files and directories.
        """
        parent_remote = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/"
        result = subprocess.run(
            ["rclone", "lsjson", parent_remote],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise CloudFileNotFoundError(
                f"Could not reach cloud storage to verify '{remote_filename}'.\n"
                f"rclone error: {result.stderr.strip()}"
            )
        try:
            import json
            items = json.loads(result.stdout)
            names = [item.get("Name") for item in items]
            if remote_filename not in names:
                raise CloudFileNotFoundError(
                    f"'{remote_filename}' was not found in gdrive:AutoBackup/.\n"
                    f"Available items: {names}"
                )
        except CloudFileNotFoundError:
            raise
        except Exception as exc:
            raise CloudRestoreError(
                f"Failed to parse cloud directory listing: {exc}"
            ) from exc

    def _verify_integrity(self, local_path: str, remote_filename: str) -> None:
        """
        Verify SHA-256 of a downloaded archive against the stored checksum
        in backup_history.json.

        - If a stored checksum exists and matches: log success, continue.
        - If a stored checksum exists but mismatches: raise CloudRestoreError.
        - If no stored checksum found: log warning, allow restore to proceed.
        """
        expected = history_manager.find_checksum_for_file(remote_filename)

        if expected is None:
            logger.warning(
                f"No stored checksum for {remote_filename} — "
                "integrity check skipped (older backup)."
            )
            return

        logger.info(f"Verifying integrity of {remote_filename}...")
        actual = compute_sha256(local_path)

        if actual == expected:
            logger.info(f"✓ Integrity verified: {remote_filename}")
        else:
            logger.error(
                f"✗ Integrity FAILED for {remote_filename}: "
                f"expected {expected[:16]}... got {actual[:16]}..."
            )
            raise CloudRestoreError(
                f"Backup integrity verification failed.\n\n"
                f"The downloaded file does not match the original checksum.\n"
                f"Expected: {expected[:16]}...\n"
                f"Got:      {actual[:16]}...\n\n"
                f"The archive may be corrupted. Restore aborted."
            )

    def _download(self, remote_filename: str, tmp_dir: str) -> str:
        """
        Download a single archive file from gdrive:AutoBackup/<remote_filename>
        into tmp_dir using:

            rclone copy gdrive:AutoBackup/<remote_filename> <tmp_dir>

        After the copy, the file will be present at:
            <tmp_dir>/<remote_filename>

        Returns the full local path to the downloaded file.

        Raises
        ------
        CloudFileNotFoundError   if the file does not exist in the cloud.
        DownloadFailedError      if rclone exits non-zero or the file is absent
                                 after a successful-looking run.
        """
        # ── Pre-flight: confirm the item exists AND is a file (not a folder) ──
        self._verify_remote_file_exists(remote_filename)

        if self._is_remote_directory(remote_filename):
            raise CloudFileNotFoundError(
                f"'{remote_filename}' is a cloud directory, not an archive file.\n"
                "Only single archive files (.tar, .tar.gz, .gpg …) can be restored.\n"
                "Please select an archive file from the Cloud Backup list."
            )

        remote_src  = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/{remote_filename}"
        local_dest  = os.path.join(tmp_dir, remote_filename)

        logger.info(f"rclone copy: {remote_src} → {tmp_dir}")

        result = subprocess.run(
            [
                "rclone", "copy",
                remote_src,       # source: exact file in the cloud
                tmp_dir,          # destination: local temp directory
                "--stats-one-line",
                "--stats=5s",
            ],
            capture_output=True,
            text=True,
            timeout=self.DOWNLOAD_TIMEOUT,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            logger.error(f"rclone download failed (rc={result.returncode}): {stderr}")
            raise DownloadFailedError(
                f"Failed to download '{remote_filename}' from cloud.\n"
                f"Details: {stderr or '(no details)'}"
            )

        # ── Post-flight: verify the file is actually present locally ──────────
        if not os.path.exists(local_dest):
            raise DownloadFailedError(
                f"rclone reported success but '{remote_filename}' is missing locally.\n"
                f"Expected path: {local_dest}\n"
                f"This usually means the remote path is a directory, not a file.\n"
                f"Make sure you select an archive file (.tar / .tar.gz / .gpg), "
                f"not a folder."
            )

        size = os.path.getsize(local_dest)
        logger.info(f"Download complete: {local_dest} ({size:,} bytes)")
        return local_dest

    def _is_encrypted(self, path: str) -> bool:
        """Return True if the file has a .gpg or .enc extension."""
        return path.endswith(".gpg") or path.endswith(".enc")

    def _is_archive(self, path: str) -> bool:
        """Return True if the file is a tar or tar.gz archive."""
        return path.endswith(".tar") or path.endswith(".tar.gz")

    def _decrypt(self, encrypted_path: str, work_dir: str, password: str) -> str:
        """
        Decrypt a GPG-encrypted file.

        Returns path to the decrypted output file.

        Raises WrongPasswordError if the password is rejected.
        """
        if not password:
            raise WrongPasswordError(
                "This backup is encrypted. Please provide the decryption password."
            )

        # Strip the .gpg / .enc suffix to determine output name
        base = os.path.basename(encrypted_path)
        if base.endswith(".gpg"):
            output_name = base[:-4]
        elif base.endswith(".enc"):
            output_name = base[:-4]
        else:
            output_name = base + ".decrypted"

        output_path = os.path.join(work_dir, output_name)

        cmd = [
            "gpg",
            "--decrypt",
            "--batch",
            "--quiet",
            "--yes",
            "--passphrase-fd", "0",
            "--output", output_path,
            encrypted_path,
        ]

        logger.info(f"Decrypting: {encrypted_path} → {output_path}")

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr = proc.communicate(input=(password + "\n").encode())

        if proc.returncode != 0:
            stderr_text = stderr.decode(errors="replace").strip()
            logger.error(f"GPG decryption failed (rc={proc.returncode}): {stderr_text}")

            # Detect wrong-password signals from GPG output
            bad_pass_signals = [
                "bad session key",
                "decryption failed",
                "bad passphrase",
                "no valid openPGP",
                "error decrypting",
            ]
            if any(sig in stderr_text.lower() for sig in bad_pass_signals):
                raise WrongPasswordError(
                    "Incorrect decryption password. Please try again."
                )

            raise CloudRestoreError(
                f"Decryption failed.\nDetails: {stderr_text or '(no details)'}"
            )

        if not os.path.exists(output_path):
            raise CloudRestoreError(
                "Decryption reported success but output file is missing."
            )

        logger.info(f"Decryption successful: {output_path}")
        return output_path

    def _extract(self, archive_path: str, extract_to: str) -> None:
        """
        Extract a .tar or .tar.gz archive into extract_to directory.

        Raises ExtractionFailedError on failure.
        """
        logger.info(f"Extracting: {archive_path} → {extract_to}")

        try:
            mode = "r:gz" if archive_path.endswith(".tar.gz") else "r"
            with tarfile.open(archive_path, mode) as tar:
                # Security: filter out absolute paths and '..' components
                safe_members = [
                    m for m in tar.getmembers()
                    if not os.path.isabs(m.name) and ".." not in m.name
                ]
                tar.extractall(path=extract_to, members=safe_members)
            logger.info(f"Extraction complete to: {extract_to}")
        except tarfile.TarError as exc:
            logger.error(f"tar extraction failed: {exc}")
            raise ExtractionFailedError(f"Archive extraction failed: {exc}") from exc
        except Exception as exc:
            logger.error(f"Unexpected extraction error: {exc}")
            raise ExtractionFailedError(f"Unexpected extraction error: {exc}") from exc

    def _check_conflicts(
        self,
        extracted_dir: str,
        destination: str,
    ) -> None:
        """
        Inspect every top-level item produced by extraction.
        If any of them already exist in *destination*, call the confirm callback
        once with a descriptive message.

        If the user declines, raises CloudRestoreError (restore aborted).
        """
        if not os.path.isdir(extracted_dir):
            return

        top_level_items = os.listdir(extracted_dir)
        conflicts = [
            item for item in top_level_items
            if os.path.exists(os.path.join(destination, item))
        ]

        if not conflicts:
            return  # No conflicts — safe to proceed

        conflict_names = "\n  • ".join(conflicts)
        confirm_msg = (
            f"The following items already exist in\n{destination}:\n\n"
            f"  • {conflict_names}\n\n"
            "They will be overwritten.  Continue?"
        )
        logger.warning(f"Restore conflict detected: {conflicts}")

        if not self._confirm(confirm_msg):
            raise CloudRestoreError(
                f"Restore aborted by user (conflicting items: {conflicts})."
            )

    def _restore_folder_structure(
        self,
        extracted_dir: str,
        destination: str,
    ) -> None:
        """
        Copy every top-level item from *extracted_dir* into *destination*,
        preserving full folder structure.

        Rule: files and directories are copied as-is, keeping their names.
              No flattening.  No renaming.  

        Example
        -------
        extracted_dir contains:
            ProjectFolder/
                file1.txt
                src/
                    main.py
            readme.txt

        After this call, destination contains:
            <destination>/ProjectFolder/
                file1.txt
                src/
                    main.py
            <destination>/readme.txt
        """
        if not os.path.isdir(extracted_dir):
            # Shouldn’t happen, but guard defensively
            raise CloudRestoreError(
                f"Extraction directory missing: {extracted_dir}"
            )

        items = os.listdir(extracted_dir)
        if not items:
            logger.warning("Extracted archive is empty — nothing to restore.")
            return

        logger.info(
            f"Restoring {len(items)} top-level item(s) to: {destination}"
        )

        for item in items:
            src  = os.path.join(extracted_dir, item)
            dest = os.path.join(destination, item)

            if os.path.isdir(src):
                logger.info(f"  [DIR]  {item}/ → {dest}/")
                # dirs_exist_ok=True means we merge into any pre-existing folder
                # (user already confirmed overwrite in _check_conflicts)
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                logger.info(f"  [FILE] {item} → {dest}")
                shutil.copy2(src, dest)

        logger.info(f"Folder structure restore complete: {destination}")

    # ------------------------------------------------------------------ #
    # Kept for backward-compat; internally replaced by _restore_folder_structure
    # ------------------------------------------------------------------ #
    def _copy_to_destination(self, source: str, destination: str) -> None:
        """Thin wrapper — delegates to _restore_folder_structure."""
        if os.path.isdir(source):
            self._restore_folder_structure(source, destination)
        else:
            shutil.copy2(source, os.path.join(destination, os.path.basename(source)))
            logger.info(f"File restored to: {destination}")
