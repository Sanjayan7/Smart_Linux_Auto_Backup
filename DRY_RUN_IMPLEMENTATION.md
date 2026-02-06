# Dry Run Feature Implementation Guide

## Overview
A dry run simulates a backup operation without actually copying, modifying, or deleting any files. It shows exactly what **would** happen if the backup were executed for real.

---

## 1. Logic Explanation

### How It Works

The dry run feature uses **rsync's `--dry-run` flag** combined with **`--itemize-changes`** to simulate the backup process:

```
rsync -aHv --info=progress2 --stats --dry-run --itemize-changes [OPTIONS] SOURCE DEST
```

#### Key Components:

1. **`--dry-run`**: Performs trial run without making changes
2. **`--itemize-changes`**: Provides detailed output showing what would change
3. **`--stats`**: Shows summary statistics
4. **`--delete-excluded`**: Shows which files would be deleted based on exclude patterns

#### Flow:
```
┌─────────────────┐
│  Start Dry Run  │
└────────┬────────┘
         │
         ▼
┌──────────────────────────┐
│ Execute rsync with       │
│ --dry-run --itemize      │
└────────┬─────────────────┘
         │
         ▼
┌──────────────────────────┐
│ Parse itemize output     │
│ Categorize files:        │
│  • New files (>f+++)     │
│  • Updated files (>f.st) │
│  • Deleted files (*)     │
└────────┬─────────────────┘
         │
         ▼
┌──────────────────────────┐
│ Generate human-readable  │
│ report for GUI           │
└──────────────────────────┘
```

---

## 2. Rsync Command & Approach

### Full Command Structure

```bash
rsync -aHv \
  --info=progress2 \
  --stats \
  --dry-run \
  --itemize-changes \
  --delete-excluded \
  --exclude='*.tmp' \
  --exclude='cache/' \
  /path/to/source/ \
  /path/to/destination/
```

### Flag Breakdown

| Flag | Purpose |
|------|---------|
| `-a` | Archive mode (preserves permissions, timestamps, etc.) |
| `-H` | Preserve hard links |
| `-v` | Verbose output |
| `--info=progress2` | Show overall progress |
| `--stats` | Display transfer statistics |
| `--dry-run` | **Simulate without making changes** |
| `--itemize-changes` | **Show detailed change information** |
| `--delete-excluded` | Show files that would be deleted |

### Itemize Changes Format

Rsync outputs lines in this format:
```
YXcstpoguax path/to/file
```

Where:
- **Y** = Update type (`>`, `<`, `*`, `.`, `c`)
- **X** = File type (`f`=file, `d`=directory, `L`=symlink)
- **c** = Checksum differs (`.` or `c`)
- **s** = Size differs (`.` or `s`)
- **t** = Time differs (`.` or `t`)

#### Common Patterns:

```
>f+++++++++ file.txt       → New file would be created
>f.st...... file.txt       → File would be updated (size/time changed)
*deleting   old.txt        → File would be deleted
.d..t...... folder/        → Directory timestamp would change
cd+++++++++ file.txt       → Checksum change (new file locally)
```

---

## 3. Sample Output Format

### 3.1 Terminal/Log Output (Raw Rsync)

```
===============================================
         DRY RUN - NO FILES MODIFIED
===============================================

Scanning source directory...
Building file list... done

Changes that would occur:
--------------------------
>f+++++++++ documents/report.pdf
>f+++++++++ documents/presentation.pptx
>f.st...... config/settings.json
>f.st...... src/main.py
*deleting   old_backup.zip
cd..t...... README.md

Number of files: 1,247 (reg: 1,125, dir: 122)
Number of created files: 2
Number of deleted files: 1
Number of regular files transferred: 5
Total file size: 4.52 GB
Total transferred file size: 245.67 MB
Literal data: 0 bytes
Matched data: 0 bytes
File list size: 0
Speedup: 0.00 (DRY RUN)
```

### 3.2 Human-Readable GUI Format

```
═══════════════════════════════════════════════
           DRY RUN SIMULATION REPORT
═══════════════════════════════════════════════

📊 SUMMARY
──────────────────────────────────────────────
Total Files Analyzed:     1,247 files
Total Size:               4.52 GB
Would Transfer:           5 files (245.67 MB)
Duration:                 ~2.3 seconds

═══════════════════════════════════════════════

📁 FILE OPERATIONS BREAKDOWN
──────────────────────────────────────────────

✅ NEW FILES (2 files)
   These files would be CREATED in the backup:
   
   • documents/report.pdf                (2.5 MB)
   • documents/presentation.pptx         (15.3 MB)

──────────────────────────────────────────────

🔄 UPDATED FILES (3 files)
   These files would be OVERWRITTEN (newer version):
   
   • config/settings.json                (4.2 KB)
     Reason: Modified time changed
     
   • src/main.py                         (18.7 KB)
     Reason: Content and size changed
     
   • README.md                           (1.2 KB)
     Reason: Checksum changed

──────────────────────────────────────────────

🗑️  DELETED FILES (1 file)
   These files would be REMOVED from backup:
   
   • old_backup.zip                      (220.5 MB)
     Reason: No longer exists in source

──────────────────────────────────────────────

⏭️  SKIPPED FILES (1,241 files)
   These files are already up-to-date
   No action needed (unchanged)

═══════════════════════════════════════════════

⚠️  NO CHANGES HAVE BEEN MADE
   This was a simulation only.
   Run a real backup to apply these changes.

═══════════════════════════════════════════════
```

### 3.3 JSON Format (for GUI consumption)

```json
{
  "dry_run": true,
  "status": "completed",
  "timestamp": "2026-02-04T20:03:01+05:30",
  "summary": {
    "total_files": 1247,
    "total_size_bytes": 4852695040,
    "would_transfer_count": 5,
    "would_transfer_bytes": 257586176,
    "duration_seconds": 2.3
  },
  "operations": {
    "new_files": [
      {
        "path": "documents/report.pdf",
        "size_bytes": 2621440,
        "size_human": "2.5 MB"
      },
      {
        "path": "documents/presentation.pptx",
        "size_bytes": 16039936,
        "size_human": "15.3 MB"
      }
    ],
    "updated_files": [
      {
        "path": "config/settings.json",
        "size_bytes": 4200,
        "size_human": "4.2 KB",
        "change_reason": "Modified time changed"
      },
      {
        "path": "src/main.py",
        "size_bytes": 19149,
        "size_human": "18.7 KB",
        "change_reason": "Content and size changed"
      },
      {
        "path": "README.md",
        "size_bytes": 1200,
        "size_human": "1.2 KB",
        "change_reason": "Checksum changed"
      }
    ],
    "deleted_files": [
      {
        "path": "old_backup.zip",
        "size_bytes": 231276800,
        "size_human": "220.5 MB",
        "reason": "No longer exists in source"
      }
    ],
    "unchanged_files": 1241
  },
  "warnings": [
    "This was a simulation. No files were modified."
  ]
}
```

---

## 4. Implementation in Your Application

Your current implementation already has most of this functionality! Here's what you have:

### ✅ Already Implemented:

1. **Rsync Engine** (`rsync_engine.py`):
   - `--dry-run` flag support
   - `--itemize-changes` parsing
   - `_parse_itemize_changes()` method that categorizes files

2. **Backup Manager** (`backup_manager.py`):
   - Dry run mode toggle
   - Progress callbacks for UI updates
   - Sends `dry_run_summary` to UI with categorized files

### 🔧 Recommended Enhancements:

#### Enhancement 1: Add File Size Information

Currently, your `_parse_itemize_changes()` only tracks file paths. Add size information:

```python
def _parse_itemize_changes_enhanced(self, output: str, source_dir: str) -> Dict[str, Any]:
    """Enhanced version with file sizes"""
    details = {
        'new_files': [],
        'updated_files': [],
        'unchanged_files': [],
        'deleted_files': [],
        'total_would_transfer': 0,
        'total_would_transfer_bytes': 0
    }
    
    itemize_pattern = re.compile(r'^([<>c\.*][fdLDS][c\.][s\.][t\.][p\.][o\.][g\.][u\.][a\.][x\.])\s+(.+)$')
    
    for line in output.splitlines():
        match = itemize_pattern.match(line)
        if match:
            flags = match.group(1)
            filepath = match.group(2)
            update_type = flags[0]
            file_type = flags[1]
            
            if file_type == 'd':
                continue
            
            # Get file size from source
            full_path = os.path.join(source_dir, filepath)
            file_size = 0
            if os.path.exists(full_path) and os.path.isfile(full_path):
                file_size = os.path.getsize(full_path)
            
            file_info = {
                'path': filepath,
                'size_bytes': file_size,
                'size_human': self._format_size(file_size)
            }
            
            if update_type == '>':
                if '+' in flags:
                    details['new_files'].append(file_info)
                    details['total_would_transfer'] += 1
                    details['total_would_transfer_bytes'] += file_size
                else:
                    details['updated_files'].append(file_info)
                    details['total_would_transfer'] += 1
                    details['total_would_transfer_bytes'] += file_size
            # ... rest of logic
    
    return details
```

#### Enhancement 2: Format Size Helper

```python
def _format_size(self, bytes_size: int) -> str:
    """Convert bytes to human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"
```

#### Enhancement 3: Generate Formatted Report

```python
def generate_dry_run_report(self, dry_run_details: Dict[str, Any]) -> str:
    """Generate human-readable dry run report for GUI"""
    lines = []
    lines.append("=" * 60)
    lines.append("           DRY RUN SIMULATION REPORT")
    lines.append("=" * 60)
    lines.append("")
    
    lines.append("📊 SUMMARY")
    lines.append("-" * 60)
    lines.append(f"Would Transfer:  {dry_run_details['total_would_transfer']} files")
    
    total_bytes = dry_run_details.get('total_would_transfer_bytes', 0)
    lines.append(f"Transfer Size:   {self._format_size(total_bytes)}")
    lines.append("")
    
    # New files
    new_files = dry_run_details.get('new_files', [])
    if new_files:
        lines.append("")
        lines.append(f"✅ NEW FILES ({len(new_files)} files)")
        lines.append("   These files would be CREATED in the backup:")
        lines.append("")
        for f in new_files[:10]:  # Limit to first 10
            lines.append(f"   • {f['path']:<50} ({f['size_human']})")
        if len(new_files) > 10:
            lines.append(f"   ... and {len(new_files) - 10} more")
    
    # Updated files
    updated_files = dry_run_details.get('updated_files', [])
    if updated_files:
        lines.append("")
        lines.append(f"🔄 UPDATED FILES ({len(updated_files)} files)")
        lines.append("   These files would be OVERWRITTEN:")
        lines.append("")
        for f in updated_files[:10]:
            lines.append(f"   • {f['path']:<50} ({f['size_human']})")
        if len(updated_files) > 10:
            lines.append(f"   ... and {len(updated_files) - 10} more")
    
    # Deleted files
    deleted_files = dry_run_details.get('deleted_files', [])
    if deleted_files:
        lines.append("")
        lines.append(f"🗑️  DELETED FILES ({len(deleted_files)} files)")
        lines.append("   These files would be REMOVED:")
        lines.append("")
        for f in deleted_files[:10]:
            lines.append(f"   • {f}")
        if len(deleted_files) > 10:
            lines.append(f"   ... and {len(deleted_files) - 10} more")
    
    lines.append("")
    lines.append("=" * 60)
    lines.append("⚠️  NO CHANGES HAVE BEEN MADE")
    lines.append("   This was a simulation only.")
    lines.append("=" * 60)
    
    return "\n".join(lines)
```

---

## 5. Testing the Dry Run

### Test Case 1: Basic Dry Run

```bash
# Create test directories
mkdir -p /tmp/test_source
mkdir -p /tmp/test_dest

# Add some files
echo "content1" > /tmp/test_source/file1.txt
echo "content2" > /tmp/test_source/file2.txt

# Run dry run
rsync -aHv --dry-run --itemize-changes /tmp/test_source/ /tmp/test_dest/

# Verify no files were created
ls /tmp/test_dest/  # Should be empty
```

### Test Case 2: Incremental Changes

```bash
# Initial backup
rsync -aH /tmp/test_source/ /tmp/test_dest/

# Modify source
echo "new content" > /tmp/test_source/file1.txt
echo "content3" > /tmp/test_source/file3.txt

# Dry run to see changes
rsync -aHv --dry-run --itemize-changes /tmp/test_source/ /tmp/test_dest/

# Expected output:
# >f.st...... file1.txt   (updated)
# >f+++++++++ file3.txt   (new)
```

---

## 6. GUI Integration

Your GUI should display the dry run results in a clear, organized manner:

### Recommended Layout:

```
┌─────────────────────────────────────────┐
│        DRY RUN RESULTS                  │
├─────────────────────────────────────────┤
│                                         │
│  Summary:                               │
│  ✓ 5 files would be transferred         │
│  ✓ 245.67 MB would be copied            │
│  ✓ 1,241 files already up-to-date       │
│                                         │
│  [Tab: New Files (2)]                   │
│  [Tab: Updated Files (3)]               │
│  [Tab: Deleted Files (1)]               │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │ • documents/report.pdf    2.5 MB  │  │
│  │ • documents/presentation  15.3 MB │  │
│  └───────────────────────────────────┘  │
│                                         │
│  [Proceed with Backup] [Cancel]         │
│                                         │
└─────────────────────────────────────────┘
```

---

## 7. Key Safety Features

✅ **No data modification**: Files are never touched
✅ **Preview before action**: User sees exact changes
✅ **Reversibility check**: User knows what will be deleted
✅ **Size validation**: User can verify disk space requirements
✅ **Clear warnings**: Clearly marked as simulation

---

## Conclusion

Your implementation is already quite robust! The main enhancements would be:

1. ✅ Add file size information to dry run results
2. ✅ Create human-readable formatted reports
3. ✅ Implement GUI display with categorized tabs
4. ✅ Add "Proceed" button after dry run review

The rsync `--dry-run` + `--itemize-changes` approach is the industry standard and works perfectly for this use case.
