#!/usr/bin/env python3
"""
Dry Run Demonstration Script

This script demonstrates how the dry run feature works in the backup application.
It simulates a backup operation and shows what would happen without making any changes.
"""

import subprocess
import re
import os
from typing import Dict, List, Any


class DryRunDemo:
    """Demonstrates dry run functionality with rsync"""
    
    def __init__(self, source: str, destination: str):
        self.source = source if source.endswith('/') else source + '/'
        self.destination = destination
    
    def execute_dry_run(self, exclude_patterns: List[str] = None) -> Dict[str, Any]:
        """
        Execute a dry run backup simulation
        
        Args:
            exclude_patterns: List of patterns to exclude
            
        Returns:
            Dictionary containing dry run results
        """
        exclude_patterns = exclude_patterns or []
        
        # Build rsync command
        cmd = [
            'rsync',
            '-aHv',  # Archive, preserve hard links, verbose
            '--dry-run',  # DRY RUN - no changes
            '--itemize-changes',  # Show detailed changes
            '--stats',  # Show statistics
            '--delete-excluded'  # Show what would be deleted
        ]
        
        # Add exclude patterns
        for pattern in exclude_patterns:
            cmd.extend(['--exclude', pattern])
        
        cmd.extend([self.source, self.destination])
        
        print("=" * 70)
        print("EXECUTING DRY RUN")
        print("=" * 70)
        print(f"Command: {' '.join(cmd)}")
        print("=" * 70)
        print()
        
        # Execute command
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True
            )
            
            output = result.stdout
            
            # Parse output
            parsed_results = self._parse_dry_run_output(output)
            
            # Display results
            self._display_results(parsed_results)
            
            return parsed_results
            
        except subprocess.CalledProcessError as e:
            print(f"Error executing rsync: {e}")
            print(f"Output: {e.output}")
            return {}
    
    def _parse_dry_run_output(self, output: str) -> Dict[str, Any]:
        """Parse rsync dry run output into structured data"""
        
        results = {
            'new_files': [],
            'updated_files': [],
            'deleted_files': [],
            'unchanged_files': [],
            'total_files': 0,
            'total_size': 0,
            'raw_output': output
        }
        
        # Parse itemize-changes lines
        # Format: >f+++++++++ file.txt or <f.st...... file.txt
        # First char: update type (< > c . *)
        # Second char: file type (f d L D S)
        # Rest: flags (can vary in length)
        itemize_pattern = re.compile(r'^([<>c\.\*][fdLDS]\S+)\s+(.+)$')
        
        for line in output.splitlines():
            # Parse itemized changes
            match = itemize_pattern.match(line)
            if match:
                flags = match.group(1)
                filepath = match.group(2)
                
                update_type = flags[0]
                file_type = flags[1]
                
                # Skip directories for cleaner output
                if file_type == 'd':
                    continue
                
                # Get file information
                file_info = self._get_file_info(filepath, flags)
                
                # Categorize the change
                if update_type == '>':
                    if '+' in flags:
                        results['new_files'].append(file_info)
                    else:
                        results['updated_files'].append(file_info)
                elif 'deleting' in line.lower() or update_type == '*':
                    results['deleted_files'].append(file_info)
                elif update_type == '.':
                    results['unchanged_files'].append(file_info)
        
        # Parse statistics
        stats_patterns = {
            'total_files': re.compile(r'Number of files:\s+([0-9,]+)'),
            'files_transferred': re.compile(r'Number of files transferred:\s+([0-9,]+)'),
            'total_size': re.compile(r'Total file size:\s+([0-9,\.]+)\s*(\w+)'),
        }
        
        for line in output.splitlines():
            for key, pattern in stats_patterns.items():
                match = pattern.search(line)
                if match:
                    if key == 'total_size':
                        size_value = float(match.group(1).replace(',', ''))
                        size_unit = match.group(2)
                        results[key] = f"{size_value} {size_unit}"
                    else:
                        results[key] = int(match.group(1).replace(',', ''))
        
        return results
    
    def _get_file_info(self, filepath: str, flags: str) -> Dict[str, Any]:
        """Get detailed information about a file"""
        full_path = os.path.join(self.source, filepath)
        
        info = {
            'path': filepath,
            'size_bytes': 0,
            'size_human': '0 B',
            'change_type': self._decode_flags(flags)
        }
        
        # Get file size if it exists
        if os.path.exists(full_path) and os.path.isfile(full_path):
            size_bytes = os.path.getsize(full_path)
            info['size_bytes'] = size_bytes
            info['size_human'] = self._format_size(size_bytes)
        
        return info
    
    def _decode_flags(self, flags: str) -> str:
        """Decode rsync itemize flags into human-readable description"""
        update_type = flags[0]
        
        if '+' in flags:
            return 'New file (would be created)'
        elif update_type == '>':
            changes = []
            if flags[2] == 'c':
                changes.append('checksum')
            if flags[3] == 's':
                changes.append('size')
            if flags[4] == 't':
                changes.append('timestamp')
            
            if changes:
                return f"Updated ({', '.join(changes)} changed)"
            else:
                return 'Updated'
        elif 'deleting' in flags.lower() or update_type == '*':
            return 'Would be deleted'
        elif update_type == '.':
            return 'Already up-to-date'
        else:
            return 'Unknown change'
    
    def _format_size(self, bytes_size: int) -> str:
        """Convert bytes to human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} PB"
    
    def _display_results(self, results: Dict[str, Any]):
        """Display formatted dry run results"""
        
        print("\n")
        print("=" * 70)
        print("           DRY RUN SIMULATION REPORT")
        print("=" * 70)
        print()
        
        # Summary
        print("📊 SUMMARY")
        print("-" * 70)
        total_files = results.get('total_files', 0)
        total_size = results.get('total_size', 'Unknown')
        print(f"Total Files Analyzed:     {total_files:,}")
        print(f"Total Size:               {total_size}")
        
        total_changes = len(results['new_files']) + len(results['updated_files']) + len(results['deleted_files'])
        print(f"Would Transfer:           {total_changes} files")
        print()
        
        # New files
        new_files = results['new_files']
        if new_files:
            print("=" * 70)
            print(f"✅ NEW FILES ({len(new_files)} files)")
            print("   These files would be CREATED in the backup:")
            print()
            for file_info in new_files[:15]:  # Show first 15
                print(f"   • {file_info['path']:<50} ({file_info['size_human']})")
            if len(new_files) > 15:
                print(f"   ... and {len(new_files) - 15} more files")
            print()
        
        # Updated files
        updated_files = results['updated_files']
        if updated_files:
            print("-" * 70)
            print(f"🔄 UPDATED FILES ({len(updated_files)} files)")
            print("   These files would be OVERWRITTEN (newer version):")
            print()
            for file_info in updated_files[:15]:
                print(f"   • {file_info['path']:<50} ({file_info['size_human']})")
                print(f"     └─ {file_info['change_type']}")
            if len(updated_files) > 15:
                print(f"   ... and {len(updated_files) - 15} more files")
            print()
        
        # Deleted files
        deleted_files = results['deleted_files']
        if deleted_files:
            print("-" * 70)
            print(f"🗑️  DELETED FILES ({len(deleted_files)} files)")
            print("   These files would be REMOVED from backup:")
            print()
            for file_info in deleted_files[:15]:
                path = file_info['path'] if isinstance(file_info, dict) else file_info
                print(f"   • {path}")
            if len(deleted_files) > 15:
                print(f"   ... and {len(deleted_files) - 15} more files")
            print()
        
        # Already up-to-date
        unchanged_count = results.get('total_files', 0) - total_changes
        if unchanged_count > 0:
            print("-" * 70)
            print(f"⏭️  SKIPPED FILES ({unchanged_count} files)")
            print("   These files are already up-to-date")
            print("   No action needed (unchanged)")
            print()
        
        # Warning
        print("=" * 70)
        print("⚠️  NO CHANGES HAVE BEEN MADE")
        print("   This was a simulation only.")
        print("   Run a real backup to apply these changes.")
        print("=" * 70)
        print()


def create_test_environment():
    """Create a test environment to demonstrate dry run"""
    import tempfile
    import shutil
    
    # Create temporary directories
    test_dir = tempfile.mkdtemp(prefix='dryrun_test_')
    source_dir = os.path.join(test_dir, 'source')
    dest_dir = os.path.join(test_dir, 'destination')
    
    os.makedirs(source_dir)
    os.makedirs(dest_dir)
    
    print(f"Created test environment at: {test_dir}")
    print(f"Source: {source_dir}")
    print(f"Destination: {dest_dir}")
    print()
    
    # Create some test files
    test_files = {
        'document1.txt': 'This is document 1',
        'document2.txt': 'This is document 2',
        'config.json': '{"setting": "value"}',
        'data.csv': 'col1,col2,col3\n1,2,3\n4,5,6',
        'subfolder/file1.txt': 'Nested file 1',
        'subfolder/file2.txt': 'Nested file 2',
    }
    
    for filepath, content in test_files.items():
        full_path = os.path.join(source_dir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
    
    print(f"Created {len(test_files)} test files in source directory")
    print()
    
    return test_dir, source_dir, dest_dir


def main():
    """Main demonstration function"""
    
    print("=" * 70)
    print("         DRY RUN FEATURE DEMONSTRATION")
    print("=" * 70)
    print()
    print("This script demonstrates the dry run feature without making any")
    print("actual changes to your files.")
    print()
    
    # Create test environment
    test_dir, source_dir, dest_dir = create_test_environment()
    
    try:
        # Initialize dry run demo
        demo = DryRunDemo(source_dir, dest_dir)
        
        # Execute dry run
        print("Starting dry run simulation...")
        print()
        
        results = demo.execute_dry_run(exclude_patterns=['*.tmp', '.git'])
        
        # Verify no files were created
        print("\n")
        print("Verification:")
        print("-" * 70)
        dest_files = os.listdir(dest_dir)
        if not dest_files:
            print("✅ Confirmed: Destination directory is empty")
            print("✅ No files were created or modified")
        else:
            print(f"⚠️  Warning: Found {len(dest_files)} files in destination")
        print()
        
    finally:
        # Cleanup
        print(f"Cleaning up test environment: {test_dir}")
        import shutil
        shutil.rmtree(test_dir)
        print("✅ Cleanup complete")


if __name__ == '__main__':
    main()
