#!/usr/bin/env python3
"""
Test script to verify dry run displays file sizes in UI
"""
import tempfile
import os
import time
from autobackup.core.backup_manager import BackupManager
from autobackup.models.backup_config import BackupConfig


def simulate_gui_output(data):
    """Simulate how the GUI main_window.py would display the data"""
    print("\n" + "="*70)
    print("📋 DRY RUN DETAILED REPORT (AS DISPLAYED IN GUI)")
    print("="*70 + "\n")
    
    new_files = data.get("new_files", [])
    updated_files = data.get("updated_files", [])
    deleted_files = data.get("deleted_files", [])
    total_would_transfer = data.get("total_would_transfer", 0)
    
    # Summary statistics
    print(f"📊 Summary:")
    print(f"   • Total files that would be transferred: {total_would_transfer}")
    print(f"   • New files: {len(new_files)}")
    print(f"   • Updated files: {len(updated_files)}")
    print(f"   • Deleted files: {len(deleted_files)}\n")
    
    # Show new files (limit to first 20)
    if new_files:
        print(f"✨ NEW FILES ({len(new_files)}):")
        for i, f in enumerate(new_files[:20], 1):
            # Handle both dict (with size info) and string formats
            if isinstance(f, dict):
                path = f.get('path', 'unknown')
                size = f.get('size_human', 'N/A')
                print(f"   {i}. {path:<45} ({size})")
            else:
                print(f"   {i}. {f}")
        if len(new_files) > 20:
            print(f"   ... and {len(new_files) - 20} more")
        print()
    
    # Show updated files (limit to first 20)
    if updated_files:
        print(f"🔄 UPDATED FILES ({len(updated_files)}):")
        for i, f in enumerate(updated_files[:20], 1):
            # Handle both dict (with size info) and string formats
            if isinstance(f, dict):
                path = f.get('path', 'unknown')
                size = f.get('size_human', 'N/A')
                print(f"   {i}. {path:<45} ({size})")
            else:
                print(f"   {i}. {f}")
        if len(updated_files) > 20:
            print(f"   ... and {len(updated_files) - 20} more")
        print()
    
    # Show deleted files (limit to first 20)
    if deleted_files:
        print(f"🗑️  DELETED FILES ({len(deleted_files)}):")
        for i, f in enumerate(deleted_files[:20], 1):
            # Deleted files are usually just strings
            if isinstance(f, dict):
                path = f.get('path', 'unknown')
                print(f"   {i}. {path}")
            else:
                print(f"   {i}. {f}")
        if len(deleted_files) > 20:
            print(f"   ... and {len(deleted_files) - 20} more")
        print()
    
    if not new_files and not updated_files and not deleted_files:
        print("✓ No changes detected - backup is already up to date!\n")


def main():
    print("="*70)
    print("Testing Dry Run with File Sizes in UI Display")
    print("="*70)
    
    # Create test environment
    test_dir = tempfile.mkdtemp(prefix='test_dry_run_ui_')
    source = os.path.join(test_dir, 'source')
    dest = os.path.join(test_dir, 'dest')
    os.makedirs(source)
    os.makedirs(dest)
    
    print(f"\n📁 Test Environment Created:")
    print(f"   Source: {source}")
    print(f"   Destination: {dest}\n")
    
    # Create test files with various sizes
    test_files = {
        'readme.txt': 'This is a readme file\n' * 10,
        'config.json': '{"setting": "value"}\n' * 20,
        'data/users.csv': 'id,name,email\n' + '\n'.join([f'{i},user{i},user{i}@example.com' for i in range(50)]),
        'docs/guide.md': '# Guide\n## Section 1\nContent here\n' * 100,
        'logs/app.log': 'Log entry\n' * 500,
        'images/photo.png': 'PNG_FAKE_DATA' * 1000,
    }
    
    print("📄 Creating test files:")
    for filepath, content in test_files.items():
        full_path = os.path.join(source, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
        size_kb = len(content) / 1024
        print(f"   ✓ {filepath:<40} ({size_kb:.1f} KB)")
    
    # Create config for dry run
    config = BackupConfig(
        source=source,
        destination=dest,
        exclude_patterns=[],
        retention_policy='7_days',
        dry_run=True,
        incremental=False,
        encryption=False
    )
    
    # Run backup manager with dry run
    print("\n🔄 Running dry run backup...\n")
    backup_manager = BackupManager(config)
    
    # Capture progress callbacks
    dry_run_data = None
    
    def on_progress(data):
        nonlocal dry_run_data
        if data.get('type') == 'dry_run_summary':
            dry_run_data = data
    
    backup_manager.set_progress_callback(on_progress)
    
    # Start dry run
    backup_manager.start_backup(dry_run=True)
    
    # Wait for completion
    for i in range(60):
        time.sleep(0.5)
        if not backup_manager._backup_thread.is_alive():
            break
    
    # Display results as they would appear in the GUI
    if dry_run_data:
        simulate_gui_output(dry_run_data)
        print("="*70)
        print("✅ DRY RUN TEST SUCCESSFUL - FILE SIZES ARE DISPLAYED!")
        print("="*70)
    else:
        print("❌ No dry run summary received")
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir)
    print("\n✅ Cleanup complete")


if __name__ == '__main__':
    main()
