from dataclasses import dataclass
from typing import List, Optional

@dataclass
class BackupConfig:
    source: str
    destination: str
    exclude_patterns: List[str]
    retention_policy: str
    local_enabled: bool = True
    incremental: bool = False
    compression: bool = False
    encryption: bool = False
    password: Optional[str] = None
    schedule: Optional[str] = None
    backup_interval_days: int = 0
    backup_name_template: str = "{timestamp}"
    notifications_enabled: bool = False
    dry_run: bool = False
    
    # Cloud backup fields
    cloud_enabled: bool = False
    cloud_provider: str = "rclone"
    rclone_remote: Optional[str] = None
    cloud_archive: bool = True

    # Retention policy
    retention_enabled: bool = False
    retention_count: int = 5

    # Scheduler
    scheduler_enabled: bool = False
    scheduler_frequency: str = "daily"       # daily / weekly / custom
    scheduler_time: str = "22:00"            # HH:MM
    scheduler_day: str = "Sunday"            # for weekly
    scheduler_interval_minutes: int = 60     # for custom

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
    cloud_files_transferred: int = 0
    cloud_total_size_bytes: int = 0
    duration_seconds: float = 0.0
