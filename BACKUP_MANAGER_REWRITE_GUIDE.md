# Backup Manager Rewrite - Integration Guide

## Overview

The backup_manager.py needs to be refactored to use the new `IncrementalBackupEngine` and strictly follow the 12 professional incremental backup rules.

## Key Changes

### 1. Import the New Engine

```python
from autobackup.core.incremental_engine import IncrementalBackupEngine, should_run_full_backup
```

### 2. Update BackupManager.__init__()

**Current Code (Flawed):**
```python
metadata_dir = os.path.join(config.destination, ".autobackup_metadata")
self._metadata_tracker: Optional[MetadataTracker] = None
if config.source:
    self._metadata_tracker = MetadataTracker(metadata_dir, config.source)
```

**New Code (Professional):**
```python
# Initialize professional incremental backup engine
metadata_path = os.path.join(config.destination, ".autobackup_metadata", "incremental_backup.json")
self._incremental_engine: Optional[IncrementalBackupEngine] = None
if config.source:
    self._incremental_engine = IncrementalBackupEngine(metadata_path, config.source)
```

### 3. Refactor _run_backup_thread()

The _run_backup_thread() method should follow this new structure:

```python
def _run_backup_thread(self, job: BackupJob):
    """
    Refactored to use professional incremental backup engine.
    
    Flow:
    1. Check if incremental backup is requested
    2. If incremental:
       a. Check if metadata exists (Rule 1, 10)
       b. If no metadata or corrupted: run FULL backup
       c. If metadata valid: run INCREMENTAL
    3. If full:
       a. Backup all files
       b. Create metadata
    """
    try:
        job.start_time = datetime.datetime.now()
        backup_dir = self._create_backup_dir(job)
        
        # Rule 1: Determine backup type
        is_first_backup = (job.config.incremental and 
                          should_run_full_backup(self._incremental_engine.metadata_path))
        
        if job.config.incremental:
            if is_first_backup:
                # Rule 1: First backup must be FULL
                logger.info("Rule 1: First backup detected. Running FULL backup.")
                self._run_full_backup(job, backup_dir)
            else:
                # Rule 2, 4, 5: Run INCREMENTAL
                self._run_incremental_backup(job, backup_dir)
        else:
            # Non-incremental: run FULL backup
            self._run_full_backup(job, backup_dir)
        
        job.end_time = datetime.datetime.now()
        job.status = "completed"
        
        if self._completion_callback:
            self._completion_callback(job)
    
    except Exception as e:
        job.status = "failed"
        job.end_time = datetime.datetime.now()
        logger.exception(e)
        self._error(str(e))


def _run_full_backup(self, job: BackupJob, backup_dir: str):
    """
    Rule 1, 10: Run FULL backup.
    
    Used for:
    - First backup (metadata doesn't exist)
    - Missing/corrupted metadata
    - Non-incremental backups
    """
    logger.info("Running FULL backup")
    
    # Backup entire source
    rsync_stats = self._rsync_engine.run_rsync(
        source=job.config.source,
        destination=backup_dir,
        exclude_patterns=job.config.exclude_patterns,
        dry_run=job.config.dry_run,
        progress_callback=self._progress_callback,
        compress=job.config.compression
    )
    
    if rsync_stats.get("failed", False):
        # Rule 8: Failed backup → don't update metadata
        logger.error("Full backup failed. Metadata NOT created.")
        cleanup_backup_directory(backup_dir)
        raise BackupError("Full backup failed")
    
    # Rule 6: Compression after file selection
    if job.config.compression:
        archive_path = self._create_compressed_archive(backup_dir)
    
    # Rule 8: Update metadata ONLY after successful backup
    if job.config.incremental and self._incremental_engine:
        self._incremental_engine.current_metadata = self._incremental_engine.scan_source_directory(
            job.config.exclude_patterns
        )
        self._incremental_engine.save_metadata(backup_type="full")
    
    job.files_transferred = rsync_stats.get("number_of_files", 0)
    job.total_size_bytes = rsync_stats.get("total_file_size", 0)
    
    logger.info(f"Full backup complete: {job.files_transferred} files")


def _run_incremental_backup(self, job: BackupJob, backup_dir: str):
    """
    Rule 2, 4, 5, 6, 11, 12: Run INCREMENTAL backup.
    
    Process:
    1. Load metadata (Rule 2)
    2. Scan source (Rule 3)
    3. Detect changes (Rule 2, 4)
    4. If 0 files: return (Rule 5, 11)
    5. If files: rsync them (Rule 6, 12)
    6. Update metadata (Rule 8)
    """
    logger.info("Running INCREMENTAL backup")
    
    # Load stored metadata (Rule 2)
    if not self._incremental_engine.load_metadata():
        logger.error("Failed to load metadata. Falling back to full backup.")
        self._run_full_backup(job, backup_dir)
        return
    
    # Rule 2, 4: Detect changes (metadata-driven)
    new_files, modified_files, deleted_files = self._incremental_engine.detect_changes(
        job.config.exclude_patterns
    )
    
    # Rule 4, 5: Build files to backup
    files_to_backup = self._incremental_engine.get_files_to_backup(new_files, modified_files)
    
    # Rule 5: No changes → zero files backed up
    if not files_to_backup:
        logger.info("No files changed. Incremental backup: 0 files.")
        logger.info("Rule 5: No archive created. Metadata NOT updated (Rule 8).")
        job.files_transferred = 0
        job.total_size_bytes = 0
        return  # Exit without updating metadata
    
    # Rule 6, 12: Run rsync with ONLY changed files (efficient)
    logger.info(f"Backing up {len(files_to_backup)} changed files")
    
    rsync_stats = self._rsync_engine.run_rsync(
        source=job.config.source,
        destination=backup_dir,
        files_from=files_to_backup,  # CRITICAL: Only these files
        exclude_patterns=job.config.exclude_patterns,
        dry_run=job.config.dry_run,
        progress_callback=self._progress_callback,
        compress=job.config.compression
    )
    
    if rsync_stats.get("failed", False):
        # Rule 8: Failed backup → don't update metadata
        logger.error("Incremental backup failed. Metadata NOT updated.")
        cleanup_backup_directory(backup_dir)
        raise BackupError("Incremental backup failed")
    
    # Rule 6: Compression happens AFTER file selection
    if job.config.compression:
        archive_path = self._create_compressed_archive(backup_dir)
    
    # Rule 8: Update metadata ONLY after successful backup
    # This is the LAST step
    self._incremental_engine.current_metadata = self._incremental_engine.scan_source_directory(
        job.config.exclude_patterns
    )
    self._incremental_engine.save_metadata(backup_type="incremental")
    
    job.files_transferred = rsync_stats.get("number_of_files", 0)
    job.total_size_bytes = rsync_stats.get("total_file_size", 0)
    
    logger.info(f"Incremental backup complete: {job.files_transferred} files")
```

## Migration Path

### Phase 1: Preserve Existing Interface (Backward Compatibility)
- Keep `MetadataTracker` class for now
- Add new `IncrementalBackupEngine` alongside
- Both can coexist during transition

### Phase 2: Update Decision Logic
- Change conditional: `if is_first_backup` instead of `if files_transferred > 0`
- Add explicit full backup vs incremental logic

### Phase 3: Update File Selection
- Use `files_from` parameter in rsync for incremental
- Don't pass list if full backup

### Phase 4: Update Metadata Update Logic
- Only update metadata if:
  - Full backup succeeds, OR
  - Incremental backup with files succeeds
- Never update if:
  - Backup fails (Rule 8)
  - Incremental with zero files (Rule 5)
  - Dry-run (Rule 8)

## Key Differences from Old Code

| Aspect | Old Code | New Code |
|--------|----------|----------|
| **First backup detection** | Try incremental, check files_transferred | Check metadata exists (Rule 1) |
| **Metadata updates** | If files_transferred > 0 | If backup succeeds AND not zero files |
| **Zero file handling** | Might create empty archive | Return immediately (Rule 5) |
| **File list** | Always entire source | Only changed files (Rule 4, 12) |
| **Decision driver** | Files transferred count | Metadata validity (Rule 2) |
| **Deleted files** | Not explicitly logged | Always logged (Rule 9) |
| **Idempotency** | Not guaranteed | Guaranteed (Rule 11) |
| **Compression timing** | After file selection | After file selection (explicit) |

## Testing Strategy

### Test 1: First Backup
```
Config: incremental=True, no metadata exists
Expected: Full backup, metadata created
```

### Test 2: Incremental No Changes
```
Config: incremental=True, metadata exists, source unchanged
Expected: 0 files, no archive, metadata not updated
```

### Test 3: Incremental With Changes
```
Config: incremental=True, metadata exists, 5 files changed
Expected: 5 files backed up, metadata updated
```

### Test 4: Idempotent Run
```
Config: incremental=True, run Test 2 twice
Expected: Both runs show 0 files (idempotent)
```

### Test 5: With Compression
```
Config: incremental=True, compression=True, 5 files changed
Expected: 5 files in archive, metadata updated
```

### Test 6: Compression Zero Files
```
Config: incremental=True, compression=True, no changes
Expected: No archive created, metadata not updated
```

### Test 7: Dry Run
```
Config: incremental=True, dry_run=True
Expected: Show changes but no metadata update, no actual backup
```

### Test 8: Metadata Corruption
```
Config: incremental=True, metadata corrupted
Expected: Fallback to full backup, metadata overwritten
```

## Code Location Notes

- New file: `autobackup/core/incremental_engine.py` ✅ Created
- Modify: `autobackup/core/backup_manager.py` - Will update
- Modify: `autobackup/core/rsync_engine.py` - Might need file_from parameter
- Keep: `autobackup/core/metadata_tracker.py` - For backward compatibility (deprecated)

