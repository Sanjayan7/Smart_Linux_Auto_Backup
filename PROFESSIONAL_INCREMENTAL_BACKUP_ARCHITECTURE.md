# Professional Incremental Backup - Complete Architecture

## PART 1: WHY THE OLD LOGIC WAS INCORRECT

### Current Implementation Violations

The existing implementation violates **RULES 1, 2, 5, 7, 8, 10, and 11**:

#### Violation 1: No Full Backup Guarantee (Rule 1)
```python
# Current code: Tries incremental on FIRST run
if job.config.incremental and not job.config.encryption:
    change_report = self._metadata_tracker.get_changed_files(...)
    # ❌ Problem: No check for first backup
    # ❌ Problem: No metadata baseline established
    # ❌ Problem: Treats first run as incremental
```

**Should Be:**
```python
# First check: Is there existing metadata?
if not metadata_exists():
    # Force FULL backup (Rule 1)
    run_full_backup()
else:
    # Now run incremental
    run_incremental_backup()
```

#### Violation 2: Conditional Metadata Updates (Rule 8)
```python
# Current code: Lines 224-232
if files_transferred > 0:
    update_metadata()  # ❌ Only if files moved
else:
    skip_metadata_update()  # ❌ Metadata becomes stale
```

**Should Be:**
```python
# Always update metadata ONLY on success
if backup_success:
    update_metadata()  # Every time, success = update
else:
    # On failure, don't update
    do_not_update_metadata()
```

#### Violation 3: Archive Files as Reference (Rule 7)
```python
# Current code looks at:
def _find_last_backup(self) -> Optional[str]:
    # Returns filesystem directory or archive
    # ❌ Problem: Compares against destination artifacts
    # ❌ Problem: .tar.gz files influence decisions
    # ❌ Problem: Not metadata-driven
```

**Should Be:**
```python
# Never look at archives for incremental logic
# Only use metadata file
metadata = load_metadata()
if metadata_is_valid():
    run_incremental()
else:
    run_full_backup()
```

#### Violation 4: Empty Backups Created (Rule 5)
```python
# Current code: Still creates archive if no changes
if compression:
    # Creates .tar.gz even for empty backup
    archive_path = self._create_compressed_archive(backup_dir)
```

**Should Be:**
```python
# Only create archive if files were actually backed up
if files_to_backup:
    if compression:
        create_archive()
    # Update metadata ONLY here (success condition)
    update_metadata()
else:
    # No files changed - skip entire process
    log("No files changed. Skipping backup.")
    return 0  # Zero files backed up
```

#### Violation 5: Missing First-Run Detection (Rule 10)
```python
# Current code: No automatic fallback
# If metadata missing:
# - Tries to use empty metadata
# - Treats everything as "new"
# - Behaves like pseudo-full-backup
```

**Should Be:**
```python
# Check metadata validity
if not metadata_exists() or metadata_corrupted():
    # Explicitly run FULL backup
    run_full_backup()
    # Metadata will be created as side effect
else:
    # Metadata is valid, run incremental
    run_incremental()
```

#### Violation 6: Not Idempotent (Rule 11)
```python
# Current code:
# Run 1 (no changes): 0 files transferred
# Run 2 (no changes): May transfer files again ❌
# Reason: Metadata might be stale
```

**Should Be:**
```python
# Run 1 (no changes): 0 files transferred
# Run 2 (no changes): 0 files transferred
# Run 3 (no changes): 0 files transferred
# Guaranteed by always-current metadata
```

---

## PART 2: CORRECT INCREMENTAL BACKUP ALGORITHM

### Decision Tree

```
START: Incremental Backup Request
  │
  ├─ Check: Does metadata file exist?
  │  │
  │  ├─ NO → Run FULL Backup (Rule 1, 10)
  │  │        └─ Create metadata after success
  │  │
  │  └─ YES → Check: Is metadata valid?
  │           │
  │           ├─ NO → Run FULL Backup (Rule 10 fallback)
  │           │        └─ Overwrite corrupted metadata
  │           │
  │           └─ YES → Proceed with INCREMENTAL
  │                   │
  │                   ├─ STEP 1: Load stored metadata
  │                   ├─ STEP 2: Scan current source
  │                   ├─ STEP 3: Detect changes
  │                   │          ├─ New files
  │                   │          ├─ Modified files
  │                   │          ├─ Deleted files
  │                   │          └─ Unchanged files
  │                   │
  │                   ├─ STEP 4: Build files_to_backup list
  │                   │          ├─ new_files + modified_files
  │                   │          └─ Skip unchanged_files
  │                   │
  │                   ├─ STEP 5: Decision point
  │                   │          ├─ If empty list:
  │                   │          │  └─ LOG "No files changed"
  │                   │          │  └─ RETURN 0 files backed up
  │                   │          │  └─ SKIP compression
  │                   │          │  └─ SKIP metadata update
  │                   │          │
  │                   │          └─ If has files:
  │                   │             ├─ STEP 6: Run rsync with file list
  │                   │             ├─ STEP 7: Apply compression (if enabled)
  │                   │             ├─ STEP 8: ONLY NOW update metadata
  │                   │             └─ RETURN files_transferred count
```

### Detailed Algorithm (Pseudocode)

```python
class IncrementalBackupSystem:
    
    def backup(config: BackupConfig):
        """
        Main incremental backup function.
        Enforces all 12 rules.
        """
        
        # ====== RULE 1: Check if first backup ======
        metadata = load_metadata(config.metadata_path)
        
        if metadata is None or metadata_is_corrupted():
            # Rule 10: Missing/corrupted → full backup
            logger.info("No valid metadata found. Running FULL backup (Rule 1).")
            return full_backup(config)
        
        # ====== RULE 2: Metadata-driven decisions ======
        # (Not archive-driven, not destination-driven)
        
        # ====== STEP 1: Load stored metadata ======
        stored_metadata = metadata["files"]  # {rel_path: {mtime, size, hash}}
        
        # ====== STEP 2: Scan current source ======
        current_metadata = scan_source_directory(
            config.source,
            config.exclude_patterns
        )
        # Result: {rel_path: {mtime, size, hash}, ...}
        
        # ====== STEP 3: Detect changes (Rule 2, 4) ======
        new_files = []
        modified_files = []
        deleted_files = []
        
        # Find new and modified files
        for rel_path, current_meta in current_metadata.items():
            if rel_path not in stored_metadata:
                new_files.append(rel_path)
            elif not files_equal(current_meta, stored_metadata[rel_path]):
                modified_files.append(rel_path)
        
        # Find deleted files (Rule 9)
        for rel_path in stored_metadata:
            if rel_path not in current_metadata:
                deleted_files.append(rel_path)
                log_deletion(rel_path)
        
        # ====== STEP 4: Build backup file list (Rule 4) ======
        files_to_backup = new_files + modified_files
        
        # ====== STEP 5: Critical decision (Rule 5) ======
        if not files_to_backup:
            # Rule 5: Incremental with no changes = ZERO files
            # Rule 11: Idempotent - repeating gives same result
            logger.info("No files changed since last backup.")
            logger.info("Incremental backup: 0 files to backup.")
            # Rule 7: Don't create archive
            # Rule 8: Don't update metadata
            return IncementalBackupResult(
                files_backed_up=0,
                bytes_transferred=0,
                status="completed",
                archive_created=False
            )
        
        # ====== STEP 6: Rsync only changed files (Rule 6) ======
        # File selection happens BEFORE compression (Rule 6)
        backup_dir = create_backup_directory(config.destination)
        
        rsync_result = run_rsync(
            source=config.source,
            destination=backup_dir,
            files_from=files_to_backup,  # Only changed files
            exclude_patterns=config.exclude_patterns
        )
        
        if rsync_result.failed:
            # Rule 8: Failed backup → don't update metadata
            logger.error("Rsync failed. Metadata NOT updated.")
            cleanup_backup_dir(backup_dir)
            raise BackupError("Rsync failed")
        
        files_transferred = len(files_to_backup)
        bytes_transferred = rsync_result.total_bytes
        
        # ====== STEP 7: Compression AFTER file selection (Rule 6) ======
        archive_path = None
        if config.compression:
            archive_path = compress_backup(backup_dir)
        
        # ====== STEP 8: Update metadata ONLY on success (Rule 8) ======
        # This is the LAST step
        update_metadata(
            metadata_path=config.metadata_path,
            current_metadata=current_metadata,
            timestamp=now()
        )
        
        logger.info(f"Incremental backup complete. "
                   f"Files backed up: {files_transferred}")
        
        return IncrementalBackupResult(
            files_backed_up=files_transferred,
            bytes_transferred=bytes_transferred,
            status="completed",
            archive_created=archive_path is not None,
            archive_path=archive_path,
            new_files_count=len(new_files),
            modified_files_count=len(modified_files),
            deleted_files_count=len(deleted_files)
        )
    
    def full_backup(config: BackupConfig):
        """
        Full backup - used for:
        - First backup (Rule 1)
        - Missing/corrupted metadata (Rule 10)
        """
        logger.info("Running FULL backup.")
        
        backup_dir = create_backup_directory(config.destination)
        
        # Backup entire source
        rsync_result = run_rsync(
            source=config.source,
            destination=backup_dir,
            exclude_patterns=config.exclude_patterns
        )
        
        if rsync_result.failed:
            logger.error("Full backup failed. Metadata NOT created.")
            cleanup_backup_dir(backup_dir)
            raise BackupError("Full backup failed")
        
        # Compression (if enabled)
        archive_path = None
        if config.compression:
            archive_path = compress_backup(backup_dir)
        
        # Create NEW metadata
        current_metadata = scan_source_directory(
            config.source,
            config.exclude_patterns
        )
        
        # Rule 8: Only update after successful backup
        create_metadata(
            metadata_path=config.metadata_path,
            file_metadata=current_metadata,
            timestamp=now()
        )
        
        files_backed_up = len(current_metadata)
        logger.info(f"Full backup complete. Files backed up: {files_backed_up}")
        
        return FullBackupResult(
            files_backed_up=files_backed_up,
            bytes_transferred=rsync_result.total_bytes,
            status="completed",
            archive_created=archive_path is not None,
            archive_path=archive_path
        )
```

---

## PART 3: METADATA FILE STRUCTURE (JSON Schema)

### File Location
```
<destination>/.autobackup_metadata/incremental_backup.json
```

### Complete Schema

```json
{
  "version": "1.0",
  "backup_type": "full",
  "timestamp": "2026-02-06T14:30:45.123456Z",
  "source_path": "/home/user/my_data",
  "files": {
    "document.txt": {
      "mtime": 1707208245.123456,
      "size": 2048,
      "hash": "sha256:abc123def456..."
    },
    "folder/image.jpg": {
      "mtime": 1707208246.654321,
      "size": 1048576,
      "hash": "sha256:ghi789jkl012..."
    },
    "config/settings.yaml": {
      "mtime": 1707208247.987654,
      "size": 512,
      "hash": "sha256:mno345pqr678..."
    }
  },
  "totals": {
    "file_count": 3,
    "total_bytes": 1051136,
    "last_backed_up": "2026-02-06T14:30:45.123456Z"
  }
}
```

### Field Descriptions

| Field | Type | Purpose | Rule |
|-------|------|---------|------|
| `version` | string | Schema version for compatibility | - |
| `backup_type` | string | "full" or "incremental" | Rule 1 |
| `timestamp` | ISO8601 | When metadata was created | Rule 8 |
| `source_path` | string | Original source directory | Rule 3 |
| `files` | dict | Map of files → their metadata | Rule 3 |
| `mtime` | float | File modification time | Rule 3 |
| `size` | integer | File size in bytes | Rule 3 |
| `hash` | string | SHA-256 checksum | Rule 3 |
| `totals.file_count` | integer | How many files were backed up | - |
| `totals.total_bytes` | integer | Total bytes backed up | - |
| `totals.last_backed_up` | ISO8601 | Last successful backup time | Rule 8 |

### Metadata Validation

```python
def is_metadata_valid(metadata_dict) -> bool:
    """
    Check if metadata is valid for incremental comparison.
    
    Rules 3, 10: Metadata must have required fields.
    """
    required_fields = ["version", "files", "timestamp", "source_path"]
    
    # Rule 10: Missing required fields = corrupted
    if not all(field in metadata_dict for field in required_fields):
        return False
    
    # Rule 3: Files must have mtime, size, and/or hash
    for rel_path, file_meta in metadata_dict["files"].items():
        required = ["mtime", "size"]
        if not all(key in file_meta for key in required):
            return False
        # Hash is optional but preferred (Rule 3)
    
    return True
```

---

## PART 4: PYTHON IMPLEMENTATION

### Core Incremental Comparison Function

```python
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

class FileMetadata:
    """Represents metadata for a single file."""
    
    def __init__(self, mtime: float, size: int, hash_value: str = ""):
        self.mtime = mtime
        self.size = size
        self.hash = hash_value
    
    def to_dict(self) -> Dict:
        return {
            "mtime": self.mtime,
            "size": self.size,
            "hash": self.hash
        }
    
    @classmethod
    def from_dict(cls, d: Dict):
        return cls(d["mtime"], d["size"], d.get("hash", ""))


class IncrementalBackupEngine:
    """
    Professional incremental backup implementation.
    Follows all 12 rules.
    """
    
    def __init__(self, metadata_path: str, source_dir: str):
        """
        Initialize incremental backup engine.
        
        Args:
            metadata_path: Path to metadata JSON file
            source_dir: Source directory being backed up
        """
        self.metadata_path = Path(metadata_path)
        self.source_dir = Path(source_dir)
        self.stored_metadata: Dict[str, FileMetadata] = {}
        self.current_metadata: Dict[str, FileMetadata] = {}
        
        # Ensure metadata directory exists
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
    
    def load_metadata(self) -> bool:
        """
        Load metadata from file.
        
        Rule 10: Invalid metadata returns False (triggers full backup)
        
        Returns:
            True if metadata loaded successfully, False if missing/invalid
        """
        if not self.metadata_path.exists():
            return False
        
        try:
            with open(self.metadata_path, 'r') as f:
                data = json.load(f)
            
            # Validate metadata (Rule 10)
            if not self._is_metadata_valid(data):
                return False
            
            # Load file metadata
            self.stored_metadata = {
                rel_path: FileMetadata.from_dict(meta)
                for rel_path, meta in data.get("files", {}).items()
            }
            
            return True
        except (json.JSONDecodeError, IOError, KeyError):
            return False
    
    def _is_metadata_valid(self, data: Dict) -> bool:
        """
        Validate metadata structure.
        
        Rule 10: Return False if invalid (triggers full backup).
        """
        required_keys = ["version", "files", "timestamp", "source_path"]
        
        if not all(k in data for k in required_keys):
            return False
        
        # Check files have required fields (Rule 3)
        for rel_path, meta in data.get("files", {}).items():
            if not ("mtime" in meta and "size" in meta):
                return False
        
        return True
    
    def scan_source_directory(self, exclude_patterns: List[str] = None) -> Dict[str, FileMetadata]:
        """
        Scan source directory and collect file metadata.
        
        Rule 3: Collect mtime, size, hash for each file.
        Rule 2: This is used for metadata-driven decisions.
        
        Args:
            exclude_patterns: List of glob patterns to exclude
        
        Returns:
            Dict mapping relative path → FileMetadata
        """
        exclude_patterns = exclude_patterns or []
        metadata = {}
        
        if not self.source_dir.exists():
            raise ValueError(f"Source directory not found: {self.source_dir}")
        
        for root, dirs, files in self.source_dir.walk():
            # Skip excluded directories
            dirs[:] = [
                d for d in dirs
                if not self._matches_exclude(str(Path(root) / d), exclude_patterns)
            ]
            
            for filename in files:
                filepath = Path(root) / filename
                rel_path = str(filepath.relative_to(self.source_dir))
                
                # Skip excluded files
                if self._matches_exclude(rel_path, exclude_patterns):
                    continue
                
                try:
                    stat = filepath.stat()
                    
                    # Rule 3: Collect mtime, size, hash
                    file_hash = self._calculate_hash(filepath)
                    
                    metadata[rel_path] = FileMetadata(
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                        hash_value=file_hash
                    )
                except (OSError, IOError) as e:
                    # Skip files we can't read
                    continue
        
        return metadata
    
    def _matches_exclude(self, path: str, patterns: List[str]) -> bool:
        """Check if path matches any exclude pattern."""
        from fnmatch import fnmatch
        
        for pattern in patterns:
            if fnmatch(path, pattern) or fnmatch(Path(path).name, pattern):
                return True
        return False
    
    def _calculate_hash(self, filepath: Path, quick_mode: bool = False) -> str:
        """
        Calculate SHA-256 hash of file.
        
        Args:
            filepath: Path to file
            quick_mode: If True, only hash first 64KB (for large files)
        
        Returns:
            Hex hash string
        """
        sha256 = hashlib.sha256()
        
        try:
            with open(filepath, 'rb') as f:
                if quick_mode:
                    # Only hash first 64KB
                    chunk = f.read(65536)
                    sha256.update(chunk)
                else:
                    # Hash full file in chunks
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        sha256.update(chunk)
            
            return f"sha256:{sha256.hexdigest()}"
        except Exception:
            return ""
    
    def detect_changes(self, exclude_patterns: List[str] = None) -> Tuple[List[str], List[str], List[str]]:
        """
        Detect new, modified, and deleted files.
        
        Rule 2: Metadata-driven (not destination-driven).
        Rule 4: Identifies new and modified files.
        Rule 9: Identifies deleted files.
        
        Args:
            exclude_patterns: List of glob patterns to exclude
        
        Returns:
            (new_files, modified_files, deleted_files)
        """
        self.current_metadata = self.scan_source_directory(exclude_patterns)
        
        new_files = []
        modified_files = []
        deleted_files = []
        
        # Rule 4: Find new and modified files
        for rel_path, current_meta in self.current_metadata.items():
            if rel_path not in self.stored_metadata:
                # Rule 4: New file
                new_files.append(rel_path)
            else:
                # Rule 4: Check if modified
                stored_meta = self.stored_metadata[rel_path]
                
                if self._file_changed(current_meta, stored_meta):
                    modified_files.append(rel_path)
        
        # Rule 9: Find deleted files
        for rel_path in self.stored_metadata:
            if rel_path not in self.current_metadata:
                deleted_files.append(rel_path)
        
        return new_files, modified_files, deleted_files
    
    def _file_changed(self, current: FileMetadata, stored: FileMetadata) -> bool:
        """
        Determine if file changed.
        
        Comparison strategy:
        1. Size changed → definitely changed
        2. mtime changed → likely changed
        3. Hash different → definitely changed (final check)
        """
        if current.size != stored.size:
            return True
        
        if current.mtime != stored.mtime:
            return True
        
        # Final check: hash (if available)
        if current.hash and stored.hash:
            if current.hash != stored.hash:
                return True
        
        return False
    
    def save_metadata(self, backup_type: str = "incremental") -> None:
        """
        Save metadata to file.
        
        Rule 8: Only call this after successful backup!
        
        Args:
            backup_type: "full" or "incremental"
        """
        metadata_dict = {
            "version": "1.0",
            "backup_type": backup_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source_path": str(self.source_dir),
            "files": {
                rel_path: meta.to_dict()
                for rel_path, meta in self.current_metadata.items()
            },
            "totals": {
                "file_count": len(self.current_metadata),
                "total_bytes": sum(m.size for m in self.current_metadata.values()),
                "last_backed_up": datetime.utcnow().isoformat() + "Z"
            }
        }
        
        try:
            with open(self.metadata_path, 'w') as f:
                json.dump(metadata_dict, f, indent=2)
        except IOError as e:
            raise BackupError(f"Failed to save metadata: {e}")


# Example usage:
def example_incremental_backup():
    """Demonstrate proper incremental backup flow."""
    
    engine = IncrementalBackupEngine(
        metadata_path="/backup/.autobackup_metadata/incremental_backup.json",
        source_dir="/home/user/data"
    )
    
    # Rule 1: Check if first backup
    if not engine.load_metadata():
        # Rule 10: No metadata = full backup
        print("First backup detected. Running FULL backup.")
        engine.current_metadata = engine.scan_source_directory()
        # ... perform backup ...
        engine.save_metadata(backup_type="full")
        return
    
    # Rule 2: Metadata-driven incremental
    new_files, modified_files, deleted_files = engine.detect_changes()
    
    files_to_backup = new_files + modified_files
    
    # Rule 5: Zero files = no backup
    if not files_to_backup:
        print("No files changed. Incremental backup: 0 files.")
        return
    
    print(f"Incremental backup: {len(files_to_backup)} files to backup")
    print(f"  New files: {len(new_files)}")
    print(f"  Modified files: {len(modified_files)}")
    print(f"  Deleted files: {len(deleted_files)}")
    
    # Rule 6: File selection happens BEFORE compression
    # ... perform rsync with files_to_backup list ...
    
    # Rule 8: Update metadata ONLY after successful backup
    engine.save_metadata(backup_type="incremental")
    print("Metadata updated.")
```

---

## PART 5: METADATA UPDATE LIFECYCLE

### When Metadata IS Updated (Rule 8)

```
✅ After successful FULL backup
   └─ Creates new metadata file

✅ After successful INCREMENTAL backup with file changes
   └─ Updates metadata with current source state

✅ After successful compression (backup succeeded, then compressed)
   └─ Metadata already updated, not changed
```

### When Metadata IS NOT Updated

```
❌ After failed backup (any reason)
   └─ Metadata untouched (next run retries)

❌ After dry-run backup
   └─ Metadata untouched (no actual backup occurred)

❌ After incremental backup with ZERO files changed
   └─ Metadata untouched (nothing to update)
   └─ Same metadata ensures next run also finds 0 changes

❌ During encrypted backup
   └─ (Optional: Don't update if encrypted, or update pre-encryption)
```

### Exact Sequence

```
1. Backup initiated
   └─ Check metadata

2. If incremental with no changes:
   └─ STOP here
   └─ Return: 0 files backed up
   └─ Metadata: UNCHANGED

3. If files to backup:
   └─ Run rsync (or perform actual file copy)
   └─ If failed:
      └─ Stop here
      └─ Raise error
      └─ Metadata: UNCHANGED (Rule 8)
   └─ If succeeded:
      └─ Apply compression (if enabled)
      └─ Scan source directory (fresh scan)
      └─ Save metadata (Rule 8 - after success)
      └─ Return: N files backed up
      └─ Metadata: UPDATED
```

---

## PART 6: EXAMPLE LOG OUTPUT

### Example 1: First Full Backup

```
[2026-02-06 14:30:00] INFO: Backup started
[2026-02-06 14:30:00] INFO: Incremental backup requested
[2026-02-06 14:30:00] INFO: Checking for metadata...
[2026-02-06 14:30:00] INFO: No metadata found at /backup/.autobackup_metadata/incremental_backup.json
[2026-02-06 14:30:00] INFO: Rule 1: First backup must be FULL backup
[2026-02-06 14:30:00] INFO: Running FULL backup (Rule 1, 10)

[2026-02-06 14:30:01] INFO: Scanning source directory: /home/user/data
[2026-02-06 14:30:02] INFO: Scanned 1,243 files

[2026-02-06 14:30:02] INFO: Starting rsync transfer (full)
[2026-02-06 14:30:15] INFO: Rsync completed successfully
[2026-02-06 14:30:15] INFO: Files transferred: 1,243
[2026-02-06 14:30:15] INFO: Total bytes transferred: 5,821,412 bytes

[2026-02-06 14:30:15] INFO: Compression enabled - creating tar.gz
[2026-02-06 14:30:25] INFO: Archive created: /backup/2026-02-06_14-30-25.tar.gz
[2026-02-06 14:30:25] INFO: Archive size: 2,410,531 bytes

[2026-02-06 14:30:25] INFO: Creating metadata file (Rule 8)
[2026-02-06 14:30:25] INFO: Saving 1,243 file entries to metadata
[2026-02-06 14:30:26] INFO: Metadata saved: /backup/.autobackup_metadata/incremental_backup.json

[2026-02-06 14:30:26] INFO: ✓ Full backup complete
[2026-02-06 14:30:26] INFO: Summary:
[2026-02-06 14:30:26] INFO:   Backup type: FULL
[2026-02-06 14:30:26] INFO:   Files backed up: 1,243
[2026-02-06 14:30:26] INFO:   Total size: 5.8 MB
[2026-02-06 14:30:26] INFO:   Archive: 2.4 MB
[2026-02-06 14:30:26] INFO:   Duration: 26 seconds
```

### Example 2: Incremental Backup (No Changes)

```
[2026-02-06 15:30:00] INFO: Backup started
[2026-02-06 15:30:00] INFO: Incremental backup requested
[2026-02-06 15:30:00] INFO: Checking for metadata...
[2026-02-06 15:30:00] INFO: Metadata found: /backup/.autobackup_metadata/incremental_backup.json
[2026-02-06 15:30:00] INFO: Validating metadata...
[2026-02-06 15:30:00] INFO: Metadata valid (1,243 files tracked)

[2026-02-06 15:30:00] INFO: Running INCREMENTAL backup (Rule 2)
[2026-02-06 15:30:01] INFO: Scanning source directory: /home/user/data
[2026-02-06 15:30:02] INFO: Scanned 1,243 files (same as before)

[2026-02-06 15:30:02] INFO: Detecting changes (Rule 4)...
[2026-02-06 15:30:03] INFO: Change detection complete:
[2026-02-06 15:30:03] INFO:   New files: 0
[2026-02-06 15:30:03] INFO:   Modified files: 0
[2026-02-06 15:30:03] INFO:   Deleted files: 0
[2026-02-06 15:30:03] INFO:   Unchanged files: 1,243

[2026-02-06 15:30:03] INFO: Files to backup: 0 + 0 = 0
[2026-02-06 15:30:03] INFO: Rule 5: No files changed since last backup
[2026-02-06 15:30:03] INFO: Skipping rsync (no files to transfer)
[2026-02-06 15:30:03] INFO: Skipping compression (no files backed up)
[2026-02-06 15:30:03] INFO: Skipping metadata update (Rule 8 - nothing changed)

[2026-02-06 15:30:03] INFO: ✓ Incremental backup complete
[2026-02-06 15:30:03] INFO: Summary:
[2026-02-06 15:30:03] INFO:   Backup type: INCREMENTAL
[2026-02-06 15:30:03] INFO:   Files backed up: 0
[2026-02-06 15:30:03] INFO:   Archive created: NO
[2026-02-06 15:30:03] INFO:   Status: IDEMPOTENT (Rule 11)
[2026-02-06 15:30:03] INFO:   Duration: 3 seconds
```

### Example 3: Incremental Backup (Modified Files)

```
[2026-02-06 16:30:00] INFO: Backup started
[2026-02-06 16:30:00] INFO: Incremental backup requested
[2026-02-06 16:30:00] INFO: Checking for metadata...
[2026-02-06 16:30:00] INFO: Metadata found: /backup/.autobackup_metadata/incremental_backup.json
[2026-02-06 16:30:00] INFO: Validating metadata...
[2026-02-06 16:30:00] INFO: Metadata valid (1,243 files tracked)

[2026-02-06 16:30:00] INFO: Running INCREMENTAL backup (Rule 2)
[2026-02-06 16:30:01] INFO: Scanning source directory: /home/user/data
[2026-02-06 16:30:02] INFO: Scanned 1,247 files (4 more than before)

[2026-02-06 16:30:02] INFO: Detecting changes (Rule 4)...
[2026-02-06 16:30:03] INFO: Change detection complete:
[2026-02-06 16:30:03] INFO:   New files: 4
[2026-02-06 16:30:03] INFO:     - new_document.txt
[2026-02-06 16:30:03] INFO:     - photos/vacation.jpg
[2026-02-06 16:30:03] INFO:     - photos/family.jpg
[2026-02-06 16:30:03] INFO:     - archive/old.zip
[2026-02-06 16:30:03] INFO:   Modified files: 2
[2026-02-06 16:30:03] INFO:     - README.md (size changed: 1024→2048)
[2026-02-06 16:30:03] INFO:     - config.json (mtime: 1707208000→1707211600)
[2026-02-06 16:30:03] INFO:   Deleted files: 0
[2026-02-06 16:30:03] INFO:   Unchanged files: 1,241

[2026-02-06 16:30:03] INFO: Files to backup: 4 + 2 = 6 (Rule 4)
[2026-02-06 16:30:03] INFO: Skipping 1,241 unchanged files (Rule 5)

[2026-02-06 16:30:03] INFO: Starting rsync transfer (incremental, 6 files)
[2026-02-06 16:30:08] INFO: Rsync completed successfully
[2026-02-06 16:30:08] INFO: Files transferred: 6
[2026-02-06 16:30:08] INFO: Total bytes transferred: 12,582,912 bytes

[2026-02-06 16:30:08] INFO: Compression enabled - creating tar.gz
[2026-02-06 16:30:10] INFO: Archive created: /backup/2026-02-06_16-30-10.tar.gz
[2026-02-06 16:30:10] INFO: Archive size: 5,242,880 bytes

[2026-02-06 16:30:10] INFO: Updating metadata file (Rule 8)
[2026-02-06 16:30:10] INFO: Metadata: Removing 0 deleted files
[2026-02-06 16:30:10] INFO: Metadata: Adding/updating 6 changed files
[2026-02-06 16:30:10] INFO: Saving 1,247 file entries to metadata
[2026-02-06 16:30:11] INFO: Metadata saved: /backup/.autobackup_metadata/incremental_backup.json

[2026-02-06 16:30:11] INFO: ✓ Incremental backup complete (Rule 12: Efficient)
[2026-02-06 16:30:11] INFO: Summary:
[2026-02-06 16:30:11] INFO:   Backup type: INCREMENTAL
[2026-02-06 16:30:11] INFO:   Files backed up: 6 (not 1,247)
[2026-02-06 16:30:11] INFO:   New: 4, Modified: 2, Deleted: 0
[2026-02-06 16:30:11] INFO:   Total size (only changed): 12.5 MB
[2026-02-06 16:30:11] INFO:   Archive: 5.2 MB (only changed files)
[2026-02-06 16:30:11] INFO:   Duration: 11 seconds
[2026-02-06 16:30:11] INFO:   Efficiency: Backed up 0.5% of total (6 of 1247 files)
```

---

## SUMMARY: 12 RULES COMPLIANCE

| Rule | Implementation | Evidence |
|------|---|---|
| **1: Full backup first** | Check metadata, no metadata → full backup | "Rule 1: First backup must be FULL backup" |
| **2: Metadata-driven** | Only compare metadata, never archives | `detect_changes()` only uses stored_metadata |
| **3: Metadata structure** | mtime, size, hash | `FileMetadata` class stores all three |
| **4: New + modified** | files_to_backup = new + modified | `files_to_backup = new_files + modified_files` |
| **5: Skip unchanged** | Empty list → 0 files backed up | "Files to backup: 0... Skipping rsync" |
| **6: Compression separate** | File selection before compression | Rsync first, then `compress_backup()` |
| **7: Archives output only** | Never compare against .tar.gz | No code reads archive files |
| **8: Update on success** | Only `save_metadata()` after rsync success | "Metadata saved" only after "Rsync completed" |
| **9: Detect deletions** | Log deleted files | "Deleted files: 0" in log |
| **10: Fallback to full** | Invalid metadata → full backup | `if not load_metadata(): full_backup()` |
| **11: Idempotent** | Run 2 with 0 changes = 0 files | Example 2 shows exactly this |
| **12: Efficient** | Only backup changed files | "Efficiency: 0.5% of total" |

