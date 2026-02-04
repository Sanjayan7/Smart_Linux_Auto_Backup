"""
Metadata Tracker for Incremental Backup

This module provides metadata tracking capabilities to support proper incremental
backups. It tracks file checksums and modification times to accurately detect
which files have changed since the last backup.

Features:
- SHA-256 checksum calculation for files
- Metadata persistence in JSON format
- Changed file detection
- Integration with rsync for efficient backup
"""

import os
import hashlib
import json
from typing import Dict, List, Set, Optional
from pathlib import Path
from datetime import datetime
from autobackup.utils.logger import logger


class MetadataTracker:
    """
    Tracks file metadata (checksums, timestamps) for incremental backup verification.
    """
    
    def __init__(self, metadata_dir: str, source_dir: str):
        """
        Initialize metadata tracker.
        
        Args:
            metadata_dir: Directory to store metadata files
            source_dir: Source directory being backed up
        """
        self.metadata_dir = Path(metadata_dir)
        self.source_dir = Path(source_dir)
        self.metadata_file = self.metadata_dir / "backup_metadata.json"
        self.metadata: Dict[str, Dict[str, any]] = {}
        
        # Ensure metadata directory exists
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing metadata if available
        self.load_metadata()
    
    def calculate_file_hash(self, filepath: str, quick_mode: bool = False) -> str:
        """
        Calculate SHA-256 hash of a file.
        
        Args:
            filepath: Path to the file
            quick_mode: If True, only hash first 64KB for speed (useful for large files)
        
        Returns:
            Hexadecimal hash string
        """
        try:
            sha256_hash = hashlib.sha256()
            
            with open(filepath, "rb") as f:
                if quick_mode:
                    # For large files, only hash the first 64KB for speed
                    chunk = f.read(65536)  # 64KB
                    sha256_hash.update(chunk)
                else:
                    # Hash entire file in chunks
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
            
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.warning(f"Failed to calculate hash for {filepath}: {e}")
            return ""
    
    def get_file_metadata(self, filepath: Path) -> Dict[str, any]:
        """
        Get metadata for a single file.
        
        Args:
            filepath: Path to the file
        
        Returns:
            Dict with file metadata (mtime, size, hash)
        """
        try:
            stat = filepath.stat()
            
            # For files larger than 10MB, use quick mode (hash only first 64KB)
            quick_mode = stat.st_size > 10 * 1024 * 1024
            
            return {
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "hash": self.calculate_file_hash(str(filepath), quick_mode=quick_mode),
                "quick_hash": quick_mode
            }
        except Exception as e:
            logger.warning(f"Failed to get metadata for {filepath}: {e}")
            return {}
    
    def scan_directory(self, exclude_patterns: List[str] = None) -> Dict[str, Dict[str, any]]:
        """
        Scan source directory and collect metadata for all files.
        
        Args:
            exclude_patterns: List of glob patterns to exclude
        
        Returns:
            Dict mapping relative paths to file metadata
        """
        exclude_patterns = exclude_patterns or []
        current_metadata = {}
        
        logger.info(f"Scanning directory: {self.source_dir}")
        
        for root, dirs, files in os.walk(self.source_dir):
            root_path = Path(root)
            
            # Filter directories by exclude patterns
            dirs[:] = [d for d in dirs if not self._should_exclude(
                str((root_path / d).relative_to(self.source_dir)), exclude_patterns
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
        
        logger.info(f"Scanned {len(current_metadata)} files")
        return current_metadata
    
    def _should_exclude(self, path: str, patterns: List[str]) -> bool:
        """Check if path matches any exclude pattern."""
        from fnmatch import fnmatch
        for pattern in patterns:
            if fnmatch(path, pattern) or fnmatch(Path(path).name, pattern):
                return True
        return False
    
    def get_changed_files(self, exclude_patterns: List[str] = None) -> Dict[str, List[str]]:
        """
        Detect which files have changed since last backup.
        
        Args:
            exclude_patterns: List of glob patterns to exclude
        
        Returns:
            Dict with lists of: new_files, modified_files, deleted_files, unchanged_files
        """
        current_metadata = self.scan_directory(exclude_patterns)
        
        new_files = []
        modified_files = []
        deleted_files = []
        unchanged_files = []
        
        # Find new and modified files
        for rel_path, current_meta in current_metadata.items():
            if rel_path not in self.metadata:
                # New file
                new_files.append(rel_path)
            else:
                old_meta = self.metadata[rel_path]
                
                # Check if file has changed
                # First check size and mtime for quick detection
                if (current_meta["size"] != old_meta["size"] or
                    current_meta["mtime"] != old_meta["mtime"]):
                    # Size or mtime changed - definitely modified
                    modified_files.append(rel_path)
                elif current_meta["hash"] != old_meta["hash"]:
                    # Hash changed - file content changed
                    modified_files.append(rel_path)
                else:
                    # File is unchanged
                    unchanged_files.append(rel_path)
        
        # Find deleted files
        for rel_path in self.metadata:
            if rel_path not in current_metadata:
                deleted_files.append(rel_path)
        
        logger.info(f"Change detection: {len(new_files)} new, {len(modified_files)} modified, "
                   f"{len(deleted_files)} deleted, {len(unchanged_files)} unchanged")
        
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
        Update stored metadata after successful backup.
        
        Args:
            new_metadata: If provided, use this metadata; otherwise scan directory
            exclude_patterns: List of glob patterns to exclude (used if scanning)
        """
        if new_metadata is None:
            new_metadata = self.scan_directory(exclude_patterns)
        
        self.metadata = new_metadata
        self.save_metadata()
        logger.info(f"Updated metadata for {len(self.metadata)} files")
    
    def save_metadata(self):
        """Save metadata to JSON file."""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump({
                    "last_backup": datetime.now().isoformat(),
                    "files": self.metadata
                }, f, indent=2)
            logger.info(f"Saved metadata to {self.metadata_file}")
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
    
    def load_metadata(self):
        """Load metadata from JSON file if it exists."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    data = json.load(f)
                    self.metadata = data.get("files", {})
                    last_backup = data.get("last_backup")
                    logger.info(f"Loaded metadata for {len(self.metadata)} files "
                               f"(last backup: {last_backup})")
            except Exception as e:
                logger.error(f"Failed to load metadata: {e}")
                self.metadata = {}
        else:
            logger.info("No existing metadata found - this will be a full backup")
            self.metadata = {}
    
    def get_stats(self) -> Dict[str, any]:
        """Get statistics about tracked metadata."""
        if not self.metadata:
            return {"tracked_files": 0, "last_backup": None}
        
        total_size = sum(meta.get("size", 0) for meta in self.metadata.values())
        
        return {
            "tracked_files": len(self.metadata),
            "total_size": total_size,
            "last_backup": self.metadata_file.stat().st_mtime if self.metadata_file.exists() else None
        }
