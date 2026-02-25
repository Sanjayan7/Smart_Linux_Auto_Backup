"""
Professional Incremental Backup Engine.

Implements all 12 rules for production-grade incremental backup.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from autobackup.utils.logger import logger


class FileMetadata:
    """Represents metadata for a single file."""
    
    def __init__(self, mtime: float, size: int, hash_value: str = ""):
        self.mtime = mtime
        self.size = size
        self.hash = hash_value
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "mtime": self.mtime,
            "size": self.size,
            "hash": self.hash
        }
    
    @classmethod
    def from_dict(cls, d: Dict):
        """Create from dictionary."""
        return cls(d["mtime"], d["size"], d.get("hash", ""))


class IncrementalBackupEngine:
    """
    Professional incremental backup implementation.
    
    Enforces all 12 professional incremental backup rules:
    1. First backup MUST be full backup (no metadata = full)
    2. Metadata-driven (not destination/archive-driven)
    3. Metadata: path, size, mtime, checksum
    4. Backup only: new + modified files
    5. No changes = 0 files backed up
    6. Compression separate from file selection
    7. Archives never used for incremental comparison
    8. Metadata updated ONLY on successful backup
    9. Deleted files detected and logged
    10. Missing/corrupted metadata triggers full backup
    11. Incremental backups are idempotent
    12. Efficient: only changed files backed up
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
        
        logger.debug(f"IncrementalBackupEngine initialized")
        logger.debug(f"  Metadata path: {self.metadata_path}")
        logger.debug(f"  Source dir: {self.source_dir}")
    
    def metadata_exists(self) -> bool:
        """
        Rule 1, 10: Check if metadata file exists.
        
        Returns:
            True if metadata file exists, False otherwise
        """
        return self.metadata_path.exists()
    
    def load_metadata(self) -> bool:
        """
        Rule 10: Load and validate metadata.
        
        Returns:
            True if metadata loaded successfully
            False if missing or invalid (triggers full backup)
        """
        if not self.metadata_path.exists():
            logger.info(f"Metadata file not found: {self.metadata_path}")
            return False
        
        try:
            with open(self.metadata_path, 'r') as f:
                data = json.load(f)
            
            # Rule 10: Validate metadata structure
            if not self._is_metadata_valid(data):
                logger.warning("Metadata validation failed - treating as corrupted")
                return False
            
            # Load file metadata
            self.stored_metadata = {
                rel_path: FileMetadata.from_dict(meta)
                for rel_path, meta in data.get("files", {}).items()
            }
            
            logger.info(f"Metadata loaded successfully: {len(self.stored_metadata)} files tracked")
            return True
        
        except (json.JSONDecodeError, IOError, KeyError, ValueError) as e:
            logger.warning(f"Failed to load metadata: {e}")
            return False
    
    def _is_metadata_valid(self, data: Dict) -> bool:
        """
        Rule 10: Validate metadata structure.
        
        Returns:
            False if invalid (triggers full backup fallback)
        """
        # Check required top-level keys
        required_keys = ["version", "files", "timestamp", "source_path"]
        if not all(k in data for k in required_keys):
            logger.debug(f"Missing required metadata keys")
            return False
        
        # Check file entries have required fields (Rule 3)
        for rel_path, meta in data.get("files", {}).items():
            if not isinstance(meta, dict):
                logger.debug(f"Invalid metadata format for file: {rel_path}")
                return False
            
            if not ("mtime" in meta and "size" in meta):
                logger.debug(f"Missing required fields (mtime, size) for: {rel_path}")
                return False
        
        return True
    
    def scan_source_directory(self, exclude_patterns: List[str] = None, stored_metadata: Dict[str, 'FileMetadata'] = None) -> Dict[str, 'FileMetadata']:
        """
        Rule 2, 3: Scan source directory and collect file metadata.
        
        Collects: file path, mtime, size, hash
        This is used for metadata-driven change detection.
        
        OPTIMIZATION: Rule 12 (Efficiency)
        If mtime and size match stored metadata, we skip re-hashing
        and preserve the old hash. This ensures the backup remains fast.
        
        Args:
            exclude_patterns: List of glob patterns to exclude
            stored_metadata: Previous metadata to check against for hash caching
        
        Returns:
            Dict mapping relative path → FileMetadata
        """
        exclude_patterns = exclude_patterns or []
        stored_metadata = stored_metadata or {}
        metadata = {}
        
        if not self.source_dir.exists():
            raise ValueError(f"Source directory not found: {self.source_dir}")
        
        logger.info(f"Scanning source directory: {self.source_dir}")
        
        scanned_count = 0
        skipped_hash_count = 0
        
        for root, dirs, files in os.walk(self.source_dir):
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
                    current_mtime = stat.st_mtime
                    current_size = stat.st_size
                    file_hash = ""
                    
                    # Rule 12: Optimization - Reuse hash if mtime/size match
                    # This avoids reading full file content for unchanged files
                    if rel_path in stored_metadata:
                        stored = stored_metadata[rel_path]
                        # Allow small float tolerance for mtime (e.g. filesystem precision)
                        if abs(stored.mtime - current_mtime) < 0.001 and stored.size == current_size:
                            file_hash = stored.hash
                            skipped_hash_count += 1
                    
                    # If we didn't get a hash from cache (new or changed file), calculate it
                    if not file_hash:
                        # Only calculate hash for new/modified files
                        # This works because if mtime/size changed, we need new hash anyway.
                        # If they didn't change, we used stored hash.
                        file_hash = self._calculate_hash(filepath)
                    
                    metadata[rel_path] = FileMetadata(
                        mtime=current_mtime,
                        size=current_size,
                        hash_value=file_hash
                    )
                    
                    scanned_count += 1
                
                except (OSError, IOError) as e:
                    logger.warning(f"Failed to scan {filepath}: {e}")
                    continue
        
        logger.info(f"Scanned {scanned_count} files (Used cached hash for {skipped_hash_count})")
        return metadata
    
    def _matches_exclude(self, path: str, patterns: List[str]) -> bool:
        """Check if path matches any exclude pattern."""
        from fnmatch import fnmatch
        
        for pattern in patterns:
            if fnmatch(path, pattern) or fnmatch(Path(path).name, pattern):
                return True
        return False
    
    def _calculate_hash(self, filepath: Path) -> str:
        """
        Calculate SHA-256 hash of file.
        
        Rule 3: Hash is part of metadata for change detection.
        
        Args:
            filepath: Path to file
        
        Returns:
            "sha256:hexdigest" string
        """
        try:
            sha256 = hashlib.sha256()
            
            with open(filepath, 'rb') as f:
                # Read in 8KB chunks
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    sha256.update(chunk)
            
            return f"sha256:{sha256.hexdigest()}"
        
        except Exception as e:
            logger.warning(f"Failed to calculate hash for {filepath}: {e}")
            return ""
    
    def detect_changes(self, exclude_patterns: List[str] = None) -> Tuple[List[str], List[str], List[str]]:
        """
        Rule 2, 4, 9: Detect new, modified, and deleted files.
        
        This is metadata-driven (not destination-driven).
        
        Args:
            exclude_patterns: List of glob patterns to exclude
        
        Returns:
            (new_files, modified_files, deleted_files)
        """
        # Scan current source state (Rule 3)
        self.current_metadata = self.scan_source_directory(exclude_patterns, self.stored_metadata)
        
        new_files = []
        modified_files = []
        deleted_files = []
        
        # Rule 4: Find new and modified files
        for rel_path, current_meta in self.current_metadata.items():
            if rel_path not in self.stored_metadata:
                # New file
                new_files.append(rel_path)
                logger.debug(f"New file: {rel_path}")
            else:
                # Check if modified (Rule 4)
                stored_meta = self.stored_metadata[rel_path]
                
                if self._file_changed(current_meta, stored_meta):
                    modified_files.append(rel_path)
                    logger.debug(f"Modified file: {rel_path}")
        
        # Rule 9: Find deleted files (log them)
        for rel_path in self.stored_metadata:
            if rel_path not in self.current_metadata:
                deleted_files.append(rel_path)
                logger.info(f"Deleted file detected: {rel_path}")
        
        logger.info(f"Change detection complete:")
        logger.info(f"  New files: {len(new_files)}")
        logger.info(f"  Modified files: {len(modified_files)}")
        logger.info(f"  Deleted files: {len(deleted_files)}")
        logger.info(f"  Unchanged files: {len(self.current_metadata) - len(new_files) - len(modified_files)}")
        
        return new_files, modified_files, deleted_files
    
    def _file_changed(self, current: FileMetadata, stored: FileMetadata) -> bool:
        """
        Determine if file changed.
        
        Comparison strategy:
        1. Size changed → definitely changed
        2. mtime changed → likely changed
        3. Hash different → definitely changed
        """
        if current.size != stored.size:
            logger.debug(f"  Size changed: {stored.size} → {current.size}")
            return True
        
        if current.mtime != stored.mtime:
            logger.debug(f"  mtime changed: {stored.mtime} → {current.mtime}")
            return True
        
        # Final check: hash (if available)
        if current.hash and stored.hash:
            if current.hash != stored.hash:
                logger.debug(f"  Hash changed")
                return True
        
        return False
    
    def save_metadata(self, backup_type: str = "incremental") -> None:
        """
        Rule 8: Save metadata to file.
        
        CRITICAL: Only call this after successful backup!
        Failed backups must NOT update metadata.
        
        Args:
            backup_type: "full" or "incremental"
        
        Raises:
            ValueError: If called with invalid backup_type
        """
        if backup_type not in ("full", "incremental"):
            raise ValueError(f"Invalid backup_type: {backup_type}")
        
        # Build metadata structure (Rule 3)
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
            
            logger.info(f"Metadata saved: {self.metadata_path}")
            logger.info(f"  Files tracked: {len(self.current_metadata)}")
            logger.info(f"  Total size: {sum(m.size for m in self.current_metadata.values()):,} bytes")
        
        except IOError as e:
            logger.error(f"Failed to save metadata: {e}")
            raise ValueError(f"Failed to save metadata: {e}")
    
    def get_files_to_backup(self, new_files: List[str], modified_files: List[str]) -> List[str]:
        """
        Rule 4: Determine files to backup.
        
        Returns: new_files + modified_files (unchanged files are excluded)
        
        Args:
            new_files: List of new files
            modified_files: List of modified files
        
        Returns:
            files_to_backup = new + modified
        """
        files_to_backup = new_files + modified_files
        logger.info(f"Files to backup: {len(new_files)} new + {len(modified_files)} modified = {len(files_to_backup)} total")
        return files_to_backup


# Helper functions for backup_manager integration

def should_run_full_backup(metadata_path: str) -> bool:
    """
    Rule 1, 10: Determine if full backup should run.
    
    Full backup if:
    - No metadata file exists
    - Metadata is corrupted
    
    Args:
        metadata_path: Path to metadata file
    
    Returns:
        True if full backup should run
    """
    engine = IncrementalBackupEngine(metadata_path, "/tmp")
    
    if not engine.metadata_exists():
        logger.info("Rule 1: No metadata found. Full backup required.")
        return True
    
    if not engine.load_metadata():
        logger.info("Rule 10: Metadata corrupted. Full backup required.")
        return True
    
    return False

