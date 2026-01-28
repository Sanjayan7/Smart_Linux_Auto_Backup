from dataclasses import dataclass
from typing import List, Optional

@dataclass
class BackupConfig:
    source: str
    destination: str
    exclude_patterns: List[str]
    retention_policy: str
    incremental: bool = False
    compression: bool = False
    encryption: bool = False
    password: Optional[str] = None
    schedule: Optional[str] = None
    backup_interval_days: int = 0
    backup_name_template: str = "{timestamp}"
    notifications_enabled: bool = False
    dry_run: bool = False          

@dataclass
class BackupJob:
    id: str
    config: BackupConfig
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: str = "pending"
    log_file: Optional[str] = None
    files_transferred: int = 0
    total_size_bytes: int = 0
    duration_seconds: float = 0.0
