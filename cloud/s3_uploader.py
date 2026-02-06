#!/usr/bin/env python3
"""
AWS S3 Backup Uploader
Architecture: Cloud Backup Architect

Features:
- Incremental Delta Upload (Only transfers new/modified files)
- Multipart Upload for large files
- Automatic Retries & Error Handling
- Server-Side Encryption
- Storage Class Optimization

Dependencies: pip install boto3
"""

import os
import sys
import threading
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple


# Try to import boto3, handle missing dependency gracefully
try:
    import boto3
    from boto3.s3.transfer import TransferConfig
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:
    # MOCKING FOR DEMO ENVIRONMENT (if boto3 is missing)
    print("Warning: 'boto3' not found. Running in MOCK mode for logic demonstration.")
    boto3 = None
    ClientError = Exception
    NoCredentialsError = Exception
    class TransferConfig:
        def __init__(self, **kwargs): pass


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("CloudBackup")

class S3Uploader:
    """
    Handles robust file uploads to AWS S3 with incremental support.
    """
    
    def __init__(self, bucket_name: str, region: str = "us-east-1"):
        self.bucket_name = bucket_name
        self.region = region
        self.s3_client = None
        self.stats = {
            "files": 0,
            "bytes": 0,
            "errors": 0,
            "skipped": 0
        }
        
    def connect(self) -> bool:
        """Establish connection to S3."""
        try:
            self.s3_client = boto3.client('s3', region_name=self.region)
            # Verify bucket exists/access
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"✅ Connected to AWS S3 Bucket: {self.bucket_name}")
            return True
        except NoCredentialsError:
            logger.error("❌ AWS Credentials not found. Check ~/.aws/credentials")
            return False
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '403':
                logger.error(f"❌ Access Denied to bucket: {self.bucket_name}")
            elif error_code == '404':
                logger.error(f"❌ Bucket does not exist: {self.bucket_name}")
            else:
                logger.error(f"❌ Connection error: {e}")
            return False

    def upload_incremental(self, 
                          source_root: str, 
                          file_list: List[str], 
                          remote_prefix: str) -> Dict:
        """
        Uploads ONLY the specified list of files (Incremental Push).
        
        Args:
            source_root: Base local directory (e.g., /home/user)
            file_list: List of relative paths detected as CHANGED (new/modified)
            remote_prefix: S3 folder path (e.g., backups/2026-02-04_2100/)
        """
        if not self.s3_client:
            if not self.connect():
                return self.stats

        logger.info(f"🚀 Starting Cloud Upload to s3://{self.bucket_name}/{remote_prefix}")
        logger.info(f"📋 Processing {len(file_list)} changed files...")

        # Configuration for concurrency
        transfer_config = TransferConfig(
            multipart_threshold=8 * 1024 * 1024, # 8MB
            max_concurrency=10,
            use_threads=True
        )

        for rel_path in file_list:
            local_path = Path(source_root) / rel_path
            s3_key = f"{remote_prefix}{rel_path}"
            
            if not local_path.exists():
                logger.warning(f"⚠️ File skipped (not found): {local_path}")
                self.stats["skipped"] += 1
                continue
                
            self._upload_single_file(local_path, s3_key, transfer_config)

        logger.info(f"☁️ Cloud Backup Complete: {self.stats['files']} files ({self.stats['bytes']/1024/1024:.2f} MB)")
        return self.stats

    def _upload_single_file(self, local_path: Path, s3_key: str, config: TransferConfig):
        """Upload a single file with retries and progress logging."""
        file_size = local_path.stat().st_size
        str_path = str(local_path)

        retries = 3
        for attempt in range(retries):
            try:
                # Callback (simplified for demo)
                def progress_callback(bytes_transferred):
                    pass 

                logger.info(f"⬆️ Uploading: {local_path.name} ({file_size/1024:.1f} KB)")
                
                self.s3_client.upload_file(
                    Filename=str_path,
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Config=config,
                    ExtraArgs={
                        'ServerSideEncryption': 'AES256',
                        'StorageClass': 'STANDARD_IA' # Save money on backups
                    },
                    Callback=progress_callback
                )
                
                self.stats["files"] += 1
                self.stats["bytes"] += file_size
                return # Success

            except ClientError as e:
                logger.error(f"❌ Upload failed {local_path.name}: {e}")
                self.stats["errors"] += 1
                return # Don't retry client errors (like auth)
            except Exception as e:
                logger.warning(f"⚠️ Network error (Attempt {attempt+1}/{retries}): {e}")
                time.sleep(2 ** attempt) # Exponential Backoff: 1s, 2s, 4s

        logger.error(f"❌ Permanently failed to upload: {local_path.name}")
        self.stats["errors"] += 1

# ==============================================================================
# ARCHITECTURE DEMONSTRATION
# ==============================================================================

def demo_cloud_workflow():
    """Simulates the entire workflow using mock data."""
    print("\n=== ☁️ CLOUD BACKUP ARCHITECTURE SIMULATION ===\n")
    
    # 1. Simulate Local Backup Result (from Incremental Engine)
    print("[1] 📂 Local Incremental Backup Finished.")
    print("    Snapshot ID: 2026-02-04_21-30-00")
    
    # This list comes from our MetadataTracker!
    changed_files = [
        "documents/report_final.pdf",
        "photos/vacation/img_001.jpg",
        "config/settings.json"
    ]
    print(f"    Detected {len(changed_files)} changed files to sync.")
    
    # 2. Simulate Upload
    base_dir = "/tmp/autobackup_demo/source"
    os.makedirs(f"{base_dir}/documents", exist_ok=True)
    os.makedirs(f"{base_dir}/photos/vacation", exist_ok=True)
    os.makedirs(f"{base_dir}/config", exist_ok=True)
    
    # Create dummy files
    for f in changed_files:
        with open(f"{base_dir}/{f}", "w") as fp:
            fp.write("dummy content " * 100)
            
    print("\n[2] 🚀 Starting S3 Uploader...")
    print("    Provider: AWS S3")
    print("    Bucket:   my-secure-backup-bucket")
    print("    Prefix:   linux-desktop-01/2026-02-04_21-30-00/")
    
    # Note: We mock the client for the specific demo to avoid needing real creds
    # In a real run, this would connect to AWS
    uploader = S3Uploader("my-secure-backup-bucket")
    
    # Use a mock client for demonstration if real boto3 fails connection/creds
    class MockS3Client:
        def head_bucket(self, Bucket): pass
        def upload_file(self, Filename, Bucket, Key, Config=None, ExtraArgs=None, Callback=None):
            time.sleep(0.2) # Simulate latency
            pass
            
    if not uploader.connect():
        print("    (Using Mock S3 Client for simulation)")
        uploader.s3_client = MockS3Client()
        
    stats = uploader.upload_incremental(
        source_root=base_dir,
        file_list=changed_files,
        remote_prefix="linux-desktop-01/2026-02-04_21-30-00/"
    )
    
    print("\n[3] ✅ Cloud Sync Complete.")
    print(f"    Uploaded: {stats['files']} files")
    print("    Storage Class: STANDARD_IA (Cost Optimized)")
    print("    Encryption: AES256 (Enabled)")

if __name__ == "__main__":
    demo_cloud_workflow()
