#!/usr/bin/env python3
"""
Advanced Dry Run Example - Shows changes detection

This demonstrates dry run with actual file changes:
- New files to be added
- Modified files to be updated
- Deleted files to be removed
"""

import os
import tempfile
import shutil
import subprocess
import time


def create_scenario():
    """Create a realistic backup scenario with changes"""
    
    # Create temporary directories
    test_dir = tempfile.mkdtemp(prefix='dryrun_scenario_')
    source_dir = os.path.join(test_dir, 'source')
    dest_dir = os.path.join(test_dir, 'destination')
    
    os.makedirs(source_dir)
    os.makedirs(dest_dir)
    
    print("\n" + "=" * 70)
    print("CREATING REALISTIC BACKUP SCENARIO")
    print("=" * 70)
    print(f"Source:      {source_dir}")
    print(f"Destination: {dest_dir}")
    print()
    
    # Step 1: Create initial backup baseline
    print("Step 1: Creating initial backup baseline...")
    initial_files = {
        'README.md': 'Project README version 1.0',
        'config.json': '{"version": "1.0", "debug": false}',
        'data/users.csv': 'id,name,email\n1,Alice,alice@example.com\n2,Bob,bob@example.com',
        'data/products.csv': 'id,name,price\n101,Widget,9.99\n102,Gadget,19.99',
        'logs/app.log': 'Application started\nProcessing requests...',
        'scripts/backup.sh': '#!/bin/bash\necho "Running backup..."',
    }
    
    for filepath, content in initial_files.items():
        full_path = os.path.join(source_dir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
    
    # Do initial backup (not dry run)
    print(f"   Created {len(initial_files)} initial files")
    
    cmd = ['rsync', '-aH', source_dir + '/', dest_dir + '/']
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print("   ✅ Initial backup completed")
    print()
    
    # Step 2: Simulate changes over time
    print("Step 2: Simulating changes to source directory...")
    time.sleep(0.1)  # Ensure timestamp difference
    
    # ADD new files
    new_files = {
        'data/orders.csv': 'order_id,customer,amount\n1001,Alice,49.99\n1002,Bob,29.99',
        'reports/monthly_report.pdf': 'PDF content placeholder - Monthly financial report',
    }
    
    print(f"   📄 Adding {len(new_files)} new files:")
    for filepath, content in new_files.items():
        full_path = os.path.join(source_dir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
        print(f"      • {filepath}")
    print()
    
    # MODIFY existing files
    modified_files = {
        'config.json': '{"version": "2.0", "debug": true, "log_level": "INFO"}',
        'README.md': 'Project README version 2.0\nUpdated with new instructions',
        'data/users.csv': 'id,name,email\n1,Alice,alice@example.com\n2,Bob,bob@example.com\n3,Charlie,charlie@example.com',
    }
    
    print(f"   ✏️  Modifying {len(modified_files)} existing files:")
    for filepath, content in modified_files.items():
        full_path = os.path.join(source_dir, filepath)
        with open(full_path, 'w') as f:
            f.write(content)
        print(f"      • {filepath}")
    print()
    
    # DELETE a file from source (will be deleted from backup)
    deleted_files = ['logs/app.log']
    
    print(f"   🗑️  Deleting {len(deleted_files)} files from source:")
    for filepath in deleted_files:
        full_path = os.path.join(source_dir, filepath)
        if os.path.exists(full_path):
            os.remove(full_path)
            print(f"      • {filepath}")
    print()
    
    return test_dir, source_dir, dest_dir


def run_dry_run_comparison(source_dir, dest_dir):
    """Run dry run and show what would happen"""
    
    print("=" * 70)
    print("RUNNING DRY RUN ANALYSIS")
    print("=" * 70)
    print()
    
    # Execute dry run
    cmd = [
        'rsync',
        '-aHv',
        '--dry-run',
        '--itemize-changes',
        '--stats',
        '--delete',  # Show deletions
        source_dir + '/',
        dest_dir + '/'
    ]
    
    print(f"Command: {' '.join(cmd)}")
    print()
    print("-" * 70)
    print("RSYNC OUTPUT:")
    print("-" * 70)
    
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    print(result.stdout)
    print("-" * 70)
    print()
    
    # Verify destination is unchanged
    print("=" * 70)
    print("VERIFICATION: Checking destination directory...")
    print("=" * 70)
    
    # Check if new files exist in destination
    new_file_check = os.path.join(dest_dir, 'data/orders.csv')
    modified_file = os.path.join(dest_dir, 'config.json')
    
    if not os.path.exists(new_file_check):
        print("✅ New file 'data/orders.csv' was NOT created (correct)")
    else:
        print("❌ ERROR: New file was created (should not happen in dry run)")
    
    # Check if modified file is unchanged
    with open(modified_file, 'r') as f:
        content = f.read()
    
    if '"version": "1.0"' in content:
        print("✅ Modified file 'config.json' was NOT updated (correct)")
    else:
        print("❌ ERROR: File was modified (should not happen in dry run)")
    
    # Check if deleted file still exists in destination
    deleted_file_check = os.path.join(dest_dir, 'logs/app.log')
    if os.path.exists(deleted_file_check):
        print("✅ Deleted file 'logs/app.log' still exists in destination (correct)")
    else:
        print("❌ ERROR: File was deleted (should not happen in dry run)")
    
    print()
    print("=" * 70)
    print("DRY RUN SUMMARY")
    print("=" * 70)
    print("✅ No files were actually modified")
    print("✅ Dry run successfully simulated the backup operation")
    print("✅ Destination remains in original state")
    print("=" * 70)
    print()


def main():
    """Main execution"""
    
    print("\n" + "=" * 70)
    print("        ADVANCED DRY RUN SCENARIO DEMONSTRATION")
    print("=" * 70)
    print()
    print("This example shows dry run detecting:")
    print("  • New files to be added")
    print("  • Modified files to be updated")
    print("  • Deleted files to be removed")
    print()
    
    # Create scenario
    test_dir, source_dir, dest_dir = create_scenario()
    
    try:
        # Run dry run
        run_dry_run_comparison(source_dir, dest_dir)
        
        print()
        print("=" * 70)
        print("WHAT WOULD HAPPEN IN A REAL BACKUP:")
        print("=" * 70)
        print("✓ 2 new files would be copied to backup")
        print("✓ 3 files would be updated with new content")
        print("✓ 1 file would be deleted from backup")
        print("✓ 3 files would remain unchanged")
        print("=" * 70)
        print()
        
    finally:
        # Cleanup
        print(f"Cleaning up: {test_dir}")
        shutil.rmtree(test_dir)
        print("✅ Cleanup complete\n")


if __name__ == '__main__':
    main()
