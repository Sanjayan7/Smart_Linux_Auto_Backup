#!/usr/bin/env python3
"""
Validation script for incremental backup fix.

This script tests that incremental backups properly:
1. Skip rsync when no files changed
2. Only backup changed files when updates exist
3. Properly update metadata after backup
"""

import os
import sys
import json
import tempfile
import shutil
import hashlib
import time
from pathlib import Path

# Add autobackup to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'autobackup'))

from autobackup.core.backup_manager import BackupManager
from autobackup.core.metadata_tracker import MetadataTracker
from autobackup.models.backup_config import BackupConfig
from autobackup.core.rsync_engine import RsyncEngine


class ValidationTest:
    """Test incremental backup functionality."""
    
    def __init__(self):
        """Initialize test environment."""
        self.test_dir = tempfile.mkdtemp(prefix="incremental_test_")
        self.source_dir = os.path.join(self.test_dir, "source")
        self.backup_dir = os.path.join(self.test_dir, "backups")
        self.metadata_dir = os.path.join(self.test_dir, ".metadata")
        
        os.makedirs(self.source_dir)
        os.makedirs(self.backup_dir)
        os.makedirs(self.metadata_dir)
        
        print(f"✓ Test environment created: {self.test_dir}")
    
    def cleanup(self):
        """Clean up test environment."""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
            print(f"✓ Test environment cleaned up")
    
    def create_test_file(self, name: str, content: str = None) -> str:
        """Create a test file."""
        filepath = os.path.join(self.source_dir, name)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        if content is None:
            content = f"Test file: {name}\n" * 100
        
        with open(filepath, 'w') as f:
            f.write(content)
        
        return filepath
    
    def modify_test_file(self, name: str, content: str = None):
        """Modify a test file."""
        filepath = os.path.join(self.source_dir, name)
        if content is None:
            content = f"Modified content for {name}\n" * 100
        
        with open(filepath, 'w') as f:
            f.write(content)
        
        print(f"  Modified: {name}")
    
    def get_file_hash(self, filepath: str) -> str:
        """Calculate SHA-256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def run_incremental_backup(self, backup_num: int) -> dict:
        """Run an incremental backup and return stats."""
        print(f"\n--- Backup Run #{backup_num} ---")
        
        # Setup metadata tracker
        metadata_tracker = MetadataTracker(
            source_dir=self.source_dir,
            metadata_dir=self.metadata_dir
        )
        
        # Get change report
        change_report = metadata_tracker.get_changed_files(exclude_patterns=[])
        
        stats = {
            "run": backup_num,
            "new_files": len(change_report["new_files"]),
            "modified_files": len(change_report["modified_files"]),
            "unchanged_files": len(change_report["unchanged_files"]),
            "deleted_files": len(change_report["deleted_files"]),
            "timestamp": time.time()
        }
        
        print(f"  New files: {stats['new_files']}")
        print(f"  Modified files: {stats['modified_files']}")
        print(f"  Unchanged files: {stats['unchanged_files']}")
        
        # Create backup directory
        backup_path = os.path.join(self.backup_dir, f"backup_{backup_num}")
        os.makedirs(backup_path, exist_ok=True)
        
        # Setup rsync engine
        rsync_engine = RsyncEngine()
        
        # Determine files to backup
        files_to_backup = (
            change_report["new_files"] + 
            change_report["modified_files"]
        )
        
        if files_to_backup:
            # Run rsync with files list
            print(f"  Backing up {len(files_to_backup)} files...")
            try:
                rsync_stats = rsync_engine.run_rsync(
                    source=self.source_dir,
                    destination=backup_path,
                    exclude_patterns=[],
                    dry_run=False,
                    files_from_list=files_to_backup
                )
                stats["rsync_files_transferred"] = rsync_stats.get("files_transferred", 0)
                print(f"  Rsync transferred: {stats['rsync_files_transferred']} files")
            except Exception as e:
                print(f"  ✗ Rsync failed: {e}")
                stats["rsync_error"] = str(e)
        else:
            # Skip rsync - no files changed
            print(f"  No files changed - skipping rsync")
            stats["rsync_skipped"] = True
            stats["rsync_files_transferred"] = 0
        
        # Update metadata
        if stats.get("rsync_files_transferred", 0) > 0:
            metadata_tracker.update_metadata(exclude_patterns=[])
            print(f"  Metadata updated")
            stats["metadata_updated"] = True
        else:
            print(f"  Metadata NOT updated (no files transferred)")
            stats["metadata_updated"] = False
        
        return stats
    
    def test_scenario_1_initial_backup(self):
        """Test Case 1: Initial backup with no prior metadata."""
        print("\n" + "=" * 60)
        print("TEST 1: Initial Backup (No Prior Metadata)")
        print("=" * 60)
        
        # Create initial files
        self.create_test_file("file1.txt", "Content 1\n" * 100)
        self.create_test_file("file2.txt", "Content 2\n" * 100)
        self.create_test_file("subdir/file3.txt", "Content 3\n" * 100)
        print("✓ Created 3 test files")
        
        # Run first backup
        stats = self.run_incremental_backup(1)
        
        # Verify
        assert stats["new_files"] == 3, f"Expected 3 new files, got {stats['new_files']}"
        assert stats["modified_files"] == 0, f"Expected 0 modified files"
        assert stats["unchanged_files"] == 0, f"Expected 0 unchanged files"
        assert stats.get("rsync_files_transferred", 0) > 0, "Expected rsync to transfer files"
        assert stats.get("metadata_updated") is True, "Expected metadata to be updated"
        
        print("✓ Test 1 PASSED: Initial backup works correctly")
        return True
    
    def test_scenario_2_unchanged_files(self):
        """Test Case 2: Run backup again with unchanged files."""
        print("\n" + "=" * 60)
        print("TEST 2: Unchanged Files (Incremental Skip)")
        print("=" * 60)
        
        # Run second backup without any changes
        stats = self.run_incremental_backup(2)
        
        # Verify
        assert stats["new_files"] == 0, f"Expected 0 new files, got {stats['new_files']}"
        assert stats["modified_files"] == 0, f"Expected 0 modified files"
        assert stats["unchanged_files"] == 3, f"Expected 3 unchanged files, got {stats['unchanged_files']}"
        assert stats.get("rsync_skipped") is True, "Expected rsync to be skipped"
        assert stats.get("rsync_files_transferred", 0) == 0, "Expected 0 files transferred"
        assert stats.get("metadata_updated") is False, "Expected metadata NOT to be updated"
        
        print("✓ Test 2 PASSED: Unchanged files are correctly skipped")
        return True
    
    def test_scenario_3_modified_file(self):
        """Test Case 3: Modify one file."""
        print("\n" + "=" * 60)
        print("TEST 3: Modified File (Incremental Update)")
        print("=" * 60)
        
        # Modify one file
        self.modify_test_file("file1.txt", "Modified Content 1\n" * 100)
        
        # Run backup
        stats = self.run_incremental_backup(3)
        
        # Verify
        assert stats["new_files"] == 0, f"Expected 0 new files"
        assert stats["modified_files"] == 1, f"Expected 1 modified file, got {stats['modified_files']}"
        assert stats["unchanged_files"] == 2, f"Expected 2 unchanged files"
        assert stats.get("rsync_files_transferred", 0) > 0, "Expected rsync to transfer modified file"
        assert stats.get("metadata_updated") is True, "Expected metadata to be updated"
        
        print("✓ Test 3 PASSED: Modified file is correctly detected and backed up")
        return True
    
    def test_scenario_4_unchanged_again(self):
        """Test Case 4: Run backup again - should skip."""
        print("\n" + "=" * 60)
        print("TEST 4: Unchanged After Modification (Skip Again)")
        print("=" * 60)
        
        # Run backup without any new changes
        stats = self.run_incremental_backup(4)
        
        # Verify
        assert stats["new_files"] == 0, f"Expected 0 new files"
        assert stats["modified_files"] == 0, f"Expected 0 modified files, got {stats['modified_files']}"
        assert stats["unchanged_files"] == 3, f"Expected 3 unchanged files"
        assert stats.get("rsync_skipped") is True, "Expected rsync to be skipped"
        assert stats.get("rsync_files_transferred", 0) == 0, "Expected 0 files transferred"
        
        print("✓ Test 4 PASSED: Metadata correctly updated, skip works again")
        return True
    
    def test_scenario_5_new_file(self):
        """Test Case 5: Add a new file."""
        print("\n" + "=" * 60)
        print("TEST 5: New File (Add to Backup)")
        print("=" * 60)
        
        # Add new file
        self.create_test_file("newfile.txt", "New File Content\n" * 100)
        
        # Run backup
        stats = self.run_incremental_backup(5)
        
        # Verify
        assert stats["new_files"] == 1, f"Expected 1 new file, got {stats['new_files']}"
        assert stats["modified_files"] == 0, f"Expected 0 modified files"
        assert stats["unchanged_files"] == 3, f"Expected 3 unchanged files (should not include new)"
        assert stats.get("rsync_files_transferred", 0) > 0, "Expected rsync to transfer new file"
        assert stats.get("metadata_updated") is True, "Expected metadata to be updated"
        
        print("✓ Test 5 PASSED: New file correctly detected and backed up")
        return True
    
    def run_all_tests(self):
        """Run all validation tests."""
        print("\n" + "=" * 80)
        print("INCREMENTAL BACKUP FIX VALIDATION TESTS")
        print("=" * 80)
        
        try:
            results = []
            
            # Run tests in sequence
            results.append(("Test 1: Initial Backup", self.test_scenario_1_initial_backup()))
            results.append(("Test 2: Unchanged Files", self.test_scenario_2_unchanged_files()))
            results.append(("Test 3: Modified File", self.test_scenario_3_modified_file()))
            results.append(("Test 4: Unchanged Again", self.test_scenario_4_unchanged_again()))
            results.append(("Test 5: New File", self.test_scenario_5_new_file()))
            
            # Print summary
            print("\n" + "=" * 80)
            print("TEST SUMMARY")
            print("=" * 80)
            
            passed = sum(1 for _, result in results if result)
            total = len(results)
            
            for test_name, result in results:
                status = "✓ PASSED" if result else "✗ FAILED"
                print(f"{test_name}: {status}")
            
            print(f"\nTotal: {passed}/{total} tests passed")
            
            if passed == total:
                print("\n✓ ALL TESTS PASSED - Incremental backup fix is working!")
                return True
            else:
                print(f"\n✗ {total - passed} tests failed")
                return False
        
        except Exception as e:
            print(f"\n✗ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            self.cleanup()


if __name__ == "__main__":
    validator = ValidationTest()
    success = validator.run_all_tests()
    sys.exit(0 if success else 1)
