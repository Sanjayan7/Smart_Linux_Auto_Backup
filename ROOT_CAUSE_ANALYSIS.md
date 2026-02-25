# ROOT CAUSE ANALYSIS: Dry Run Size = 0.00 MB Bug

## Executive Summary
The dry run shows 0.00 MB despite having files listed because:
1. `job.total_size_bytes` is set from `rsync_stats.get("total_file_size", 0)` (line 120 backup_manager.py)
2. This value often remains 0 because rsync's "Total file size" only applies to files that **would be transferred**
3. In dry-run mode, rsync doesn't list individual file sizes in certain configurations
4. No fallback mechanism exists to calculate size from the actual file list

## Evidence

### Current Code Flow
```
backup_manager.py (line 120):
    job.total_size_bytes = rsync_stats.get("total_file_size", 0)
                                                              ^ DEFAULT 0!
     ↓
rsync_engine.py (lines 125-162):
    Parses "Total file size:" from rsync output
     ↓
If the regex doesn't match (or field is missing):
    summary["total_file_size"] = 0  (initialized at line 125)
     ↓
UI displays:
    Size: 0.00 MB (estimated)  ← PROBLEM!
```

### Why the Value is 0

1. **Initial Value**: `summary["total_file_size"] = 0` (line 125)
2. **Parsing Failure**: The regex `r"Total file size: ([\d,\.]+)\s*(.B|K.B|M.B|G.B|T.B)"` may:
   - Not match rsync output if format is different
   - Fail when files are excluded or in certain configurations
3. **No Fallback**: After rsync completes, there's NO fallback to calculate size from:
   - The file list that WAS successfully parsed (dry_run_details)
   - Filesystem metadata (os.stat)

## Why Previous Fixes Failed

- Earlier fixes focused on file details (path, size_human per file)
- But these were NOT aggregated into `job.total_size_bytes`
- The UI still reads `job.total_size_bytes` which remains 0

## Permanent Solution

**Hybrid Approach (RECOMMENDED):**
1. Always parse rsync "Total file size" (current approach)
2. **CRITICAL FIX**: If total_file_size is 0 AND files exist, calculate from filesystem
3. For compression scenarios, parse rsync output correctly
4. Update UI to show pre/post compression size

**Implementation Location:**
- `backup_manager.py` (lines 115-135) - Add size fallback calculation
- `rsync_engine.py` - Improve rsync output parsing
- `main_window.py` - Update UI display with compression note

## Guarantee Against 0.00 MB

The fix guarantees no 0.00 MB display if:
1. Files exist in source (checked by: `if dry_run_details.get("new_files")`)
2. Calculate total_size_bytes = SUM(file["size_bytes"] for file in files)
3. Only show 0.00 MB if new_files list is actually empty
