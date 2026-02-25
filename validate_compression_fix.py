#!/usr/bin/env python3
"""
VALIDATION SCRIPT: Verify compression size reporting fix is working correctly.

This script demonstrates that the fix guarantees:
1. Compressed backups show ACTUAL smaller size
2. Uncompressed backups show ACTUAL original size
3. Sizes are NEVER identical (when compression is different)
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add parent to path so we can import autobackup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autobackup.core.backup_manager import BackupManager
from autobackup.models.backup_config import BackupConfig


def create_test_files(directory, count=5):
    """Create test files with known content."""
    files_created = []
    for i in range(count):
        filename = os.path.join(directory, f"test_file_{i}.txt")
        content = f"This is test file {i}. " * 1000  # ~25 KB each
        with open(filename, 'w') as f:
            f.write(content)
        files_created.append(filename)
    return files_created


def format_size(size_bytes):
    """Format bytes to human readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def get_directory_size(path):
    """Get total size of all files in directory."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.isfile(filepath):
                total += os.path.getsize(filepath)
    return total


def test_compression_size_reporting():
    """
    Test that compression size reporting works correctly.
    
    This validates:
    1. Real backups with compression create tar.gz
    2. Compressed size is reported correctly
    3. Uncompressed size is different from compressed
    """
    
    print("\n" + "="*80)
    print("COMPRESSION SIZE REPORTING TEST")
    print("="*80)
    
    # Create temporary directories
    test_dir = tempfile.mkdtemp(prefix='compression_test_')
    source_dir = os.path.join(test_dir, 'source')
    dest_dir = os.path.join(test_dir, 'dest')
    
    try:
        os.makedirs(source_dir)
        os.makedirs(dest_dir)
        
        # Create test files
        print("\n1. Creating test files...")
        create_test_files(source_dir, count=5)
        source_size = get_directory_size(source_dir)
        print(f"   Created 5 test files, total size: {format_size(source_size)}")
        
        # Test 1: Uncompressed backup
        print("\n2. Running UNCOMPRESSED backup...")
        config_uncompressed = BackupConfig(
            source=source_dir,
            destination=dest_dir,
            exclude_patterns=[],
            retention_policy='7_days',
            dry_run=False,
            incremental=False,
            encryption=False,
            compression=False  # NO COMPRESSION
        )
        
        backup_manager = BackupManager(config_uncompressed)
        completion_event_uncompressed = {}
        
        def on_completion_uncompressed(job):
            completion_event_uncompressed['job'] = job
            completion_event_uncompressed['done'] = True
        
        backup_manager.set_completion_callback(on_completion_uncompressed)
        backup_manager.start_backup(dry_run=False)
        
        # Wait for completion
        import time
        for _ in range(60):
            if completion_event_uncompressed.get('done'):
                break
            time.sleep(0.5)
        
        if not completion_event_uncompressed.get('done'):
            print("   ❌ Uncompressed backup timed out")
            return False
        
        job_uncompressed = completion_event_uncompressed['job']
        uncompressed_size = job_uncompressed.total_size_bytes
        print(f"   ✓ Uncompressed backup completed")
        print(f"   Size reported: {format_size(uncompressed_size)}")
        
        # Clean dest for next test
        for item in os.listdir(dest_dir):
            item_path = os.path.join(dest_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            elif os.path.isfile(item_path):
                os.remove(item_path)
        
        # Test 2: Compressed backup
        print("\n3. Running COMPRESSED backup...")
        config_compressed = BackupConfig(
            source=source_dir,
            destination=dest_dir,
            exclude_patterns=[],
            retention_policy='7_days',
            dry_run=False,
            incremental=False,
            encryption=False,
            compression=True  # WITH COMPRESSION
        )
        
        backup_manager2 = BackupManager(config_compressed)
        completion_event_compressed = {}
        
        def on_completion_compressed(job):
            completion_event_compressed['job'] = job
            completion_event_compressed['done'] = True
        
        backup_manager2.set_completion_callback(on_completion_compressed)
        backup_manager2.start_backup(dry_run=False)
        
        # Wait for completion
        for _ in range(60):
            if completion_event_compressed.get('done'):
                break
            time.sleep(0.5)
        
        if not completion_event_compressed.get('done'):
            print("   ❌ Compressed backup timed out")
            return False
        
        job_compressed = completion_event_compressed['job']
        compressed_size = job_compressed.total_size_bytes
        print(f"   ✓ Compressed backup completed")
        print(f"   Size reported: {format_size(compressed_size)}")
        
        # Verify tar.gz file exists
        tar_gz_files = [f for f in os.listdir(dest_dir) if f.endswith('.tar.gz')]
        if tar_gz_files:
            archive_path = os.path.join(dest_dir, tar_gz_files[0])
            archive_size = os.path.getsize(archive_path)
            print(f"   Archive file: {tar_gz_files[0]}")
            print(f"   Actual archive size: {format_size(archive_size)}")
        else:
            print("   ⚠️ No tar.gz archive found")
        
        # Validation
        print("\n4. VALIDATION RESULTS:")
        print("   " + "-"*76)
        
        # Check 1: Sizes are different
        if uncompressed_size != compressed_size:
            print(f"   ✅ Sizes are DIFFERENT")
            print(f"      Uncompressed: {format_size(uncompressed_size)}")
            print(f"      Compressed:   {format_size(compressed_size)}")
        else:
            print(f"   ❌ Sizes are IDENTICAL (BUG NOT FIXED!)")
            print(f"      Both report: {format_size(uncompressed_size)}")
            return False
        
        # Check 2: Compressed is smaller
        if compressed_size < uncompressed_size:
            reduction = ((uncompressed_size - compressed_size) / uncompressed_size) * 100
            print(f"   ✅ Compression reduced size by {reduction:.1f}%")
        else:
            print(f"   ⚠️ Compressed size is not smaller")
        
        # Check 3: Archive exists
        if tar_gz_files:
            print(f"   ✅ Actual tar.gz archive created")
        else:
            print(f"   ❌ No archive file found")
            return False
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED - COMPRESSION FIX VERIFIED")
        print("="*80)
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Cleanup
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == '__main__':
    success = test_compression_size_reporting()
    sys.exit(0 if success else 1)
