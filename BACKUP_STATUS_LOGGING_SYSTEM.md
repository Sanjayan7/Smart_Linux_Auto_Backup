# Backup Status and Logging System Design

**Role:** Backend Engineer  
**Date:** 2026-02-04  
**Project:** Smart Linux Auto Backup  
**Component:** Status Management & Logging System

---

## Table of Contents

1. [Status Flow](#status-flow)
2. [Log Format](#log-format)
3. [Example Outputs](#example-outputs)
4. [Implementation](#implementation)
5. [Error Handling](#error-handling)
6. [GUI Integration](#gui-integration)

---

## Status Flow

### State Machine Diagram

```
                    ┌──────────────────────────────────┐
                    │                                  │
                    │            IDLE                  │
                    │    (Ready for new backup)        │
                    │                                  │
                    └──────────┬───────────────────────┘
                               │
                               │ start_backup()
                               ▼
                    ┌──────────────────────────────────┐
                    │                                  │
                    │          RUNNING                 │
                    │   (Backup in progress)           │
                    │                                  │
                    └──────────┬───────────────────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                │ Success      │ Error        │ User Cancel
                ▼              ▼              ▼
    ┌────────────────┐  ┌───────────┐  ┌──────────┐
    │   COMPLETED    │  │  FAILED   │  │ CANCELED │
    │  ✓ Success     │  │  ✗ Error  │  │ ⊗ Stopped│
    └────────┬───────┘  └─────┬─────┘  └────┬─────┘
             │                │              │
             └────────────────┴──────────────┘
                               │
                               │ reset()
                               ▼
                    ┌──────────────────────────────────┐
                    │            IDLE                  │
                    └──────────────────────────────────┘
```

### State Definitions

| State | Description | Allowed Transitions | Icon |
|-------|-------------|---------------------|------|
| **IDLE** | System ready, no active backup | → RUNNING | ⏸️ |
| **RUNNING** | Backup executing | → COMPLETED, FAILED, CANCELED | ▶️ |
| **COMPLETED** | Backup finished successfully | → IDLE | ✅ |
| **FAILED** | Backup encountered error | → IDLE | ❌ |
| **CANCELED** | User stopped backup | → IDLE | ⊗ |

### State Transitions

```python
# Valid transitions
TRANSITIONS = {
    'IDLE': ['RUNNING'],
    'RUNNING': ['COMPLETED', 'FAILED', 'CANCELED'],
    'COMPLETED': ['IDLE'],
    'FAILED': ['IDLE'],
    'CANCELED': ['IDLE']
}
```

### Extended States (Optional)

For more granular tracking:

```
IDLE
  ↓
INITIALIZING     # Validating config, creating directories
  ↓
SCANNING         # Scanning source files
  ↓
DETECTING        # Detecting changes (incremental mode)
  ↓
TRANSFERRING     # Actually copying files
  ↓
ENCRYPTING       # Encryption phase (if enabled)
  ↓
FINALIZING       # Updating metadata, cleanup
  ↓
COMPLETED / FAILED
```

---

## Log Format

### Structured Log Entry Format

```json
{
  "timestamp": "2026-02-04T20:51:22.123456+05:30",
  "level": "INFO",
  "category": "backup",
  "message": "Backup started",
  "context": {
    "job_id": "backup_20260204205122",
    "backup_type": "incremental",
    "source": "/home/user/documents",
    "destination": "/backup/documents"
  },
  "metrics": {
    "files_scanned": 0,
    "files_transferred": 0,
    "bytes_transferred": 0,
    "duration_seconds": 0
  }
}
```

### Log Levels

| Level | Priority | Usage | Color (GUI) |
|-------|----------|-------|-------------|
| **DEBUG** | 10 | Detailed diagnostic info | Gray |
| **INFO** | 20 | General information | Blue |
| **WARNING** | 30 | Warning messages | Orange |
| **ERROR** | 40 | Error occurred but recoverable | Red |
| **CRITICAL** | 50 | Critical failure | Dark Red |
| **SUCCESS** | 25 | Successful operation (custom) | Green |

### Log Categories

```python
class LogCategory:
    SYSTEM = "system"          # System-level events
    BACKUP = "backup"          # Backup operations
    RESTORE = "restore"        # Restore operations
    CONFIG = "config"          # Configuration changes
    METADATA = "metadata"      # Metadata operations
    RSYNC = "rsync"           # Rsync output
    ENCRYPTION = "encryption" # Encryption operations
    CLOUD = "cloud"           # Cloud sync operations
```

### Human-Readable Format (for GUI)

```
[2026-02-04 20:51:22] INFO | Backup started
[2026-02-04 20:51:23] INFO | Scanning source directory...
[2026-02-04 20:51:25] INFO | ✓ Found 1,247 files (4.52 GB)
[2026-02-04 20:51:26] INFO | Detecting changes...
[2026-02-04 20:51:27] INFO | ✓ Changes: 5 new, 3 modified, 1,239 unchanged
[2026-02-04 20:51:28] INFO | Starting file transfer...
[2026-02-04 20:51:35] INFO | ✓ Transferred 8 files (245 MB)
[2026-02-04 20:51:36] INFO | Updating metadata...
[2026-02-04 20:51:37] SUCCESS | ✅ Backup completed successfully
```

### Structured Format (for file logs)

```
2026-02-04 20:51:22.123 [INFO] [backup] Backup started | job_id=backup_20260204205122 source=/home/user/documents
2026-02-04 20:51:23.456 [INFO] [backup] Scanning source directory | files=0 dirs=0
2026-02-04 20:51:25.789 [INFO] [backup] Scan complete | files=1247 total_size=4852695040
2026-02-04 20:51:26.012 [INFO] [metadata] Loading previous metadata | tracked_files=1242
2026-02-04 20:51:27.345 [INFO] [backup] Change detection complete | new=5 modified=3 deleted=0 unchanged=1239
2026-02-04 20:51:28.678 [INFO] [rsync] Transfer started | command="rsync -aH --link-dest=..."
2026-02-04 20:51:35.901 [INFO] [rsync] Transfer complete | transferred=8 size=257586176 duration=7.223s
2026-02-04 20:51:36.234 [INFO] [metadata] Updating metadata | files=1247
2026-02-04 20:51:37.567 [SUCCESS] [backup] Backup completed | duration=15.444s status=completed
```

---

## Example Outputs

### Example 1: Successful Incremental Backup

```
================================================================================
BACKUP STARTED - 2026-02-04 20:51:22
================================================================================
Job ID:          backup_20260204205122
Type:            Incremental Backup
Source:          /home/user/documents
Destination:     /backup/documents/2026-02-04_20-51-22
Features:        Incremental, Compression
================================================================================

[20:51:23] 📂 Scanning source directory...
[20:51:25] ✓ Scanned 1,247 files (4.52 GB)

[20:51:26] 🔍 Detecting changes...
[20:51:27] ✓ Change detection complete:
           • New files: 5 (12.3 MB)
           • Modified files: 3 (8.7 MB)
           • Deleted files: 0
           • Unchanged files: 1,239 (will be hard-linked)

[20:51:28] 🚀 Starting file transfer...
[20:51:29] ▶ Transferring: documents/report_2024.pdf (2.5 MB)
[20:51:30] ▶ Transferring: documents/presentation.pptx (15.3 MB)
[20:51:32] ▶ Transferring: config/settings.json (4.2 KB)
[20:51:33] ▶ Transferring: src/main.py (18.7 KB)
[20:51:34] ▶ Transferring: README.md (1.2 KB)
[20:51:35] ✓ Transfer complete: 8 files (245.67 MB) in 7.2 seconds

[20:51:36] 💾 Updating backup metadata...
[20:51:37] ✓ Metadata saved (1,247 files tracked)

================================================================================
✅ BACKUP COMPLETED SUCCESSFULLY
================================================================================
Status:          Completed
Duration:        15.4 seconds
Files backed up: 8 files (5 new, 3 modified)
Total size:      245.67 MB
Storage saved:   4.27 GB (via hard-links)
Backup location: /backup/documents/2026-02-04_20-51-22
================================================================================
```

### Example 2: Failed Backup with Error

```
================================================================================
BACKUP STARTED - 2026-02-04 21:00:15
================================================================================
Job ID:          backup_20260204210015
Type:            Full Backup
Source:          /home/user/projects
Destination:     /backup/projects/2026-02-04_21-00-15
================================================================================

[21:00:16] 📂 Scanning source directory...
[21:00:18] ✓ Scanned 15,432 files (25.8 GB)

[21:00:19] 🚀 Starting file transfer...
[21:00:20] ▶ Transferring: project1/data.db (450 MB)
[21:00:35] ▶ Transferring: project2/images/photo1.jpg (8.2 MB)
[21:00:36] ▶ Transferring: project2/images/photo2.jpg (7.5 MB)
[21:00:37] ❌ ERROR: Permission denied

================================================================================
❌ BACKUP FAILED
================================================================================
Status:          Failed
Duration:        22.3 seconds
Error:           Permission denied accessing file
Details:         Cannot read /home/user/projects/project2/images/photo2.jpg
                 Error code: EACCES (13)
                 
Files backed up: 2 files before error
Partial backup:  /backup/projects/2026-02-04_21-00-15 (incomplete)

Suggested Action:
  • Check file permissions: chmod +r /home/user/projects/project2/images/photo2.jpg
  • Or exclude the file: --exclude='project2/images/*'
  • Run backup again after fixing permissions

================================================================================
```

### Example 3: Dry Run Output

```
================================================================================
DRY RUN SIMULATION - 2026-02-04 21:15:30
================================================================================
⚠️  DRY RUN MODE - No files will be modified
Job ID:          dryrun_20260204211530
Source:          /home/user/documents
Destination:     /backup/documents/preview
================================================================================

[21:15:31] 📂 Scanning source directory...
[21:15:33] ✓ Scanned 1,247 files (4.52 GB)

[21:15:34] 🔍 Simulating backup...

================================================================================
📋 DRY RUN RESULTS
================================================================================

📊 Summary:
   • Total files analyzed: 1,247
   • Would transfer: 8 files (245.67 MB)
   • Would skip: 1,239 files (hard-linked)
   • Estimated duration: ~7 seconds

✅ NEW FILES (5 files)
   These files would be CREATED:
   
   1. documents/report_2024.pdf (2.5 MB)
   2. documents/presentation.pptx (15.3 MB)
   3. data/new_data.csv (3.1 MB)
   4. images/screenshot.png (1.2 MB)
   5. notes/meeting_notes.txt (45 KB)

🔄 UPDATED FILES (3 files)
   These files would be OVERWRITTEN:
   
   1. config/settings.json (4.2 KB)
      Reason: Content changed
   
   2. src/main.py (18.7 KB)
      Reason: Size and timestamp changed
   
   3. README.md (1.2 KB)
      Reason: Checksum changed

⏭️  UNCHANGED FILES (1,239 files)
   These files would be HARD-LINKED (zero additional space)

================================================================================
⚠️  NO CHANGES HAVE BEEN MADE
   This was a simulation only. Run a real backup to apply these changes.
================================================================================
```

### Example 4: Canceled Backup

```
================================================================================
BACKUP STARTED - 2026-02-04 21:30:45
================================================================================
Job ID:          backup_20260204213045
Type:            Incremental Backup
Source:          /home/user/documents
Destination:     /backup/documents/2026-02-04_21-30-45
================================================================================

[21:30:46] 📂 Scanning source directory...
[21:30:48] ✓ Scanned 1,247 files (4.52 GB)

[21:30:49] 🚀 Starting file transfer...
[21:30:50] ▶ Transferring: documents/large_video.mp4 (1.2 GB)
[21:30:55] ⏸️  Transfer progress: 45% (540 MB / 1.2 GB)
[21:31:00] ⏸️  Transfer progress: 78% (936 MB / 1.2 GB)

[21:31:03] 🛑 BACKUP CANCELED BY USER

================================================================================
⊗ BACKUP CANCELED
================================================================================
Status:          Canceled
Duration:        18.2 seconds
Files backed up: 0 files (incomplete)
Partial data:    /backup/documents/2026-02-04_21-30-45 (will be cleaned up)

Cleanup:
  • Removing incomplete backup directory
  • Metadata not updated (previous backup still valid)
  • Ready for next backup

================================================================================
```

### Example 5: Warning Messages During Backup

```
================================================================================
BACKUP STARTED - 2026-02-04 21:45:10
================================================================================
Job ID:          backup_20260204214510
Type:            Incremental Backup
Source:          /home/user/documents
Destination:     /backup/documents/2026-02-04_21-45-10
================================================================================

[21:45:11] 📂 Scanning source directory...
[21:45:12] ⚠️  WARNING: Symbolic link detected: /home/user/documents/link_to_external
           Skipping - not following symbolic links (use --copy-links to include)

[21:45:13] ⚠️  WARNING: Large file detected: video_project.mp4 (8.5 GB)
           This may take a while to transfer

[21:45:15] ✓ Scanned 1,245 files (15.2 GB)
           Note: 2 items skipped (1 symlink, 0 permission errors)

[21:45:16] 🔍 Detecting changes...
[21:45:17] ✓ Changes: 3 new, 2 modified, 1,240 unchanged

[21:45:18] 🚀 Starting file transfer...
[21:45:19] ▶ Transferring: docs/report.pdf (2.1 MB)
[21:45:20] ▶ Transferring: video_project.mp4 (8.5 GB)
[21:45:25] ⏸️  Progress: 15% (1.3 GB / 8.5 GB) - ETA: 25 seconds
[21:45:30] ⏸️  Progress: 35% (3.0 GB / 8.5 GB) - ETA: 18 seconds
[21:45:35] ⏸️  Progress: 58% (4.9 GB / 8.5 GB) - ETA: 10 seconds
[21:45:40] ⏸️  Progress: 82% (7.0 GB / 8.5 GB) - ETA: 4 seconds
[21:45:44] ✓ Transfer complete: 5 files (8.7 GB) in 26 seconds

[21:45:45] 💾 Updating metadata...
[21:45:46] ✓ Metadata saved

================================================================================
✅ BACKUP COMPLETED WITH WARNINGS
================================================================================
Status:          Completed
Duration:        36.2 seconds
Files backed up: 5 files
Warnings:        2 (review warnings above)
Total size:      8.7 GB
Backup location: /backup/documents/2026-02-04_21-45-10

⚠️  Review Warnings:
   • 1 symbolic link was skipped
   • Large files may slow down future backups

================================================================================
```

---

## Implementation

### Core Status Manager Class

```python
"""
Backup Status and Logging Manager

Manages backup job status, state transitions, and structured logging
suitable for both file persistence and real-time GUI updates.
"""

import logging
import json
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, asdict
from pathlib import Path


class BackupStatus(Enum):
    """Backup job status states."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class LogLevel(Enum):
    """Extended log levels including SUCCESS."""
    DEBUG = 10
    INFO = 20
    SUCCESS = 25  # Custom level
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class LogCategory(Enum):
    """Log message categories for filtering."""
    SYSTEM = "system"
    BACKUP = "backup"
    RESTORE = "restore"
    CONFIG = "config"
    METADATA = "metadata"
    RSYNC = "rsync"
    ENCRYPTION = "encryption"
    CLOUD = "cloud"


@dataclass
class LogEntry:
    """Structured log entry."""
    timestamp: str
    level: str
    category: str
    message: str
    context: Dict[str, Any]
    metrics: Dict[str, Any]
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self), indent=2)
    
    def to_human_readable(self) -> str:
        """Convert to human-readable format for GUI."""
        # Format timestamp
        dt = datetime.fromisoformat(self.timestamp)
        time_str = dt.strftime("%H:%M:%S")
        
        # Get emoji for level
        emoji_map = {
            "DEBUG": "🔍",
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "CRITICAL": "🔥"
        }
        emoji = emoji_map.get(self.level, "•")
        
        return f"[{time_str}] {emoji} {self.message}"
    
    def to_structured(self) -> str:
        """Convert to structured format for file logs."""
        context_str = " ".join([f"{k}={v}" for k, v in self.context.items()])
        return f"{self.timestamp} [{self.level}] [{self.category}] {self.message} | {context_str}"


class BackupStatusManager:
    """
    Manages backup job status and logging with real-time updates.
    
    Features:
    - State machine for status transitions
    - Structured logging
    - Real-time GUI callbacks
    - File persistence
    - Error tracking
    """
    
    # Valid state transitions
    TRANSITIONS = {
        BackupStatus.IDLE: [BackupStatus.RUNNING],
        BackupStatus.RUNNING: [BackupStatus.COMPLETED, BackupStatus.FAILED, BackupStatus.CANCELED],
        BackupStatus.COMPLETED: [BackupStatus.IDLE],
        BackupStatus.FAILED: [BackupStatus.IDLE],
        BackupStatus.CANCELED: [BackupStatus.IDLE]
    }
    
    def __init__(self, job_id: str, log_dir: str = "./logs"):
        self.job_id = job_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Status
        self.status = BackupStatus.IDLE
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        
        # Metrics
        self.files_scanned = 0
        self.files_transferred = 0
        self.bytes_transferred = 0
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        
        # Callbacks for real-time updates
        self.status_callback: Optional[Callable[[BackupStatus], None]] = None
        self.log_callback: Optional[Callable[[LogEntry], None]] = None
        self.progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        
        # Log file
        self.log_file = self.log_dir / f"{job_id}.log"
        self.json_log_file = self.log_dir / f"{job_id}.json"
        
        # In-memory log buffer (for GUI display)
        self.log_buffer: List[LogEntry] = []
        
        # Setup logging
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup file logging."""
        self.logger = logging.getLogger(f"backup.{self.job_id}")
        self.logger.setLevel(logging.DEBUG)
        
        # File handler (structured format)
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s')
        )
        self.logger.addHandler(file_handler)
        
        # Add custom SUCCESS level
        logging.addLevelName(25, "SUCCESS")
    
    def set_status_callback(self, callback: Callable[[BackupStatus], None]):
        """Set callback for status changes."""
        self.status_callback = callback
    
    def set_log_callback(self, callback: Callable[[LogEntry], None]):
        """Set callback for new log entries."""
        self.log_callback = callback
    
    def set_progress_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set callback for progress updates."""
        self.progress_callback = callback
    
    def transition_to(self, new_status: BackupStatus):
        """
        Transition to new status with validation.
        
        Args:
            new_status: Target status
            
        Raises:
            ValueError: If transition is invalid
        """
        # Validate transition
        allowed = self.TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {self.status.value} -> {new_status.value}"
            )
        
        old_status = self.status
        self.status = new_status
        
        # Track timestamps
        if new_status == BackupStatus.RUNNING:
            self.start_time = datetime.now()
        elif new_status in [BackupStatus.COMPLETED, BackupStatus.FAILED, BackupStatus.CANCELED]:
            self.end_time = datetime.now()
        
        # Log transition
        self.log(
            LogLevel.INFO,
            LogCategory.SYSTEM,
            f"Status changed: {old_status.value} → {new_status.value}",
            context={"old_status": old_status.value, "new_status": new_status.value}
        )
        
        # Notify callback
        if self.status_callback:
            self.status_callback(new_status)
    
    def log(self, 
            level: LogLevel, 
            category: LogCategory,
            message: str,
            context: Dict[str, Any] = None,
            metrics: Dict[str, Any] = None):
        """
        Add a log entry.
        
        Args:
            level: Log level
            category: Log category
            message: Log message
            context: Additional context
            metrics: Metrics data
        """
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            level=level.name,
            category=category.value,
            message=message,
            context=context or {},
            metrics=metrics or {}
        )
        
        # Add to buffer
        self.log_buffer.append(entry)
        
        # Write to file log (structured)
        self.logger.log(level.value, entry.to_structured())
        
        # Write to JSON log
        with open(self.json_log_file, 'a') as f:
            f.write(entry.to_json() + "\n")
        
        # Notify callback for real-time GUI update
        if self.log_callback:
            self.log_callback(entry)
    
    def update_progress(self, **metrics):
        """Update progress metrics."""
        for key, value in metrics.items():
            if hasattr(self, key):
                setattr(self, key, value)
        
        if self.progress_callback:
            self.progress_callback(metrics)
    
    def add_error(self, error_message: str, error_details: Dict[str, Any] = None):
        """Record an error."""
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "message": error_message,
            "details": error_details or {}
        }
        self.errors.append(error_entry)
        
        self.log(
            LogLevel.ERROR,
            LogCategory.BACKUP,
            error_message,
            context=error_details or {}
        )
    
    def add_warning(self, warning_message: str, warning_details: Dict[str, Any] = None):
        """Record a warning."""
        warning_entry = {
            "timestamp": datetime.now().isoformat(),
            "message": warning_message,
            "details": warning_details or {}
        }
        self.warnings.append(warning_entry)
        
        self.log(
            LogLevel.WARNING,
            LogCategory.BACKUP,
            warning_message,
            context=warning_details or {}
        )
    
    def get_duration(self) -> float:
        """Get backup duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        elif self.start_time:
            return (datetime.now() - self.start_time).total_seconds()
        return 0.0
    
    def get_summary(self) -> Dict[str, Any]:
        """Get backup summary."""
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.get_duration(),
            "files_scanned": self.files_scanned,
            "files_transferred": self.files_transferred,
            "bytes_transferred": self.bytes_transferred,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "log_file": str(self.log_file),
            "json_log_file": str(self.json_log_file)
        }
    
    def get_logs(self, 
                 level: Optional[LogLevel] = None,
                 category: Optional[LogCategory] = None,
                 limit: Optional[int] = None) -> List[LogEntry]:
        """
        Get filtered logs.
        
        Args:
            level: Filter by log level
            category: Filter by category
            limit: Maximum number of entries
            
        Returns:
            List of log entries
        """
        filtered = self.log_buffer
        
        if level:
            filtered = [e for e in filtered if e.level == level.name]
        
        if category:
            filtered = [e for e in filtered if e.category == category.value]
        
        if limit:
            filtered = filtered[-limit:]
        
        return filtered
    
    def format_for_gui(self) -> str:
        """Format complete log for GUI display."""
        lines = []
        
        # Header
        lines.append("=" * 80)
        lines.append(f"BACKUP JOB: {self.job_id}")
        lines.append(f"Status: {self.status.value.upper()}")
        if self.start_time:
            lines.append(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        if self.end_time:
            lines.append(f"Ended: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append(f"Duration: {self.get_duration():.2f} seconds")
        lines.append("=" * 80)
        lines.append("")
        
        # Logs
        for entry in self.log_buffer:
            lines.append(entry.to_human_readable())
        
        # Summary
        if self.status in [BackupStatus.COMPLETED, BackupStatus.FAILED, BackupStatus.CANCELED]:
            lines.append("")
            lines.append("=" * 80)
            lines.append(f"SUMMARY")
            lines.append("=" * 80)
            lines.append(f"Files scanned: {self.files_scanned}")
            lines.append(f"Files transferred: {self.files_transferred}")
            lines.append(f"Bytes transferred: {self.bytes_transferred:,}")
            if self.warnings:
                lines.append(f"Warnings: {len(self.warnings)}")
            if self.errors:
                lines.append(f"Errors: {len(self.errors)}")
            lines.append("=" * 80)
        
        return "\n".join(lines)
```

### Usage Example

```python
# Create status manager
status_mgr = BackupStatusManager(job_id="backup_20260204205122")

# Setup callbacks for GUI
def on_status_change(status: BackupStatus):
    print(f"Status changed to: {status.value}")
    # Update GUI status indicator

def on_log_entry(entry: LogEntry):
    print(entry.to_human_readable())
    # Append to GUI text widget

def on_progress(metrics: Dict):
    print(f"Progress: {metrics}")
    # Update GUI progress bar

status_mgr.set_status_callback(on_status_change)
status_mgr.set_log_callback(on_log_entry)
status_mgr.set_progress_callback(on_progress)

# Start backup
status_mgr.transition_to(BackupStatus.RUNNING)
status_mgr.log(LogLevel.INFO, LogCategory.BACKUP, "Backup started")

# Scanning phase
status_mgr.log(LogLevel.INFO, LogCategory.BACKUP, "Scanning source directory...")
status_mgr.update_progress(files_scanned=1247)
status_mgr.log(LogLevel.SUCCESS, LogCategory.BACKUP, "✓ Scanned 1,247 files")

# Transfer phase
status_mgr.log(LogLevel.INFO, LogCategory.RSYNC, "Starting file transfer...")
status_mgr.update_progress(files_transferred=8, bytes_transferred=257586176)

# Warning
status_mgr.add_warning("Large file detected", {"file": "video.mp4", "size": 8500000000})

# Complete
status_mgr.log(LogLevel.SUCCESS, LogCategory.BACKUP, "✅ Backup completed")
status_mgr.transition_to(BackupStatus.COMPLETED)

# Get summary
summary = status_mgr.get_summary()
print(json.dumps(summary, indent=2))

# Format for GUI
gui_output = status_mgr.format_for_gui()
print(gui_output)
```

---

## Error Handling

### Error Classification

```python
class BackupError(Exception):
    """Base class for backup errors."""
    pass

class ConfigurationError(BackupError):
    """Configuration is invalid."""
    severity = "CRITICAL"
    recoverable = False

class PermissionError(BackupError):
    """Permission denied."""
    severity = "ERROR"
    recoverable = True
    suggestion = "Check file permissions or run with appropriate privileges"

class DiskSpaceError(BackupError):
    """Insufficient disk space."""
    severity = "ERROR"
    recoverable = True
    suggestion = "Free up disk space or choose a different destination"

class NetworkError(BackupError):
    """Network connection failed."""
    severity = "ERROR"
    recoverable = True
    suggestion = "Check network connection and retry"

class MetadataCorruptionError(BackupError):
    """Backup metadata is corrupted."""
    severity = "WARNING"
    recoverable = True
    suggestion = "Metadata will be rebuilt (may perform full backup)"
```

### Error Messages Format

```python
ERROR_MESSAGES = {
    "EACCES": {
        "title": "Permission Denied",
        "message": "Cannot access file: {filepath}",
        "suggestion": "Check file permissions: chmod +r {filepath}",
        "recovery": "Skip file and continue, or fix permissions and retry"
    },
    
    "ENOSPC": {
        "title": "Disk Full",
        "message": "Insufficient disk space on destination: {destination}",
        "suggestion": "Free up space or choose different destination",
        "recovery": "Backup cannot continue"
    },
    
    "ENOENT": {
        "title": "File Not Found",
        "message": "Source file does not exist: {filepath}",
        "suggestion": "File may have been deleted during backup",
        "recovery": "Continue with remaining files"
    },
    
    "ETIMEDOUT": {
        "title": "Connection Timeout",
        "message": "Network connection timed out: {destination}",
        "suggestion": "Check network connection and firewall settings",
        "recovery": "Retry backup or use local destination"
    }
}

def format_error(error_code: str, **context) -> Dict[str, str]:
    """Format error message with context."""
    template = ERROR_MESSAGES.get(error_code, {
        "title": "Backup Error",
        "message": "An error occurred: {error}",
        "suggestion": "Check logs for details",
        "recovery": "Retry backup"
    })
    
    return {
        "title": template["title"],
        "message": template["message"].format(**context),
        "suggestion": template["suggestion"].format(**context),
        "recovery": template["recovery"]
    }
```

---

## GUI Integration

### Status Indicator Widget

```python
import tkinter as tk
from tkinter import ttk

class StatusIndicator(ttk.Frame):
    """Visual status indicator for backup job."""
    
    STATUS_COLORS = {
        BackupStatus.IDLE: "#95a5a6",        # Gray
        BackupStatus.RUNNING: "#3498db",     # Blue
        BackupStatus.COMPLETED: "#27ae60",   # Green
        BackupStatus.FAILED: "#e74c3c",      # Red
        BackupStatus.CANCELED: "#f39c12"     # Orange
    }
    
    STATUS_ICONS = {
        BackupStatus.IDLE: "⏸️",
        BackupStatus.RUNNING: "▶️",
        BackupStatus.COMPLETED: "✅",
        BackupStatus.FAILED: "❌",
        BackupStatus.CANCELED: "⊗"
    }
    
    def __init__(self, parent):
        super().__init__(parent)
        
        self.status_label = ttk.Label(self, text="", font=("Arial", 12, "bold"))
        self.status_label.pack(side="left", padx=5)
        
        self.status_text = ttk.Label(self, text="Idle")
        self.status_text.pack(side="left", padx=5)
        
        self.set_status(BackupStatus.IDLE)
    
    def set_status(self, status: BackupStatus):
        """Update status display."""
        icon = self.STATUS_ICONS[status]
        color = self.STATUS_COLORS[status]
        
        self.status_label.config(text=icon)
        self.status_text.config(text=status.value.title())
        self.status_label.config(foreground=color)
```

### Real-Time Log Viewer

```python
class LogViewer(ttk.Frame):
    """Real-time log viewer with color coding."""
    
    LEVEL_COLORS = {
        "DEBUG": "#7f8c8d",
        "INFO": "#3498db",
        "SUCCESS": "#27ae60",
        "WARNING": "#f39c12",
        "ERROR": "#e74c3c",
        "CRITICAL": "#c0392b"
    }
    
    def __init__(self, parent):
        super().__init__(parent)
        
        # Create text widget with scrollbar
        scrollbar = ttk.Scrollbar(self)
        scrollbar.pack(side="right", fill="y")
        
        self.log_text = tk.Text(
            self,
            height=20,
            width=80,
            state="disabled",
            yscrollcommand=scrollbar.set,
            font=("Courier", 9)
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)
        
        # Configure tags for colors
        for level, color in self.LEVEL_COLORS.items():
            self.log_text.tag_config(level, foreground=color)
    
    def add_log(self, entry: LogEntry):
        """Add log entry with color coding."""
        self.log_text.config(state="normal")
        
        # Insert with appropriate tag
        text = entry.to_human_readable() + "\n"
        self.log_text.insert(tk.END, text, entry.level)
        
        # Auto-scroll to bottom
        self.log_text.see(tk.END)
        
        self.log_text.config(state="disabled")
    
    def clear(self):
        """Clear all logs."""
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")
```

---

## Summary

This backup status and logging system provides:

✅ **Clear State Flow** - Well-defined states with validated transitions  
✅ **Structured Logging** - JSON and human-readable formats  
✅ **Real-Time Updates** - Callback system for GUI integration  
✅ **Error Handling** - Meaningful error messages with recovery suggestions  
✅ **GUI-Ready** - Example widgets and color-coding  
✅ **Metrics Tracking** - Progress monitoring and statistics  
✅ **File Persistence** - Structured logs for auditing  

**Production-ready for immediate integration!** 🚀
