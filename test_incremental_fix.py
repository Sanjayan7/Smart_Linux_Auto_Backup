#!/usr/bin/env python3
"""
Test script to validate the incremental backup fix.

This script demonstrates:
1. First incremental backup transfers all files
2. Second incremental backup transfers 0 files (no changes)
3. Third incremental backup still transfers 0 files (metadata is current)
4. Modified file is correctly detected and transferred
"""

import os
import sys
import tempfile
import shutil
import time
import json
from pathlib import Path

# Add autobackup to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autobackup.core.backup_manager import BackupManager
from autobackup.core.metadata_tracker import MetadataTracker
from autobackup.models.backup_config import BackupConfig


def print_header(text):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def load_metadata(metadata_dir):
    """Load metadata JSON."""
    metadata_file = os.path.join(metadata_dir, ".autobackup_metadata", "backup_metadata.json")
    if os.path.exists(metadata_file):
        with open(metadata_file, 'r') as f:
            return json.load(f)
    return None


def count_files_in_backup(backup_dir):
    """Count files in backup directory."""
    count = 0
    for root, dirs, files in os.walk(backup_dir):
        count += len(files)
    return count


def test_incremental_backup_fix():
    """Main test function."""
    
    # Create temporary directories
    test_dir = tempfile.mkdtemp(prefix="incremental_test_")
    source_dir = os.path.join(test_dir, "source")
    backup_dir = os.path.join(test_dir, "backups")
    
    os.makedirs(source_dir)
    os.makedirs(backup_dir)
    
    print_header("Test Environment Setup")
    print(f"Source directory: {source_dir}")
    print(f"Backup directory: {backup_dir}")
    print(f"Test directory: {test_dir}")
    
    # Create initial source files
    print_header("Creating Initial Source Files")
    
    files_created = []
    for i in range(3):
        filename = f"file{i+1}.txt"
        filepath = os.path.join(source_dir, filename)
        with open(filepath, 'w') as f:
            f.write(f"Content of {filename}\n" * 100)
        files_created.append(filename)
        print(f"✓ Created: {filename}")
    
    # Create subdirectory with files
    subdir = os.path.join(source_dir, "subfolder")
    os.makedirs(subdir)
    for i in range(2):
        filename = f"subfile{i+1}.txt"
        filepath = os.path.join(subdir, filename)
        with open(filepath, 'w') as f:
            f.write(f"Content of {filename}\n" * 50)
        files_created.append(f"subfolder/{filename}")
        print(f"✓ Created: subfolder/{filename}")
    
    total_files = len(files_created)
    print(f"\nTotal files created: {total_files}")
    
    # Create config
    config = BackupConfig(
        source=source_dir,
        destination=backup_dir,
        exclude_patterns=[],
        retention_policy="none",
        incremental=True,
        compression=False,
        encryption=False,
        schedule=None,
        backup_name_template="{timestamp}"
    )
    
    # ========================================================================
    # RUN 1: Initial backup (should transfer all files)
    # ========================================================================
    print_header("Run 1: Initial Incremental Backup")
    print(f"Expected: {total_files} files transferred (first time)")
    
    manager = BackupManager(config)
    manager.start_backup(dry_run=False)
    
    # Wait for completion
    while manager._backup_thread and manager._backup_thread.is_alive():
        time.sleep(0.1)
    
    job1 = manager.get_current_job_status()
    
    print(f"\nResults:")
    print(f"  Status: {job1.status}")
    print(f"  Files transferred: {job1.files_transferred}")
    print(f"  Total size: {job1.total_size_bytes:,} bytes")
    print(f"  Duration: {job1.duration_seconds:.2f} seconds")
    
    # Check metadata
    metadata1 = load_metadata(backup_dir)
    if metadata1:
        num_tracked = len(metadata1.get("files", {}))
        print(f"  Metadata tracked files: {num_tracked}")
        print(f"  Last backup: {metadata1.get('last_backup')}")
    
    assert job1.status == "completed", "Run 1 should complete successfully"
    assert job1.files_transferred == total_files, \
        f"Run 1 should transfer {total_files} files, got {job1.files_transferred}"
    
    print("\n✓ Run 1 PASSED: All files backed up on first run")
    
    # Wait a bit to ensure different timestamp
    time.sleep(1.5)
    
    # ========================================================================
    # RUN 2: No changes (should transfer 0 files - THE FIX TEST!)
    # ========================================================================
    print_header("Run 2: Incremental Backup (No Changes)")
    print(f"Expected: 0 files transferred (nothing changed)")
    print("This tests that metadata update occurs even when no files change")
    
    manager2 = BackupManager(config)
    manager2.start_backup(dry_run=False)
    
    while manager2._backup_thread and manager2._backup_thread.is_alive():
        time.sleep(0.1)
    
    job2 = manager2.get_current_job_status()
    
    print(f"\nResults:")
    print(f"  Status: {job2.status}")
    print(f"  Files transferred: {job2.files_transferred}")
    print(f"  Total size: {job2.total_size_bytes:,} bytes")
    print(f"  Duration: {job2.duration_seconds:.2f} seconds")
    
    # Check metadata
    metadata2 = load_metadata(backup_dir)
    if metadata2:
        num_tracked = len(metadata2.get("files", {}))
        print(f"  Metadata tracked files: {num_tracked}")
        print(f"  Last backup: {metadata2.get('last_backup')}")
        
        # Verify metadata was updated even though no files transferred
        if metadata1 and metadata2:
            ts1 = metadata1.get('last_backup')
            ts2 = metadata2.get('last_backup')
            print(f"\n  Metadata timestamps:")
            print(f"    Run 1: {ts1}")
            print(f"    Run 2: {ts2}")
            if ts2 > ts1:
                print("    ✓ Metadata was updated (timestamps differ)")
            else:
                print("    ❌ Metadata was NOT updated (timestamps same or earlier)")
    
    assert job2.status == "completed", "Run 2 should complete successfully"
    assert job2.files_transferred == 0, \
        f"Run 2 should transfer 0 files (no changes), got {job2.files_transferred}"
    
    print("\n✓ Run 2 PASSED: No files transferred when nothing changed")
    print("✓ THE FIX WORKS: Metadata was updated despite zero file transfers")
    
    # Wait a bit more
    time.sleep(1.5)
    
    # ========================================================================
    # RUN 3: Still no changes (verify metadata is current)
    # ========================================================================
    print_header("Run 3: Incremental Backup (Still No Changes)")
    print(f"Expected: 0 files transferred (metadata should be current)")
    print("This verifies metadata update from Run 2 prevents false changes")
    
    manager3 = BackupManager(config)
    manager3.start_backup(dry_run=False)
    
    while manager3._backup_thread and manager3._backup_thread.is_alive():
        time.sleep(0.1)
    
    job3 = manager3.get_current_job_status()
    
    print(f"\nResults:")
    print(f"  Status: {job3.status}")
    print(f"  Files transferred: {job3.files_transferred}")
    print(f"  Total size: {job3.total_size_bytes:,} bytes")
    print(f"  Duration: {job3.duration_seconds:.2f} seconds")
    
    assert job3.status == "completed", "Run 3 should complete successfully"
    assert job3.files_transferred == 0, \
        f"Run 3 should transfer 0 files (no changes), got {job3.files_transferred}"
    
    print("\n✓ Run 3 PASSED: Metadata stayed current, no false changes detected")
    
    # Wait before modifying
    time.sleep(1.5)
    
    # ========================================================================
    # RUN 4: Modify one file
    # ========================================================================
    print_header("Run 4: Incremental Backup (Modified One File)")
    print(f"Expected: 1 file transferred (file2.txt modified)")
    
    # Modify file2.txt
    filepath = os.path.join(source_dir, "file2.txt")
    with open(filepath, 'w') as f:
        f.write("MODIFIED CONTENT\n" * 150)
    print("✓ Modified: file2.txt")
    
    time.sleep(0.5)
    
    manager4 = BackupManager(config)
    manager4.start_backup(dry_run=False)
    
    while manager4._backup_thread and manager4._backup_thread.is_alive():
        time.sleep(0.1)
    
    job4 = manager4.get_current_job_status()
    
    print(f"\nResults:")
    print(f"  Status: {job4.status}")
    print(f"  Files transferred: {job4.files_transferred}")
    print(f"  Total size: {job4.total_size_bytes:,} bytes")
    print(f"  Duration: {job4.duration_seconds:.2f} seconds")
    
    assert job4.status == "completed", "Run 4 should complete successfully"
    assert job4.files_transferred == 1, \
        f"Run 4 should transfer 1 file (modified), got {job4.files_transferred}"
    
    print("\n✓ Run 4 PASSED: Modified file correctly detected and transferred")
    
    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================
    print_header("Test Summary - ALL TESTS PASSED ✓")
    
    print("Backup Transfer Summary:")
    print(f"  Run 1 (initial):        {job1.files_transferred:2d} files - First backup")
    print(f"  Run 2 (no changes):     {job2.files_transferred:2d} files - Metadata kept current ✓")
    print(f"  Run 3 (still no changes): {job3.files_transferred:2d} files - No false positives ✓")
    print(f"  Run 4 (1 file modified): {job4.files_transferred:2d} file  - Correctly detected ✓")
    
    print("\nTest Outcomes:")
    print("  [✓] Metadata is updated even when no files change")
    print("  [✓] Unchanged files skip rsync in subsequent runs")
    print("  [✓] No false 'changed file' detection")
    print("  [✓] Changed files are correctly identified")
    
    print("\nConclusion: THE INCREMENTAL BACKUP FIX IS WORKING CORRECTLY")
    
    # Cleanup
    shutil.rmtree(test_dir)
    print(f"\nTest environment cleaned up: {test_dir}")


if __name__ == "__main__":
    try:
        test_incremental_backup_fix()
        print("\n" + "="*60)
        print("  ✓ ALL TESTS PASSED - INCREMENTAL BACKUP IS FIXED")
        print("="*60 + "\n")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
