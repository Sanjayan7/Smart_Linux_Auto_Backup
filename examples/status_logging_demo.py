#!/usr/bin/env python3
"""
Backup Status and Logging System - Working Demonstration

This script implements the BackupStatusManager design and runs a simulated 
backup job to demonstrate:
1. State transitions (Idle -> Running -> Completed/Failed)
2. Real-time logging callbacks (for GUI integration)
3. Structured JSON logging (for machine parsing)
4. Meaningful error and warning handling

Author: Backend Engineer
Date: 2026-02-04
"""

import logging
import json
import time
import random
import sys
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, asdict

# ==============================================================================
# DATA MODELS & ENUMS
# ==============================================================================

class BackupStatus(Enum):
    """Backup job status states."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class LogLevel(Enum):
    """Extended log levels."""
    DEBUG = 10
    INFO = 20
    SUCCESS = 25  # Custom level for success messages
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class LogCategory(Enum):
    """Log message categories."""
    SYSTEM = "system"
    BACKUP = "backup"
    RSYNC = "rsync"
    METADATA = "metadata"


@dataclass
class LogEntry:
    """Structured log entry."""
    timestamp: str
    level: str
    category: str
    message: str
    context: Dict[str, Any]
    
    def to_human_readable(self) -> str:
        """Format suitable for GUI display."""
        dt = datetime.fromisoformat(self.timestamp)
        time_str = dt.strftime("%H:%M:%S")
        
        icons = {
            "DEBUG": "🔍",
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "CRITICAL": "🔥"
        }
        icon = icons.get(self.level, "•")
        
        return f"[{time_str}] {icon} {self.message}"

    def to_json(self) -> str:
        """Format suitable for file storage."""
        return json.dumps(asdict(self))


# ==============================================================================
# CORE MANAGER CLASS
# ==============================================================================

class BackupStatusManager:
    """
    Manages backup job status, state transitions, and logging.
    Designed for easy integration with GUI callbacks.
    """
    
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
        
        # State
        self.status = BackupStatus.IDLE
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        
        # Metrics
        self.files_scanned = 0
        self.files_transferred = 0
        self.bytes_transferred = 0
        self.errors = []
        self.warnings = []
        
        # Files
        self.log_file = self.log_dir / f"{job_id}.jsonl"
        
        # Callbacks
        self.on_status_change: Optional[Callable[[BackupStatus], None]] = None
        self.on_log: Optional[Callable[[LogEntry], None]] = None
        self.on_progress: Optional[Callable[[Dict], None]] = None

    def transition_to(self, new_status: BackupStatus):
        """Execute state transition with validation."""
        if new_status not in self.TRANSITIONS.get(self.status, []):
            raise ValueError(f"Invalid transition: {self.status.value} -> {new_status.value}")
            
        old_status = self.status
        self.status = new_status
        
        # Handle timestamps
        if new_status == BackupStatus.RUNNING:
            self.start_time = datetime.now()
        elif new_status in [BackupStatus.COMPLETED, BackupStatus.FAILED, BackupStatus.CANCELED]:
            self.end_time = datetime.now()
            
        # Notify
        if self.on_status_change:
            self.on_status_change(new_status)
            
        self.log(LogLevel.INFO, LogCategory.SYSTEM, 
                 f"Status changed: {old_status.value} → {new_status.value}")

    def log(self, level: LogLevel, category: LogCategory, message: str, context: Dict = None):
        """Record a log entry and notify listeners."""
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            level=level.name,
            category=category.value,
            message=message,
            context=context or {}
        )
        
        # Write to file
        with open(self.log_file, "a") as f:
            f.write(entry.to_json() + "\n")
            
        # Notify callback (GUI update)
        if self.on_log:
            self.on_log(entry)
            
        # Console fallback if running in terminal
        if not self.on_log:
            print(entry.to_human_readable())

    def update_progress(self, **metrics):
        """Update progress metrics."""
        for k, v in metrics.items():
            if hasattr(self, k):
                setattr(self, k, v)
        
        if self.on_progress:
            self.on_progress(metrics)

    def add_warning(self, message: str, context: Dict = None):
        """Record a warning."""
        self.warnings.append({"message": message, "context": context, "time": datetime.now().isoformat()})
        self.log(LogLevel.WARNING, LogCategory.BACKUP, message, context)

    def add_error(self, message: str, context: Dict = None):
        """Record an error."""
        self.errors.append({"message": message, "context": context, "time": datetime.now().isoformat()})
        self.log(LogLevel.ERROR, LogCategory.BACKUP, message, context)
        
    def get_summary(self) -> Dict:
        """Get final job summary."""
        duration = 0
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()
            
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "duration_seconds": round(duration, 2),
            "files_transferred": self.files_transferred,
            "bytes_transferred": self.bytes_transferred,
            "errors": len(self.errors),
            "warnings": len(self.warnings)
        }


# ==============================================================================
# DEMONSTRATION LOGIC
# ==============================================================================

class ConsoleUI:
    """Mock GUI to demonstrate callback integration."""
    
    def on_status_change(self, status: BackupStatus):
        colors = {
            BackupStatus.RUNNING: "\033[94m",   # Blue
            BackupStatus.COMPLETED: "\033[92m", # Green
            BackupStatus.FAILED: "\033[91m",    # Red
        }
        color = colors.get(status, "\033[0m")
        print(f"\n{color}>>> STATUS CHANGE: {status.value.upper()} <<<\033[0m\n")

    def on_log(self, entry: LogEntry):
        print(f"DISPLAY: {entry.to_human_readable()}")

    def on_progress(self, metrics: Dict):
        # Overwrite last line for progress bar effect
        sys.stdout.write(f"\rPROGRESS: Scanned: {metrics.get('files_scanned', 0)} | Transferred: {metrics.get('files_transferred', 0)}")
        sys.stdout.flush()

def run_simulation():
    """Simulate a realistic backup process."""
    job_id = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # 1. Initialize System
    print(f"Initializing Backup Job: {job_id}")
    print("-" * 60)
    
    manager = BackupStatusManager(job_id, log_dir="./demo_logs")
    ui = ConsoleUI()
    
    # Connect callbacks (Integration Point)
    manager.on_status_change = ui.on_status_change
    manager.on_log = ui.on_log
    # manager.on_progress = ui.on_progress  # Uncomment for progress bar effect
    
    try:
        # 2. Start Backup
        manager.transition_to(BackupStatus.RUNNING)
        manager.log(LogLevel.INFO, LogCategory.SYSTEM, "Starting incremental backup process")
        
        # 3. Scanning Phase
        manager.log(LogLevel.INFO, LogCategory.BACKUP, "Scanning source directory: /home/user/docs")
        time.sleep(1) # Simulate work
        
        # Simulate discovering files
        total_files = 150
        for i in range(0, total_files, 50):
            manager.update_progress(files_scanned=i)
            time.sleep(0.2)
        
        manager.update_progress(files_scanned=total_files)
        manager.log(LogLevel.SUCCESS, LogCategory.BACKUP, f"Scan complete. Found {total_files} files.")
        
        # 4. Change Detection Phase
        manager.log(LogLevel.INFO, LogCategory.METADATA, "Detecting file changes...")
        time.sleep(1) 
        
        changes = {"new": 5, "modified": 2, "deleted": 0}
        manager.log(LogLevel.INFO, LogCategory.BACKUP, 
                   f"Change detection results: {changes['new']} new, {changes['modified']} modified")
        
        # 5. Transfer Phase
        manager.log(LogLevel.INFO, LogCategory.RSYNC, "Starting file transfer...")
        
        files_to_transfer = [
            ("report.pdf", 2500000),
            ("image.png", 5000000),
            ("notes.txt", 1024),
            ("data.csv", 1500000),
            ("video_intro.mp4", 55000000)
        ]
        
        transferred_count = 0
        transferred_bytes = 0
        
        for name, size in files_to_transfer:
            # Simulate transfer time based on size
            manager.log(LogLevel.INFO, LogCategory.RSYNC, f"Transferring {name}...", {"size_bytes": size})
            time.sleep(0.5) 
            
            # Simulate a warning event
            if "video" in name:
                manager.add_warning(f"Large file detected: {name}", {"size_mb": size / 1024 / 1024})
                
            transferred_count += 1
            transferred_bytes += size
            manager.update_progress(files_transferred=transferred_count, bytes_transferred=transferred_bytes)
        
        manager.log(LogLevel.SUCCESS, LogCategory.RSYNC, "All files transferred successfully.")
        
        # 6. Metadata Update Phase
        manager.log(LogLevel.INFO, LogCategory.METADATA, "Updating internal metadata registry...")
        time.sleep(0.5)
        manager.log(LogLevel.SUCCESS, LogCategory.METADATA, "Metadata saved.")
        
        # 7. Completion
        manager.transition_to(BackupStatus.COMPLETED)
        
        # Final Summary
        summary = manager.get_summary()
        manager.log(LogLevel.SUCCESS, LogCategory.SYSTEM, "Backup Job Completed Successfully", summary)
        
        print("\n\n" + "="*60)
        print("JOB SUMMARY (JSON)")
        print("="*60)
        print(json.dumps(summary, indent=2))
        print(f"\nLog file created at: {manager.log_file}")
        
    except Exception as e:
        manager.add_error(f"Unexpected error: {str(e)}")
        manager.transition_to(BackupStatus.FAILED)

if __name__ == "__main__":
    run_simulation()
