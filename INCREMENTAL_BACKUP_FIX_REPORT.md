# Incremental Backup Logic Fix Report

## 1. Why the Old Logic Was Incorrect

The previous incremental backup implementation using `MetadataTracker` failed to strictly adhere to professional backup standards, leading to the following issues:

1.  **Metadata-State Disconnect**: The metadata update mechanism re-scanned the source directory *after* the backup completed (`update_metadata` calls `scan_directory`). This created a "race condition" where if a file changed *during* the backup process, the metadata would record the *new* state (mtime/size) while the backup archive actually contained the *old* version. On the next run, the system would compare the file on disk (state T2) with the metadata (state T2) and assume no change, incorrectly ignoring the fact that the backup only holds the T1 version.
    *   **Fix**: Update metadata using the *exact state* that was used for change detection, rather than re-scanning.

2.  **Compression Conflict**: The user reported issues "specifically when compression is enabled". The previous logic attempted to use `link_dest` (hard links) pointing to previous backups. However, when compression is enabled, the previous backup directory is converted to a `.tar.gz` file and the directory is removed.
    *   **Result**: `_find_last_backup` returns `None` (or an older uncompressed folder).
    *   **Consequence**: Without a valid `link_dest`, an incremental run might default to a full backup behavior depending on the rsync flags, or fail to link unchanged files.
    *   **Fix**: Strictly rely on metadata for file selection. Do NOT rely on `link_dest` for determining *what* to backup. The incremental engine explicitly produces a list of modified/new files, and *only* those are passed to the archiver.

3.  **Ambiguous Change Detection**: The `MetadataTracker` combined change detection with status updates in a way that didn't strictly separate "decision" from "execution".
    *   **Fix**: Separate the *decision phase* (compare source vs stored metadata) from the *execution phase* (copy files) and *finalization phase* (save metadata).

## 2. Exact Incremental Backup Algorithm (Step-by-step)

1.  **Initialize**:
    *   Load `metadata.json` from the backup destination.
    *   If missing or corrupted, flag strictly as **FULL BACKUP**.

2.  **Scan Source**:
    *   Walk the source directory (respecting exclude patterns).
    *   For each file, calculate: `rel_path`, `size`, `mtime`, and `sha256_hash`.
    *   Build `current_source_state` map.

3.  **Detect Changes (Decision Phase)**:
    *   If FULL BACKUP flagged:
        *   All files in `current_source_state` are marked **NEW**.
    *   If INCREMENTAL:
        *   Iterate through `current_source_state`:
            *   If file not in `stored_metadata` -> **NEW**.
            *   If file in `stored_metadata`:
                *   Compare `mtime`, `size`, `hash`.
                *   If different -> **MODIFIED**.
                *   If same -> **UNCHANGED** (Skip).
        *   Iterate through `stored_metadata`:
            *   If file not in `current_source_state` -> **DELETED** (Log it).

4.  **Execute Backup**:
    *   If `new` + `modified` count is 0:
        *   **STOP**. Do not run rsync. Do not create archive. Return "0 files backed up".
    *   Pass strictly the list of `[new + modified]` files to the transfer engine (rsync).
    *   Destination: A new folder (e.g., `backup_2024...`).

5.  **Compression (Optional)**:
    *   If enabled, compress the `backup_2024...` folder to `.tar.gz`.
    *   Delete the uncompressed folder.

6.  **Finalize**:
    *   **IF AND ONLY IF** backup (and compression) succeeded:
        *   Update `stored_metadata` to match `current_source_state`.
        *   Write to `metadata.json`.

## 3. Metadata File Structure (JSON Schema)

```json
{
  "version": "1.0",
  "backup_type": "incremental",
  "timestamp": "2026-02-06T23:00:00Z",
  "source_path": "/home/user/data",
  "files": {
    "documents/report.pdf": {
      "mtime": 1707241200.5,
      "size": 1048576,
      "hash": "sha256:a1b2c3d4..."
    },
    "photos/image.jpg": {
      "mtime": 1707241500.2,
      "size": 2097152,
      "hash": "sha256:e5f6g7h8..."
    }
  },
  "totals": {
    "file_count": 2,
    "total_bytes": 3145728,
    "last_backed_up": "2026-02-06T23:00:00Z"
  }
}
```

## 4. Where and When Metadata is Updated

*   **Location**: `DESTINATION_ROOT/backup_metadata.json` (Persistent, outside individual backup folders).
*   **When**: Immediately AFTER the backup transfer (and optional compression) returns success.
*   **Condition**: strict check `if job.status == success`.
*   **Content**: The `current_source_state` that was captured in Step 2. Do *not* re-scan.

## 5. Python Code Snippet (Implementation)

(See `autobackup/core/incremental_engine.py` for full implementation logic which will be integrated).

## 6. Example Log Output

**Case A: First Full Backup**
```text
[INFO] Starting Backup Job: backup_20260206_100000
[INFO] Metadata not found. Rule 1: First backup MUST be FULL.
[INFO] Scanning source directory... Scanned 1500 files.
[INFO] Change detection: 1500 New, 0 Modified.
[INFO] Files to backup: 1500.
[INFO] Rsync transfer successful.
[INFO] Metadata saved: /backup/dest/backup_metadata.json (1500 files tracked).
[INFO] Backup Completed.
```

**Case B: Incremental with No Changes**
```text
[INFO] Starting Backup Job: backup_20260206_110000
[INFO] Loading metadata... Valid. 1500 files tracked.
[INFO] Scanning source directory... Scanned 1500 files.
[DEBUG] Comparing metadata...
[INFO] Change detection: 0 New, 0 Modified, 0 Deleted.
[INFO] Files to backup: 0.
[INFO] Rule 5: No files changed. Skipping backup generation.
[INFO] Backup Completed (0 files).
```

**Case C: Incremental with Modified Files**
```text
[INFO] Starting Backup Job: backup_20260206_120000
[INFO] Loading metadata... Valid. 1500 files tracked.
[INFO] Scanning source directory... Scanned 1501 files.
[DEBUG] Comparing metadata...
[DEBUG] New file: documents/new_proposal.docx
[DEBUG] Modified file: work/budget.xlsx (mtime changed)
[INFO] Change detection: 1 New, 1 Modified, 0 Deleted.
[INFO] Files to backup: 2.
[INFO] Rsync transfer of 2 files successful.
[INFO] Creating compressed archive... Done.
[INFO] Metadata saved: /backup/dest/backup_metadata.json (1502 files tracked).
[INFO] Backup Completed.
```
