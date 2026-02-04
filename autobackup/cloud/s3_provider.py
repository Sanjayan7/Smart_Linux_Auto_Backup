"""
AWS S3 cloud storage provider implementation.

Requires: boto3
Install: pip install boto3
"""

import os
from typing import Dict, Optional, Callable
from pathlib import Path
from autobackup.cloud.base import CloudProvider
from autobackup.utils.logger import logger

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not installed. Install with: pip install boto3")


class S3Provider(CloudProvider):
    """AWS S3 (and S3-compatible) cloud storage provider"""
    
    def __init__(self, credentials: Dict[str, str]):
        """
        Initialize S3 provider.
        
        Args:
            credentials: Dict with keys:
                - access_key_id: AWS access key ID
                - secret_access_key: AWS secret access key
                - bucket_name: S3 bucket name
                - region: AWS region (default: us-east-1)
                - endpoint_url: Optional S3-compatible endpoint (for MinIO, etc.)
        """
        if not BOTO3_AVAILABLE:
            raise ImportError("boto3 is required for S3 provider. Install with: pip install boto3")
        
        self.access_key_id = credentials.get('access_key_id', '')
        self.secret_access_key = credentials.get('secret_access_key', '')
        self.bucket_name = credentials.get('bucket_name', '')
        self.region = credentials.get('region', 'us-east-1')
        self.endpoint_url = credentials.get('endpoint_url', None)
        
        # Initialize S3 client
        session_kwargs = {
            'aws_access_key_id': self.access_key_id,
            'aws_secret_access_key': self.secret_access_key,
            'region_name': self.region,
        }
        
        client_kwargs = {}
        if self.endpoint_url:
            client_kwargs['endpoint_url'] = self.endpoint_url
        
        try:
            self.s3_client = boto3.client('s3', **session_kwargs, **client_kwargs)
            logger.info(f"S3 client initialized for bucket: {self.bucket_name}")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            raise
    
    def test_connection(self) -> bool:
        """Test connection to S3 bucket."""
        try:
            # Try to head the bucket
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"Successfully connected to S3 bucket: {self.bucket_name}")
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                logger.error(f"Bucket not found: {self.bucket_name}")
            elif error_code == '403':
                logger.error(f"Access denied to bucket: {self.bucket_name}")
            else:
                logger.error(f"S3 connection test failed: {e}")
            return False
        except NoCredentialsError:
            logger.error("AWS credentials not found or invalid")
            return False
        except Exception as e:
            logger.error(f"S3 connection test failed: {e}")
            return False
    
    def upload_file(self, local_path: str, remote_path: str,
                   progress_callback: Optional[Callable[[int, int], None]] = None) -> bool:
        """Upload a single file to S3."""
        try:
            file_size = os.path.getsize(local_path)
            
            # Progress callback wrapper
            class ProgressCallback:
                def __init__(self, callback):
                    self._callback = callback
                    self._bytes_uploaded = 0
                
                def __call__(self, bytes_amount):
                    self._bytes_uploaded += bytes_amount
                    if self._callback:
                        self._callback(self._bytes_uploaded, file_size)
            
            extra_args = {}
            if progress_callback:
                extra_args['Callback'] = ProgressCallback(progress_callback)
            
            # Upload file
            self.s3_client.upload_file(
                local_path,
                self.bucket_name,
                remote_path,
                **extra_args
            )
            
            logger.info(f"Uploaded: {local_path} -> s3://{self.bucket_name}/{remote_path}")
            return True
            
        except FileNotFoundError:
            logger.error(f"Local file not found: {local_path}")
            return False
        except Exception as e:
            logger.error(f"Failed to upload {local_path}: {e}")
            return False
    
    def upload_directory(self, local_dir: str, remote_dir: str,
                        incremental: bool = False,
                        progress_callback: Optional[Callable[[str, int, int], None]] = None) -> bool:
        """Upload entire directory to S3."""
        try:
            local_path = Path(local_dir)
            if not local_path.is_dir():
                logger.error(f"Not a directory: {local_dir}")
                return False
            
            # Collect all files to upload
            files_to_upload = []
            for root, _, files in os.walk(local_dir):
                for filename in files:
                    local_file = os.path.join(root, filename)
                    relative_path = os.path.relpath(local_file, local_dir)
                    remote_file = os.path.join(remote_dir, relative_path).replace('\\', '/')
                    
                    # For incremental, check if file exists and has same ETag
                    if incremental:
                        local_etag = self._calculate_etag(local_file)
                        remote_etag = self.get_file_etag(remote_file)
                        
                        if remote_etag and local_etag == remote_etag:
                            logger.debug(f"Skipping unchanged file: {relative_path}")
                            continue
                    
                    files_to_upload.append((local_file, remote_file, relative_path))
            
            total_files = len(files_to_upload)
            logger.info(f"Uploading {total_files} files to S3...")
            
            # Upload files
            for idx, (local_file, remote_file, display_name) in enumerate(files_to_upload, 1):
                if progress_callback:
                    progress_callback(display_name, idx, total_files)
                
                if not self.upload_file(local_file, remote_file):
                    logger.warning(f"Failed to upload: {display_name}")
                    # Continue with other files rather than failing completely
            
            logger.info(f"Directory upload complete: {total_files} files")
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload directory: {e}")
            return False
    
    def file_exists(self, remote_path: str) -> bool:
        """Check if file exists in S3."""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=remote_path)
            return True
        except ClientError as e:
            if e.response.get('Error', {}).get('Code', '') == '404':
                return False
            logger.error(f"Error checking file existence: {e}")
            return False
        except Exception as e:
            logger.error(f"Error checking file existence: {e}")
            return False
    
    def get_file_etag(self, remote_path: str) -> Optional[str]:
        """Get ETag of remote file for change detection."""
        try:
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=remote_path)
            etag = response.get('ETag', '').strip('"')
            return etag if etag else None
        except ClientError as e:
            if e.response.get('Error', {}).get('Code', '') == '404':
                return None
            logger.error(f"Error getting file ETag: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting file ETag: {e}")
            return None
    
    def _calculate_etag(self, filepath: str) -> str:
        """Calculate S3-compatible ETag (MD5 hash) for local file."""
        import hashlib
        try:
            with open(filepath, 'rb') as f:
                file_hash = hashlib.md5(f.read()).hexdigest()
            return file_hash
        except Exception as e:
            logger.error(f"Error calculating ETag: {e}")
            return ""
    
    @classmethod
    def get_credentials_schema(cls) -> Dict[str, dict]:
        """Get schema for S3 credentials."""
        return {
            'access_key_id': {
                'label': 'AWS Access Key ID',
                'type': 'text',
                'required': True,
                'default': ''
            },
            'secret_access_key': {
                'label': 'AWS Secret Access Key',
                'type': 'password',
                'required': True,
                'default': ''
            },
            'bucket_name': {
                'label': 'S3 Bucket Name',
                'type': 'text',
                'required': True,
                'default': ''
            },
            'region': {
                'label': 'AWS Region',
                'type': 'text',
                'required': False,
                'default': 'us-east-1'
            },
            'endpoint_url': {
                'label': 'Endpoint URL (for S3-compatible services)',
                'type': 'text',
                'required': False,
                'default': ''
            }
        }
