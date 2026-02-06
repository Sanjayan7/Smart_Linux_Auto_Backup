# Dry Run Quick Reference Guide

## TL;DR - Quick Command

```bash
rsync -aHv --dry-run --itemize-changes --stats --delete /source/ /destination/
```

This command:
- ✅ Simulates the backup
- ✅ Shows all changes
- ✅ Doesn't modify anything
- ✅ Safe to run anytime

---

## Reading the Output

### Itemize Codes

| Code | Meaning | Action |
|------|---------|--------|
| `>f+++++++++` | New file | Would be **CREATED** |
| `>f.st......` | Modified file | Would be **UPDATED** |
| `*deleting` | Deleted file | Would be **REMOVED** |
| `.f........` | Unchanged | **SKIP** (already backed up) |

### Example Output Interpretation

```bash
*deleting   old_file.txt          # ❌ Would delete from backup
>f+++++++++ new_document.pdf      # ✅ Would create new file
>f.st...... config.json           # 🔄 Would update (size/time changed)
.f......... photo.jpg             # ⏭️  Skip (unchanged)
```

---

## Common Dry Run Commands

### 1. Basic Dry Run
```bash
rsync -aHv --dry-run /source/ /destination/
```

### 2. Dry Run with Detailed Changes
```bash
rsync -aHv --dry-run --itemize-changes /source/ /destination/
```

### 3. Dry Run with Statistics
```bash
rsync -aHv --dry-run --itemize-changes --stats /source/ /destination/
```

### 4. Dry Run with Exclusions
```bash
rsync -aHv --dry-run --itemize-changes \
  --exclude='*.tmp' \
  --exclude='.git' \
  --exclude='node_modules/' \
  /source/ /destination/
```

### 5. Dry Run with Deletions Shown
```bash
rsync -aHv --dry-run --itemize-changes --delete /source/ /destination/
```

### 6. Dry Run Incremental (with link-dest)
```bash
rsync -aHv --dry-run --itemize-changes \
  --link-dest=/backups/previous/ \
  /source/ /destination/current/
```

---

## Python API Usage

### Your Current Implementation

```python
from autobackup.core.rsync_engine import RsyncEngine

# Initialize engine
engine = RsyncEngine()

# Run dry run
stats = engine.run_rsync(
    source='/path/to/source',
    destination='/path/to/backup',
    exclude_patterns=['*.tmp', '.git'],
    dry_run=True,  # ← Enable dry run
    progress_callback=callback_function
)

# Access results
dry_run_details = stats.get('dry_run_details', {})
new_files = dry_run_details.get('new_files', [])
updated_files = dry_run_details.get('updated_files', [])
deleted_files = dry_run_details.get('deleted_files', [])

print(f"Would create: {len(new_files)} files")
print(f"Would update: {len(updated_files)} files")
print(f"Would delete: {len(deleted_files)} files")
```

---

## Testing Dry Run

### Verify It's Actually Dry

```bash
# Before dry run
ls -la /destination/

# Run dry run
rsync -aHv --dry-run --itemize-changes /source/ /destination/

# After dry run (should be identical to before)
ls -la /destination/

# Compare timestamps - they should be unchanged
stat /destination/file.txt
```

### Create Test Scenario

```bash
# 1. Create test directories
mkdir -p /tmp/test_source
mkdir -p /tmp/test_dest

# 2. Add files
echo "original" > /tmp/test_source/file1.txt
echo "data" > /tmp/test_source/file2.txt

# 3. Initial backup
rsync -aH /tmp/test_source/ /tmp/test_dest/

# 4. Make changes
echo "modified" > /tmp/test_source/file1.txt
echo "new" > /tmp/test_source/file3.txt
rm /tmp/test_source/file2.txt

# 5. DRY RUN - see what would happen
rsync -aHv --dry-run --itemize-changes --delete /tmp/test_source/ /tmp/test_dest/

# ✅ Expected output:
# >f.st...... file1.txt    (would update)
# >f+++++++++ file3.txt    (would create)
# *deleting   file2.txt    (would delete)

# 6. Verify nothing changed
cat /tmp/test_dest/file1.txt  # Should still say "original"
ls /tmp/test_dest/file3.txt   # Should not exist
ls /tmp/test_dest/file2.txt   # Should still exist
```

---

## Itemize Flags Reference

The itemize format is: **YXcstpoguax**

### Position Meanings

| Pos | Symbol | Meaning |
|-----|--------|---------|
| 0 | `>` | Sent to destination |
| | `<` | Received from destination |
| | `*` | Message (deletion, etc.) |
| | `.` | No change |
| 1 | `f` | Regular file |
| | `d` | Directory |
| | `L` | Symlink |
| | `D` | Device |
| 2 | `c` | Checksum differs |
| 3 | `s` | Size differs |
| 4 | `t` | Time differs |
| 5 | `p` | Permissions differ |
| 6 | `o` | Owner differs |
| 7 | `g` | Group differs |

### Common Combinations

```
>f+++++++++  → New file (all attributes new)
>f.st......  → File modified (size and time changed)
>f..t......  → Timestamp only changed
>fcs.......  → Checksum and size changed
.f.........  → File unchanged (skip)
*deleting    → File would be deleted
cd+++++++++  → Local checksum change (new file)
```

---

## Safety Checklist

Before running a real backup, use dry run to verify:

- [ ] Source path is correct
- [ ] Destination path is correct
- [ ] Exclude patterns work as expected
- [ ] No unexpected deletions
- [ ] File count is reasonable
- [ ] Transfer size is reasonable
- [ ] No permission errors

---

## Dry Run Workflow

```
┌─────────────────────┐
│  User clicks        │
│  "Preview Backup"   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Run rsync with     │
│  --dry-run flag     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Parse output       │
│  Show in GUI        │
└──────────┬──────────┘
           │
           ▼
    ┌─────────┴─────────┐
    │                   │
    ▼                   ▼
┌─────────┐      ┌──────────┐
│ Approve │      │  Cancel  │
└────┬────┘      └──────────┘
     │
     ▼
┌─────────────────────┐
│  Run REAL backup    │
│  (no --dry-run)     │
└─────────────────────┘
```

---

## Performance Notes

- Dry run is **FAST** (no data transfer)
- Only reads metadata (file list, sizes, timestamps)
- Safe to run frequently
- No disk space used
- No network bandwidth used (for remote syncs)

**Typical dry run speed**: Analyzes 10,000 files in < 5 seconds

---

## Troubleshooting

### "Nothing shows up in dry run"

Check:
1. Source path has trailing slash: `/source/` ✅ not `/source`
2. Destination path is correct
3. Files actually exist in source
4. No excessive exclude patterns

### "Shows too many changes"

Likely causes:
- Destination is empty (first backup)
- Different file permissions
- Cross-filesystem backup (different timestamps)

### "Shows deletions I don't expect"

- Add `--delete-excluded` flag to see why
- Check exclude patterns
- Verify source path is correct

---

## Best Practices

1. **Always dry run first** before real backups
2. **Review the output** before proceeding
3. **Test exclude patterns** with dry run
4. **Monitor file counts** for anomalies
5. **Document expected changes** for auditing

---

## Integration with GUI

### Suggested UI Flow

```
┌────────────────────────────────────┐
│  Backup Configuration              │
│                                    │
│  Source:      /home/user/docs      │
│  Destination: /backup/docs         │
│                                    │
│  [Preview Backup] [Start Backup]   │
└────────────────────────────────────┘
           │
           ▼ (User clicks Preview)
┌────────────────────────────────────┐
│  Dry Run Results                   │
│  ───────────────────────────────   │
│  ✅ 5 new files (2.3 MB)           │
│  🔄 3 updated files (1.1 MB)       │
│  🗑️ 1 deleted file                 │
│  ⏭️ 142 unchanged files             │
│                                    │
│  [View Details] [Proceed] [Cancel] │
└────────────────────────────────────┘
```

---

## Quick Reference Card

| Task | Command |
|------|---------|
| Basic dry run | `rsync -aHv --dry-run /src/ /dst/` |
| With details | `rsync -aHv --dry-run --itemize-changes /src/ /dst/` |
| With stats | `rsync -aHv --dry-run --itemize-changes --stats /src/ /dst/` |
| Show deletions | `rsync -aHv --dry-run --delete /src/ /dst/` |
| Exclude files | `rsync -aHv --dry-run --exclude='*.tmp' /src/ /dst/` |

---

## Remember

> **Dry run NEVER modifies files**
> 
> It's like a weather forecast - shows what WOULD happen,
> but doesn't make the weather happen.

Safe to run as many times as you want! 🚀
