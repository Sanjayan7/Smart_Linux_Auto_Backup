"""Cloud backup integration module for AutoBackup"""

from autobackup.cloud.base import CloudProvider
from autobackup.cloud.rclone_provider import RcloneProvider
from autobackup.cloud.credentials import CredentialManager

__all__ = ['CloudProvider', 'RcloneProvider', 'CredentialManager']
