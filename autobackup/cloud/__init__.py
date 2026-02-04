"""Cloud backup integration module for AutoBackup"""

from autobackup.cloud.base import CloudProvider
from autobackup.cloud.s3_provider import S3Provider
from autobackup.cloud.credentials import CredentialManager

__all__ = ['CloudProvider', 'S3Provider', 'CredentialManager']
