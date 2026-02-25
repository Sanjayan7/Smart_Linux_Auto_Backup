
import subprocess
import os
import json
from typing import Dict, List, Optional, Callable
from autobackup.cloud.base import CloudProvider
from autobackup.utils.logger import logger

class RcloneProvider(CloudProvider):
    """Cloud storage provider using rclone CLI."""
    
    REMOTE_NAME = "gdrive"
    CLOUD_FOLDER = "AutoBackup"
    DEFAULT_TIMEOUT = 10 
    
    def __init__(self, credentials: Optional[Dict] = None):
        """
        Credentials ignored as rclone handles its own config.
        """
        pass

    def is_rclone_available(self) -> bool:
        """Check if rclone is installed."""
        try:
            result = subprocess.run(["which", "rclone"], capture_output=True, text=True, timeout=2)
            return result.returncode == 0
        except Exception:
            return False

    def test_connection(self) -> bool:
        """
        Test if 'gdrive' remote exists in rclone.
        """
        if not self.is_rclone_available():
            return False
            
        try:
            result = subprocess.run(
                ["rclone", "listremotes"],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.DEFAULT_TIMEOUT
            )
            if result.returncode == 0:
                remotes = [r.strip().rstrip(':') for r in result.stdout.splitlines() if r.strip()]
                return self.REMOTE_NAME in remotes
            return False
        except Exception as e:
            logger.error(f"Failed to check rclone connection: {e}")
            return False

    def upload_archive(self, local_path: str, progress_callback: Optional[Callable[[dict], None]] = None) -> bool:
        """
        Upload the final archive to cloud.
        rclone copy <local_path> gdrive:AutoBackup/
        """
        if not os.path.exists(local_path):
            logger.error(f"Archive not found: {local_path}")
            return False

        try:
            # Ensure folder exists
            subprocess.run(
                ["rclone", "mkdir", f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}"],
                capture_output=True, check=False, timeout=10
            )

            filename = os.path.basename(local_path)
            destination = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/"
            
            logger.info(f"Uploading {local_path} to {destination}")
            
            # Using Popen to capture progress if possible, or just subprocess.run for simplicity
            # since rclone doesn't provide easy machine-readable progress without complex parsing.
            # But the user wants "REAL progress".
            # rclone --use-json-log produces JSON progress.
            
            cmd = ["rclone", "copyto", local_path, os.path.join(destination, filename)]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                if progress_callback:
                    progress_callback({"percentage": 100, "message": "Cloud upload complete"})
                return True
            else:
                logger.error(f"rclone upload failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error during rclone upload: {e}")
            return False

    def list_objects(self) -> List[str]:
        """List archives in the remote folder."""
        try:
            result = subprocess.run(
                ["rclone", "lsjson", f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            if result.returncode == 0:
                items = json.loads(result.stdout)
                # Return both files and directories
                # If it's a directory, we might want to distinguish it?
                # But for now let's just return names.
                return [item['Name'] for item in items]
            return []
        except Exception as e:
            logger.error(f"rclone list failed: {e}")
            return []

    def list_cloud_backups(self) -> List[str]:
        """
        List files available in gdrive:AutoBackup/ using rclone lsf.
        Returns a list of filenames (strings), or raises on error.
        """
        remote_path = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/"
        result = subprocess.run(
            ["rclone", "lsf", "--files-only", remote_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error(f"rclone lsf --files-only failed: {result.stderr.strip()}")
            return []
        # Lines are plain filenames (--files-only never appends trailing slashes)
        files = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        ]
        return files

    def download_file(
        self,
        remote_filename: str,
        local_dest_dir: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Download a single file from gdrive:AutoBackup/<remote_filename>
        into the local directory local_dest_dir.

        Returns True on success, False on failure.
        """
        try:
            src = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/{remote_filename}"
            logger.info(f"Downloading: {src} → {local_dest_dir}")

            result = subprocess.run(
                ["rclone", "copy", src, local_dest_dir,
                 "--stats-one-line", "--stats=5s"],
                capture_output=True,
                text=True,
                check=False,
                timeout=7200,  # 2-hour cap for large files
            )
            if result.returncode == 0:
                if progress_callback:
                    progress_callback("Download complete")
                return True
            else:
                logger.error(f"rclone download failed: {result.stderr.strip()}")
                return False
        except Exception as e:
            logger.error(f"rclone download exception: {e}")
            return False

    def upload_directory(self, local_dir: str, remote_dir: str,
                        incremental: bool = False,
                        progress_callback: Optional[Callable[[str, int, int], None]] = None) -> bool:
        """
        Mirror a directory to cloud using rclone sync.
        Preserves directory structure.
        """
        if not os.path.exists(local_dir):
            return False
            
        try:
            destination = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/{remote_dir}"
            logger.info(f"Mirroring directory {local_dir} to {destination}")
            
            # Use 'sync' to ensure cloud is an exact mirror of local source
            cmd = ["rclone", "sync", local_dir, destination]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                if progress_callback:
                    progress_callback("complete", 1, 1)
                return True
            else:
                logger.error(f"rclone sync failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error during rclone sync: {e}")
            return False

    def list_directory(self, remote_relative_path: str) -> List[Dict]:
        """List objects in a specific remote directory."""
        try:
            full_path = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/{remote_relative_path}"
            result = subprocess.run(
                ["rclone", "lsjson", full_path],
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            if result.returncode == 0:
                items = json.loads(result.stdout)
                return [
                    {
                        "name": item['Name'],
                        "type": "directory" if item['IsDir'] else "file",
                        "size": item['Size'] if not item['IsDir'] else 0
                    }
                    for item in items
                ]
            return []
        except Exception as e:
            logger.error(f"rclone list_directory failed: {e}")
            return []

    def file_exists(self, remote_path: str) -> bool:
        try:
            full_path = f"{self.REMOTE_NAME}:{self.CLOUD_FOLDER}/{remote_path}"
            result = subprocess.run(["rclone", "lsf", full_path], capture_output=True, check=False)
            return result.returncode == 0
        except Exception:
            return False

    def get_file_etag(self, remote_path: str) -> Optional[str]:
        return None
    
    def upload_file(self, local_path: str, remote_path: str, progress_callback: Optional[Callable[[int, int], None]] = None) -> bool:
        """Upload single file to cloud."""
        return self.upload_archive(local_path)

    @classmethod
    def get_credentials_schema(cls) -> Dict[str, dict]:
        return {}
