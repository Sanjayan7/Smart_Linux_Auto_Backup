#!/usr/bin/env python3
"""
Complete Incremental Backup System Demonstration

This script demonstrates a production-ready incremental backup system with:
- Metadata tracking (SHA-256 + timestamp + size)
- Hard-link deduplication
- Change detection (new/modified/deleted files)
- Rsync integration
- State persistence

Author: Senior Linux Storage Engineer
Date: 2026-02-04
"""

import os
import json
import hashlib
import subprocess
import tempfile
import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple


class IncrementalBackupEngine:
    """
    Production-grade incremental backup engine.
    
    Features:
    - Efficient change detection (size -> mtime -> hash)
    - Metadata persistence in JSON
    - Hard-link deduplication via rsync --link-dest
    - Atomic operations
    """
    
    def __init__(self, source: str, destination: str):
        self.source = Path(source)
        self.destination = Path(destination)
        self.metadata_dir = self.destination / ".autobackup_metadata"
        self.metadata_file = self.metadata_dir / "backup_metadata.json"
        
        # Create metadata directory
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        # Load previous state
        self.previous_metadata = self.load_metadata()
    
    def load_metadata(self) -> Dict:
        """Load metadata from previous backup run."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    data = json.load(f)
                    files_count = len(data.get('files', {}))
                    last_backup = data.get('last_backup', 'unknown')
                    print(f"✓ Loaded metadata for {files_count} files")
                    print(f"  Last backup: {last_backup}")
                    return data
            except Exception as e:
                print(f"⚠ Error loading metadata: {e}")
                return {"files": {}}
        else:
            print("ℹ No previous metadata found - will perform full backup")
            return {"files": {}}
    
    def calculate_hash(self, filepath: Path, quick_mode: bool = False) -> str:
        """
        Calculate SHA-256 hash of file.
        
        Args:
            filepath: Path to file
            quick_mode: If True, hash only first 64KB (for large files)
        
        Returns:
            Hexadecimal hash string
        """
        sha256 = hashlib.sha256()
        
        try:
            with open(filepath, 'rb') as f:
                if quick_mode:
                    # Quick mode: hash only first 64KB
                    chunk = f.read(65536)  # 64KB
                    if chunk:
                        sha256.update(chunk)
                else:
                    # Full mode: hash entire file in chunks
                    for chunk in iter(lambda: f.read(4096), b''):
                        sha256.update(chunk)
            
            return sha256.hexdigest()
        except Exception as e:
            print(f"⚠ Hash calculation failed for {filepath}: {e}")
            return ""
    
    def scan_source(self, exclude_patterns: List[str] = None) -> Dict:
        """
        Scan source directory and collect metadata.
        
        Returns:
            Dict mapping relative paths to file metadata
        """
        exclude_patterns = exclude_patterns or []
        current_metadata = {}
        
        print(f"\n📂 Scanning source: {self.source}")
        
        file_count = 0
        for root, dirs, files in os.walk(self.source):
            root_path = Path(root)
            
            # Apply exclusions to directories (modifies in-place)
            dirs[:] = [d for d in dirs if not self._should_exclude(d, exclude_patterns)]
            
            for filename in files:
                # Skip excluded files
                if self._should_exclude(filename, exclude_patterns):
                    continue
                
                filepath = root_path / filename
                rel_path = str(filepath.relative_to(self.source))
                
                try:
                    stat = filepath.stat()
                    
                    # Use quick hash for large files (>10MB)
                    quick_mode = stat.st_size > 10 * 1024 * 1024
                    
                    current_metadata[rel_path] = {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                        "hash": self.calculate_hash(filepath, quick_mode),
                        "quick_hash": quick_mode,
                        "last_seen": datetime.now().isoformat()
                    }
                    
                    file_count += 1
                    if file_count % 100 == 0:
                        print(f"  Scanned {file_count} files...", end='\r')
                
                except Exception as e:
                    print(f"\n⚠ Error processing {rel_path}: {e}")
        
        print(f"\n✓ Scanned {len(current_metadata)} files")
        return current_metadata
    
    def _should_exclude(self, name: str, patterns: List[str]) -> bool:
        """Check if file/directory should be excluded."""
        from fnmatch import fnmatch
        return any(fnmatch(name, pattern) for pattern in patterns)
    
    def detect_changes(self, current_metadata: Dict) -> Dict:
        """
        Detect changes between current and previous state.
        
        Returns:
            Dict with lists of new, modified, deleted, and unchanged files
        """
        previous_files = self.previous_metadata.get("files", {})
        
        new_files = []
        modified_files = []
        unchanged_files = []
        deleted_files = []
        
        print(f"\n🔍 Detecting changes...")
        
        # Check each current file
        for rel_path, current_meta in current_metadata.items():
            if rel_path not in previous_files:
                # New file
                new_files.append((rel_path, current_meta["size"]))
            else:
                prev_meta = previous_files[rel_path]
                
                # Quick check: size changed?
                if current_meta["size"] != prev_meta["size"]:
                    modified_files.append((rel_path, current_meta["size"]))
                # Quick check: mtime changed?
                elif current_meta["mtime"] != prev_meta["mtime"]:
                    modified_files.append((rel_path, current_meta["size"]))
                # Hash check: content changed?
                elif current_meta["hash"] != prev_meta["hash"]:
                    modified_files.append((rel_path, current_meta["size"]))
                else:
                    # File unchanged
                    unchanged_files.append(rel_path)
        
        # Find deleted files
        for rel_path in previous_files:
            if rel_path not in current_metadata:
                deleted_files.append(rel_path)
        
        return {
            "new_files": new_files,
            "modified_files": modified_files,
            "unchanged_files": unchanged_files,
            "deleted_files": deleted_files
        }
    
    def format_size(self, bytes_size: int) -> str:
        """Convert bytes to human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} PB"
    
    def display_change_summary(self, changes: Dict):
        """Display formatted change summary."""
        print("\n" + "="*70)
        print("INCREMENTAL BACKUP - CHANGE DETECTION RESULTS")
        print("="*70)
        
        new_count = len(changes['new_files'])
        modified_count = len(changes['modified_files'])
        unchanged_count = len(changes['unchanged_files'])
        deleted_count = len(changes['deleted_files'])
        
        new_size = sum(size for _, size in changes['new_files'])
        modified_size = sum(size for _, size in changes['modified_files'])
        total_to_transfer = new_size + modified_size
        
        print(f"\n📊 Summary:")
        print(f"   ✅ New files:       {new_count:<6} ({self.format_size(new_size)})")
        print(f"   🔄 Modified files:  {modified_count:<6} ({self.format_size(modified_size)})")
        print(f"   ⏭️  Unchanged files: {unchanged_count:<6} (will be hard-linked)")
        print(f"   🗑️  Deleted files:   {deleted_count}")
        print(f"\n   📦 Total to transfer: {self.format_size(total_to_transfer)}")
        
        # Show some examples
        if new_count > 0:
            print(f"\n   New files (showing up to 5):")
            for path, size in changes['new_files'][:5]:
                print(f"      • {path} ({self.format_size(size)})")
            if new_count > 5:
                print(f"      ... and {new_count - 5} more")
        
        if modified_count > 0:
            print(f"\n   Modified files (showing up to 5):")
            for path, size in changes['modified_files'][:5]:
                print(f"      • {path} ({self.format_size(size)})")
            if modified_count > 5:
                print(f"      ... and {modified_count - 5} more")
        
        print("="*70)
    
    def find_last_backup(self) -> str:
        """Find the most recent backup directory for hard-linking."""
        try:
            backups = [d for d in self.destination.iterdir() 
                      if d.is_dir() and d.name != '.autobackup_metadata']
            
            if backups:
                # Get most recent backup
                latest = max(backups, key=lambda d: d.stat().st_mtime)
                print(f"\nℹ Previous backup found: {latest.name}")
                print(f"  Unchanged files will be hard-linked (zero space)")
                return str(latest)
        except Exception as e:
            print(f"⚠ Error finding previous backup: {e}")
        
        print(f"\nℹ No previous backup found - will do full backup")
        return None
    
    def execute_backup(self, exclude_patterns: List[str] = None, 
                      dry_run: bool = False) -> Dict:
        """
        Execute the incremental backup.
        
        Args:
            exclude_patterns: List of glob patterns to exclude
            dry_run: If True, simulate only (don't modify files)
        
        Returns:
            Dict with change statistics
        """
        print("\n" + "="*70)
        print(f"INCREMENTAL BACKUP {'(DRY RUN)' if dry_run else '(LIVE)'}")
        print("="*70)
        print(f"Source:      {self.source}")
        print(f"Destination: {self.destination}")
        
        # Step 1: Scan current state
        current_metadata = self.scan_source(exclude_patterns)
        
        # Step 2: Detect changes
        changes = self.detect_changes(current_metadata)
        
        # Step 3: Display summary
        self.display_change_summary(changes)
        
        # Check if backup is needed
        total_changes = len(changes['new_files']) + len(changes['modified_files'])
        
        if total_changes == 0:
            print("\n✓ No changes detected - backup not needed!")
            print("="*70)
            return changes
        
        # Step 4: Find previous backup for hard-linking
        link_dest = self.find_last_backup()
        
        # Step 5: Create new backup directory
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_dir = self.destination / timestamp
        
        if not dry_run:
            backup_dir.mkdir(parents=True, exist_ok=True)
            print(f"\n📁 Created backup directory: {backup_dir.name}")
        
        # Step 6: Execute rsync
        print(f"\n🚀 Executing rsync...")
        rsync_cmd = self._build_rsync_command(
            backup_dir, link_dest, exclude_patterns, dry_run
        )
        
        print(f"\nCommand:\n  {' '.join(rsync_cmd)}\n")
        
        start_time = time.time()
        
        result = subprocess.run(
            rsync_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        duration = time.time() - start_time
        
        if result.returncode != 0:
            print(f"\n❌ Rsync failed with exit code {result.returncode}")
            print(f"Output:\n{result.stdout}")
            raise RuntimeError("Backup failed")
        
        print(f"✓ Rsync completed in {duration:.2f} seconds")
        
        # Parse rsync stats
        self._display_rsync_stats(result.stdout)
        
        # Step 7: Update metadata (if not dry run)
        if not dry_run:
            self.save_metadata(current_metadata)
            print(f"\n💾 Metadata saved: {self.metadata_file.name}")
        
        print("\n" + "="*70)
        print(f"INCREMENTAL BACKUP {'(DRY RUN) ' if dry_run else ''}COMPLETE")
        print("="*70)
        
        return changes
    
    def _build_rsync_command(self, backup_dir: Path, link_dest: str,
                            exclude_patterns: List[str], dry_run: bool) -> List[str]:
        """Build rsync command with all necessary flags."""
        cmd = [
            'rsync',
            '-aH',              # Archive mode + hard links
            '--info=progress2', # Progress reporting
            '--stats'           # Statistics
        ]
        
        if dry_run:
            cmd.append('--dry-run')
            cmd.append('--itemize-changes')
        
        # Critical for incremental backup: hard-link to previous
        if link_dest:
            cmd.append(f'--link-dest={link_dest}')
        
        # Add exclusions
        for pattern in (exclude_patterns or []):
            cmd.extend(['--exclude', pattern])
        
        # Source (must end with slash)
        source = str(self.source)
        if not source.endswith('/'):
            source += '/'
        
        cmd.extend([source, str(backup_dir)])
        
        return cmd
    
    def _display_rsync_stats(self, output: str):
        """Parse and display rsync statistics."""
        import re
        
        stats = {}
        
        patterns = {
            "files": re.compile(r"Number of files:\s+([0-9,]+)"),
            "transferred": re.compile(r"Number of files transferred:\s+([0-9,]+)"),
            "total_size": re.compile(r"Total file size:\s+([0-9,.]+)\s*(\w+)"),
        }
        
        for line in output.splitlines():
            for key, pattern in patterns.items():
                match = pattern.search(line)
                if match:
                    if key == "total_size":
                        stats[key] = f"{match.group(1)} {match.group(2)}"
                    else:
                        stats[key] = match.group(1).replace(',', '')
        
        if stats:
            print(f"\n📈 Rsync Statistics:")
            print(f"   Total files:       {stats.get('files', 'N/A')}")
            print(f"   Files transferred: {stats.get('transferred', 'N/A')}")
            print(f"   Total size:        {stats.get('total_size', 'N/A')}")
    
    def save_metadata(self, current_metadata: Dict):
        """Save current metadata for next incremental run."""
        # Backup previous metadata
        if self.metadata_file.exists():
            prev_file = self.metadata_dir / "backup_metadata.json.prev"
            shutil.copy2(self.metadata_file, prev_file)
            print(f"  Previous metadata backed up to: {prev_file.name}")
        
        # Prepare metadata
        metadata = {
            "last_backup": datetime.now().isoformat(),
            "backup_version": "1.0",
            "source_directory": str(self.source),
            "files": current_metadata,
            "statistics": {
                "total_files": len(current_metadata),
                "total_size_bytes": sum(f["size"] for f in current_metadata.values()),
                "quick_hash_count": sum(1 for f in current_metadata.values() if f.get("quick_hash", False))
            }
        }
        
        # Atomic write (write to temp, then rename)
        temp_file = self.metadata_file.with_suffix('.tmp')
        
        with open(temp_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        temp_file.rename(self.metadata_file)


def create_test_scenario():
    """Create a realistic test scenario for incremental backup."""
    
    # Create temporary directories
    test_dir = tempfile.mkdtemp(prefix='incremental_backup_test_')
    source_dir = Path(test_dir) / 'source'
    dest_dir = Path(test_dir) / 'backups'
    
    source_dir.mkdir()
    dest_dir.mkdir()
    
    print("\n" + "="*70)
    print("CREATING TEST SCENARIO")
    print("="*70)
    print(f"Test directory: {test_dir}")
    print(f"Source:         {source_dir}")
    print(f"Destination:    {dest_dir}")
    
    # Create initial files
    print(f"\n📝 Creating initial files...")
    
    files = {
        'README.md': 'Project README version 1.0\n' * 10,
        'config.json': '{"version": "1.0", "debug": false}\n',
        'data/users.csv': 'id,name,email\n' + '\n'.join([f'{i},User{i},user{i}@example.com' for i in range(100)]),
        'data/products.csv': 'id,name,price\n' + '\n'.join([f'{i},Product{i},{i*10}.99' for i in range(50)]),
        'logs/app.log': 'Application log\n' * 100,
        'scripts/backup.sh': '#!/bin/bash\necho "Backup script"\n' * 5,
    }
    
    for filepath, content in files.items():
        full_path = source_dir / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
    
    print(f"✓ Created {len(files)} initial files")
    
    return test_dir, source_dir, dest_dir, files


def run_demo():
    """Run complete incremental backup demonstration."""
    
    # Create test scenario
    test_dir, source_dir, dest_dir, initial_files = create_test_scenario()
    
    try:
        # Initialize backup engine
        engine = IncrementalBackupEngine(str(source_dir), str(dest_dir))
        
        # ============================================================
        # BACKUP 1: Initial full backup
        # ============================================================
        print("\n\n")
        print("█" * 70)
        print("BACKUP #1: INITIAL FULL BACKUP")
        print("█" * 70)
        
        input("\nPress Enter to start first backup...")
        
        changes1 = engine.execute_backup(exclude_patterns=['*.tmp', '.git'])
        
        # ============================================================
        # BACKUP 2: No changes (should be instant)
        # ============================================================
        print("\n\n")
        print("█" * 70)
        print("BACKUP #2: NO CHANGES TEST")
        print("█" * 70)
        
        input("\nPress Enter to run second backup (no changes)...")
        
        changes2 = engine.execute_backup(exclude_patterns=['*.tmp', '.git'])
        
        # ============================================================
        # BACKUP 3: Some changes
        # ============================================================
        print("\n\n")
        print("█" * 70)
        print("BACKUP #3: WITH CHANGES")
        print("█" * 70)
        
        print("\n📝 Making changes to source files...")
        time.sleep(0.1)  # Ensure timestamp difference
        
        # Add new file
        (source_dir / 'NEW_FILE.txt').write_text('This is a new file\n' * 20)
        print("   ✓ Added: NEW_FILE.txt")
        
        # Modify existing file
        (source_dir / 'config.json').write_text('{"version": "2.0", "debug": true}\n')
        print("   ✓ Modified: config.json")
        
        # Delete a file
        (source_dir / 'logs' / 'app.log').unlink()
        print("   ✓ Deleted: logs/app.log")
        
        input("\nPress Enter to run third backup (with changes)...")
        
        changes3 = engine.execute_backup(exclude_patterns=['*.tmp', '.git'])
        
        # ============================================================
        # VERIFICATION
        # ============================================================
        print("\n\n")
        print("█" * 70)
        print("VERIFICATION & RESULTS")
        print("█" * 70)
        
        # Check backup directories
        backups = sorted([d for d in dest_dir.iterdir() if d.is_dir() and d.name != '.autobackup_metadata'])
        
        print(f"\n📁 Backup directories created: {len(backups)}")
        for backup in backups:
            size = sum(f.stat().st_size for f in backup.rglob('*') if f.is_file())
            file_count = sum(1 for _ in backup.rglob('*') if _.is_file())
            print(f"   {backup.name}: {file_count} files, {engine.format_size(size)}")
        
        # Check hard links
        print(f"\n🔗 Verifying hard links...")
        if len(backups) >= 2:
            # Check if unchanged file has same inode
            file1 = backups[0] / 'README.md'
            file2 = backups[1] / 'README.md'
            
            if file1.exists() and file2.exists():
                inode1 = file1.stat().st_ino
                inode2 = file2.stat().st_ino
                
                if inode1 == inode2:
                    print(f"   ✓ README.md is hard-linked (inode: {inode1})")
                    print(f"     → Zero additional space used!")
                else:
                    print(f"   ℹ README.md was copied (different inodes)")
        
        # Check metadata
        metadata_file = dest_dir / '.autobackup_metadata' / 'backup_metadata.json'
        if metadata_file.exists():
            with open(metadata_file) as f:
                metadata = json.load(f)
            
            print(f"\n💾 Metadata:")
            print(f"   Tracked files: {len(metadata.get('files', {}))}")
            print(f"   Last backup:   {metadata.get('last_backup', 'N/A')}")
            print(f"   Total size:    {engine.format_size(metadata.get('statistics', {}).get('total_size_bytes', 0))}")
        
        print("\n" + "="*70)
        print("DEMONSTRATION COMPLETE ✓")
        print("="*70)
        print(f"\nTest files remain at: {test_dir}")
        print(f"You can inspect them manually before cleanup.")
        
        input("\nPress Enter to cleanup test files...")
        
    finally:
        # Cleanup
        print(f"\n🧹 Cleaning up: {test_dir}")
        shutil.rmtree(test_dir)
        print("✓ Cleanup complete")


if __name__ == '__main__':
    print("\n" + "█"*70)
    print("INCREMENTAL BACKUP SYSTEM - LIVE DEMONSTRATION")
    print("█"*70)
    print("\nThis demonstration will:")
    print("  1. Create a test source directory with sample files")
    print("  2. Perform an initial full backup")
    print("  3. Run incremental backup with no changes (instant)")
    print("  4. Make some changes and run incremental backup")
    print("  5. Verify hard-link deduplication")
    print("  6. Show metadata tracking")
    print("\n" + "█"*70)
    
    input("\nPress Enter to start demonstration...")
    
    run_demo()
    
    print("\n✨ Demonstration complete!")
    print("\nKey takeaways:")
    print("  ✓ First backup: Full copy of all files")
    print("  ✓ Second backup: Zero files copied (all hard-linked)")
    print("  ✓ Third backup: Only changed files copied")
    print("  ✓ Metadata tracks state between backups")
    print("  ✓ Storage efficient (hard links eliminate duplication)")
