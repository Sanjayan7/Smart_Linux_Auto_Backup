from dataclasses import dataclass
from typing import Optional
from datetime import datetime

from autobackup.models.backup_config import BackupConfig


@dataclass
class BackupJob:
    id: str
    config: BackupConfig

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: str = "pending"   # pending | running | completed | failed

    log_file: Optional[str] = None
    files_transferred: int = 0
    total_size_bytes: int = 0
    duration_seconds: float = 0.0
