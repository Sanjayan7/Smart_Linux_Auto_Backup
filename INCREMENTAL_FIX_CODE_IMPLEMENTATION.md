# Incremental Backup Fix - Complete Code Implementation

## THE FIX (One Critical Change)

### File: `autobackup/core/backup_manager.py` - Lines 224-232

#### OLD (BROKEN) CODE:
```python
# INCORRECT: Conditional metadata update
if job.config.incremental and self._metadata_tracker:
    files_transferred = rsync_stats.get("files_transferred", 
                                        rsync_stats.get("number_of_files", 0))
    if files_transferred > 0:  # ❌ WRONG CONDITION
        logger.info("Updating incremental backup metadata...")
        self._metadata_tracker.update_metadata(
            exclude_patterns=job.config.exclude_patterns)
    else:
        logger.info("No files transferred in incremental backup, "
                   "skipping metadata update")
```

#### NEW (CORRECT) CODE:
```python
# CORRECT: ALWAYS update metadata for incremental backups
# Even when no files changed, metadata must be updated to confirm
# current source state. Otherwise, metadata becomes stale and next run
# will incorrectly identify all files as "changed".
# 
# Metadata lifecycle:
# - Represents source state at time of backup completion
# - Used by get_changed_files() to detect changes in next run
# - Must be current to prevent false positives
if job.config.incremental and self._metadata_tracker:
    logger.info("Updating incremental backup metadata...")
    self._metadata_tracker.update_metadata(
        exclude_patterns=job.config.exclude_patterns)
```

---

## COMPLETE INCREMENTAL COMPARISON ALGORITHM

### The Flow (from `backup_manager.py` lines 100-232)

```python
def _run_backup_thread(self, job: BackupJob):
    try:
        job.start_time = datetime.datetime.now()
        backup_dir = self._create_backup_dir(job)
        
        # ============================================================
        # STEP 1: CHANGE DETECTION (lines 105-125)
        # ============================================================
        if job.config.incremental and not job.config.encryption:
            link_dest = self._find_last_backup()
            
            if self._metadata_tracker:
                # CRITICAL: Get list of CHANGED files only
                change_report = self._metadata_tracker.get_changed_files(
                    job.config.exclude_patterns)
                
                # Track statistics for UI
                incremental_stats = {
                    "new_files_count": len(change_report["new_files"]),
                    "modified_files_count": len(change_report["modified_files"]),
                    "deleted_files_count": len(change_report["deleted_files"]),
                    "unchanged_files_count": len(change_report["unchanged_files"]),
                }
                
                # Send to UI
                if self._progress_callback:
                    self._progress_callback({
                        "type": "incremental_analysis",
                        **incremental_stats
                    })
        
        # ============================================================
        # STEP 2: DETERMINE FILES TO BACKUP (lines 126-145)
        # ============================================================
        # Only backup files that are new or modified
        files_to_backup = (change_report["new_files"] + 
                          change_report["modified_files"])
        
        if not files_to_backup:
            # ❌ NOTHING CHANGED
            # Skip rsync entirely - this is the optimization
            logger.info("No files changed since last backup. Skipping rsync.")
            rsync_stats = {
                "number_of_files": 0,
                "total_file_size": 0,
                "files_transferred": 0,
                "transfer_speed": "0.0KB/s",
                "elapsed_time": 0.0
            }
        else:
            # ✓ FILES CHANGED
            # Run rsync only on changed files
            logger.info(f"Backing up {len(files_to_backup)} changed files "
                       f"in incremental mode")
            rsync_stats = self._rsync_engine.run_rsync(
                source=job.config.source,
                destination=backup_dir,
                exclude_patterns=job.config.exclude_patterns,
                dry_run=job.config.dry_run,
                progress_callback=self._progress_callback,
                link_dest=link_dest,
                compress=job.config.compression,
                files_from_list=files_to_backup,  # ← CRITICAL
            )
        
        # ============================================================
        # STEP 3: HANDLE COMPRESSION (lines 166-200)
        # ============================================================
        if not job.config.dry_run:
            if job.config.compression:
                logger.info("Creating compressed backup archive...")
                archive_path = self._create_compressed_archive(backup_dir)
                if archive_path and os.path.exists(archive_path):
                    job.files_transferred = 1
                    job.total_size_bytes = os.path.getsize(archive_path)
                    if os.path.exists(backup_dir):
                        shutil.rmtree(backup_dir)
        
        # ============================================================
        # STEP 4: UPDATE METADATA (THE FIX!) (lines 224-232)
        # ============================================================
        # This is the CRITICAL FIX
        if job.config.incremental and self._metadata_tracker:
            logger.info("Updating incremental backup metadata...")
            self._metadata_tracker.update_metadata(
                exclude_patterns=job.config.exclude_patterns)
            
            # What this does:
            # 1. Scans current source directory again
            # 2. Calculates metadata for all files (mtime, size, hash)
            # 3. Overwrites the stored metadata with current state
            # 4. Saves to backup_metadata.json
            # 
            # This ensures that on the NEXT run, get_changed_files() will
            # correctly identify no changes (all files match), and rsync
            # won't be called at all.
        
        # ============================================================
        # STEP 5: ENCRYPTION (if needed) (lines 234-235)
        # ============================================================
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
```

---

## METADATA TRACKER ALGORITHM (How Changed Files Are Detected)

### File: `autobackup/core/metadata_tracker.py`

```python
class MetadataTracker:
    """
    Tracks file metadata for incremental backup comparison.
    """
    
    def __init__(self, metadata_dir: str, source_dir: str):
        self.metadata_dir = Path(metadata_dir)
        self.source_dir = Path(source_dir)
        self.metadata_file = self.metadata_dir / "backup_metadata.json"
        self.metadata: Dict[str, Dict[str, any]] = {}
        
        # Load previously stored metadata
        self.load_metadata()
    
    def get_changed_files(self, exclude_patterns: List[str] = None) -> Dict[str, List[str]]:
        """
        CRITICAL: Compares CURRENT source against STORED metadata to find changes.
        
        This is the heart of incremental detection. It must be called BEFORE
        running rsync to determine which files need backup.
        
        Returns:
            {
                "new_files": [...],        # Files in source, not in metadata
                "modified_files": [...],   # Files with changed mtime, size, or hash
                "deleted_files": [...],    # Files in metadata, but removed from source
                "unchanged_files": [...]   # Files with identical metadata
            }
        """
        # STEP 1: Scan current source directory and get fresh metadata
        current_metadata = self.scan_directory(exclude_patterns)
        
        new_files = []
        modified_files = []
        deleted_files = []
        unchanged_files = []
        
        # STEP 2: Check each file in current source
        for rel_path, current_meta in current_metadata.items():
            if rel_path not in self.metadata:
                # ❌ File exists in source but not in stored metadata
                # → This is a NEW file (first time seeing it)
                new_files.append(rel_path)
            else:
                # File exists in both
                old_meta = self.metadata[rel_path]
                
                # Quick check: size or mtime changed?
                if (current_meta["size"] != old_meta["size"] or
                    current_meta["mtime"] != old_meta["mtime"]):
                    # ❌ File size or timestamp changed
                    # → This is MODIFIED
                    modified_files.append(rel_path)
                elif current_meta["hash"] != old_meta["hash"]:
                    # Rare: size/mtime same but hash different
                    # (e.g., file edited and timestamp restored)
                    # → This is MODIFIED
                    modified_files.append(rel_path)
                else:
                    # ✓ Everything matches!
                    # Size, mtime, hash all identical
                    # → This is UNCHANGED
                    unchanged_files.append(rel_path)
        
        # STEP 3: Check for deleted files
        for rel_path in self.metadata:
            if rel_path not in current_metadata:
                # File was in metadata but no longer in source
                # → This is DELETED
                deleted_files.append(rel_path)
        
        logger.info(
            f"Change detection: {len(new_files)} new, "
            f"{len(modified_files)} modified, {len(deleted_files)} deleted, "
            f"{len(unchanged_files)} unchanged"
        )
        
        return {
            "new_files": new_files,
            "modified_files": modified_files,
            "deleted_files": deleted_files,
            "unchanged_files": unchanged_files,
            "current_metadata": current_metadata
        }
    
    def update_metadata(self, new_metadata: Dict[str, Dict[str, any]] = None,
                       exclude_patterns: List[str] = None):
        """
        THE CRITICAL UPDATE FUNCTION
        
        This must be called AFTER a successful backup, regardless of whether
        files were transferred or not.
        
        Call it with:
        - new_metadata=None: Scans source and gets fresh metadata
        - exclude_patterns: Same patterns used during backup
        
        Result: Stored metadata now matches current source state
        """
        if new_metadata is None:
            # Scan source directory for fresh metadata
            new_metadata = self.scan_directory(exclude_patterns)
        
        # Replace stored metadata with fresh copy
        self.metadata = new_metadata
        
        # Save to JSON file
        self.save_metadata()
        
        logger.info(f"Updated metadata for {len(self.metadata)} files")
    
    def save_metadata(self):
        """Persist metadata to JSON file."""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump({
                    "last_backup": datetime.now().isoformat(),
                    "files": self.metadata
                }, f, indent=2)
            logger.info(f"Saved metadata to {self.metadata_file}")
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
    
    def scan_directory(self, exclude_patterns: List[str] = None) -> Dict[str, Dict[str, any]]:
        """
        Scan source directory and get metadata for ALL files.
        
        This is called:
        1. When initializing to load existing metadata
        2. In get_changed_files() to get CURRENT state
        3. In update_metadata() to get FRESH state for storage
        """
        exclude_patterns = exclude_patterns or []
        current_metadata = {}
        
        for root, dirs, files in os.walk(self.source_dir):
            root_path = Path(root)
            
            # Skip excluded directories
            dirs[:] = [d for d in dirs if not self._should_exclude(
                str((root_path / d).relative_to(self.source_dir)), 
                exclude_patterns
            )]
            
            for filename in files:
                filepath = root_path / filename
                relative_path = str(filepath.relative_to(self.source_dir))
                
                # Skip excluded files
                if self._should_exclude(relative_path, exclude_patterns):
                    continue
                
                metadata = self.get_file_metadata(filepath)
                if metadata:
                    current_metadata[relative_path] = metadata
        
        return current_metadata
    
    def get_file_metadata(self, filepath: Path) -> Dict[str, any]:
        """Get metadata for a single file: mtime, size, hash."""
        try:
            stat = filepath.stat()
            
            # For large files, use quick mode (hash only first 64KB)
            # This is faster and still detects most changes
            quick_mode = stat.st_size > 10 * 1024 * 1024
            
            return {
                "mtime": stat.st_mtime,           # File modification time
                "size": stat.st_size,             # File size in bytes
                "hash": self.calculate_file_hash(str(filepath), 
                                                quick_mode=quick_mode),
                "quick_hash": quick_mode
            }
        except Exception as e:
            logger.warning(f"Failed to get metadata for {filepath}: {e}")
            return {}
    
    def calculate_file_hash(self, filepath: str, quick_mode: bool = False) -> str:
        """Calculate SHA-256 hash of file."""
        try:
            sha256_hash = hashlib.sha256()
            
            with open(filepath, "rb") as f:
                if quick_mode:
                    # First 64KB only
                    chunk = f.read(65536)
                    sha256_hash.update(chunk)
                else:
                    # Full file hash in 4KB chunks
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
            
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.warning(f"Failed to calculate hash for {filepath}: {e}")
            return ""
```

---

## HOW THE FIX WORKS - STEP BY STEP

### Scenario: Three Consecutive Incremental Backup Runs

```
SOURCE DIRECTORY (doesn't change between runs)
├── file1.txt (100 bytes)
├── file2.py (200 bytes)
└── folder/file3.log (300 bytes)
```

#### Run 1: Initial Backup

```
BEFORE:
- metadata.json doesn't exist
- self.metadata = {}

EXECUTION:
1. get_changed_files():
   - scan_directory() returns all 3 files
   - Compare to self.metadata = {} (empty)
   - Result: new_files=[file1, file2, file3], modified=[], unchanged=[]

2. Backup:
   - files_to_backup = [file1, file2, file3]
   - rsync runs, transfers 3 files
   - rsync_stats["files_transferred"] = 3

3. Update Metadata (THE FIX):
   - ALWAYS executes (not conditional)
   - update_metadata() scans source again
   - Stores: {
       "last_backup": "2026-02-06T10:00:00",
       "files": {
         "file1.txt": {mtime: 1000, size: 100, hash: "abc"},
         "file2.py": {mtime: 1001, size: 200, hash: "def"},
         "folder/file3.log": {mtime: 1002, size: 300, hash: "ghi"}
       }
     }

AFTER:
- metadata is CURRENT (matches source exactly)
- All 3 files backed up ✓
```

#### Run 2: No Changes to Source Files

```
BEFORE:
- Source unchanged (same files, same content)
- metadata.json exists from Run 1
- self.metadata = {file1, file2, file3}

EXECUTION:
1. get_changed_files():
   - scan_directory() returns all 3 files
   - Current state:
     {file1: {mtime: 1000, size: 100, hash: "abc"},
      file2: {mtime: 1001, size: 200, hash: "def"},
      file3: {mtime: 1002, size: 300, hash: "ghi"}}
   
   - Compare to self.metadata (from Run 1) - SAME
   - For each file:
     * file1: current matches stored (size ✓, mtime ✓, hash ✓) → unchanged
     * file2: current matches stored (size ✓, mtime ✓, hash ✓) → unchanged
     * file3: current matches stored (size ✓, mtime ✓, hash ✓) → unchanged
   
   - Result: new_files=[], modified=[], unchanged=[all 3]

2. Backup:
   - files_to_backup = [] + [] = []
   - if not files_to_backup: SKIP RSYNC
   - No rsync execution (OPTIMIZATION!)
   - rsync_stats["files_transferred"] = 0

3. Update Metadata (THE FIX):
   - STILL EXECUTES (this is the critical fix!)
   - OLD CODE WOULD SKIP: if files_transferred > 0: ... (FALSE, skip it)
   - NEW CODE ALWAYS RUNS: update_metadata() called
   - Metadata is RE-SCANNED and REWRITTEN
   - Timestamp updates: "last_backup": "2026-02-06T10:05:00"
   - File data: unchanged (because source unchanged)
   - Metadata is STILL CURRENT

AFTER:
- 0 files transferred ✓
- rsync never ran ✓
- metadata still matches source ✓
- Ready for Run 3
```

#### Run 3: Still No Changes (Verifies The Fix)

```
BEFORE:
- Source still unchanged
- metadata from Run 2 exists and is CURRENT
- self.metadata = {file1, file2, file3} (fresh from Run 2)

EXECUTION:
1. get_changed_files():
   - scan_directory() returns all 3 files
   - Current state: {file1: ..., file2: ..., file3: ...} (unchanged)
   - Compare to self.metadata from Run 2: IDENTICAL
   - Result: new_files=[], modified=[], unchanged=[all 3]

2. Backup:
   - files_to_backup = []
   - SKIP RSYNC again

3. Metadata Update:
   - EXECUTES (fixed behavior)
   - Metadata stays current

AFTER:
- 0 files transferred ✓
- rsync never ran ✓
- This repeats indefinitely until source changes ✓
```

---

## WHAT WOULD HAPPEN WITHOUT THE FIX

If the old conditional code remained:
```python
if files_transferred > 0:
    update_metadata()  # Only if files actually transferred
```

After Run 2:
- rsync_stats["files_transferred"] = 0
- Condition is FALSE: don't update metadata
- metadata.json NOT updated
- metadata becomes STALE (represents Run 1 state, not current)

In Run 3:
- metadata.json still has Run 1 timestamp
- get_changed_files() compares current source to stale metadata
- If anything is different (or detection is sensitive), files appear "changed"
- rsync runs unnecessarily
- This repeats forever ❌

---

## VALIDATION CODE

```python
def test_incremental_no_changes():
    """Verify that unchanged files are skipped in future incremental runs."""
    
    # Setup
    source_dir = "/tmp/test_source"
    backup_dir = "/tmp/test_backup"
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(backup_dir, exist_ok=True)
    
    # Create initial files
    with open(f"{source_dir}/file1.txt", "w") as f:
        f.write("content1\n" * 1000)
    with open(f"{source_dir}/file2.txt", "w") as f:
        f.write("content2\n" * 1000)
    
    config = BackupConfig(
        source=source_dir,
        destination=backup_dir,
        incremental=True,
        compression=False,
        exclude_patterns=[],
        retention_policy="none"
    )
    
    manager = BackupManager(config)
    
    # Run 1: Initial backup
    manager.start_backup(dry_run=False)
    # Wait for completion
    while manager._backup_thread.is_alive():
        time.sleep(0.1)
    
    job1 = manager.get_current_job_status()
    print(f"Run 1: {job1.files_transferred} files transferred")
    assert job1.files_transferred == 2, "Run 1 should transfer 2 files"
    
    # Run 2: No changes to source
    time.sleep(1)  # Ensure timestamp difference
    manager.start_backup(dry_run=False)
    while manager._backup_thread.is_alive():
        time.sleep(0.1)
    
    job2 = manager.get_current_job_status()
    print(f"Run 2: {job2.files_transferred} files transferred")
    assert job2.files_transferred == 0, "Run 2 should transfer 0 files (no changes)"
    
    # Run 3: Verify no changes are detected again
    time.sleep(1)
    manager.start_backup(dry_run=False)
    while manager._backup_thread.is_alive():
        time.sleep(0.1)
    
    job3 = manager.get_current_job_status()
    print(f"Run 3: {job3.files_transferred} files transferred")
    assert job3.files_transferred == 0, "Run 3 should transfer 0 files (no changes)"
    
    print("✓ Test passed: Unchanged files correctly skipped in future runs")
```

