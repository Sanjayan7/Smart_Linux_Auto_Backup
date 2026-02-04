"""
Base abstract class for cloud backup providers.

This module defines the interface that all cloud providers must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Callable


class CloudProvider(ABC):
    """Abstract base class for cloud storage providers"""
    
    @abstractmethod
    def __init__(self, credentials: Dict[str, str]):
        """
        Initialize cloud provider with credentials.
        
        Args:
            credentials: Dict containing provider-specific credentials
        """
        pass
    
    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test connection to cloud provider.
        
        Returns:
            True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def upload_file(self, local_path: str, remote_path: str,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> bool:
        """
        Upload a single file to cloud storage.
        
        Args:
            local_path: Path to local file
            remote_path: Destination path in cloud storage
            progress_callback: Optional callback(bytes_uploaded, total_bytes)
        
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def upload_directory(self, local_dir: str, remote_dir: str,
                        incremental: bool = False,
                        progress_callback: Optional[Callable[[str, int, int], None]] = None) -> bool:
        """
        Upload entire directory to cloud storage.
        
        Args:
            local_dir: Path to local directory
            remote_dir: Destination directory in cloud storage
            incremental: If True, only upload new/changed files
            progress_callback: Optional callback(filename, current_file, total_files)
        
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def file_exists(self, remote_path: str) -> bool:
        """
        Check if a file exists in cloud storage.
        
        Args:
            remote_path: Path in cloud storage
        
        Returns:
            True if file exists, False otherwise
        """
        pass
    
    @abstractmethod
    def get_file_etag(self, remote_path: str) -> Optional[str]:
        """
        Get ETag (hash) of remote file for change detection.
        
        Args:
            remote_path: Path in cloud storage
        
        Returns:
            ETag string or None if file doesn't exist
        """
        pass
    
    @classmethod
    @abstractmethod
    def get_credentials_schema(cls) -> Dict[str, dict]:
        """
        Get schema for required credentials.
        
        Returns:
            Dict mapping credential keys to their properties:
            {
                'key_name': {
                    'label': 'Display Label',
                    'type': 'text' | 'password',
                    'required': True | False,
                    'default': 'default_value'
                }
            }
        """
        pass
