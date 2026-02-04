"""
Secure credential management for cloud providers.

Uses system keyring for secure credential storage.
"""

import json
from typing import Dict, Optional
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    
from autobackup.utils.logger import logger


class CredentialManager:
    """Manage cloud provider credentials securely"""
    
    SERVICE_NAME = "AutoBackup_Cloud"
    
    def __init__(self, provider_name: str):
        """
        Initialize credential manager.
        
        Args:
            provider_name: Name of cloud provider (e.g., 's3', 'gdrive')
        """
        self.provider_name = provider_name
        self.key_name = f"{provider_name}_credentials"
    
    def save_credentials(self, credentials: Dict[str, str]) -> bool:
        """
        Save credentials securely.
        
        Args:
            credentials: Dict of credential key-value pairs
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if KEYRING_AVAILABLE:
                # Use system keyring for secure storage
                creds_json = json.dumps(credentials)
                keyring.set_password(self.SERVICE_NAME, self.key_name, creds_json)
                logger.info(f"Credentials saved securely for {self.provider_name}")
                return True
            else:
                # Fallback: save to file (less secure, but functional)
                logger.warning("Keyring not available, using file-based storage (less secure)")
                import os
                creds_dir = os.path.expanduser("~/.autobackup")
                os.makedirs(creds_dir, exist_ok=True)
                os.chmod(creds_dir, 0o700)  # Owner-only permissions
                
                creds_file = os.path.join(creds_dir, f"{self.key_name}.json")
                with open(creds_file, 'w') as f:
                    json.dump(credentials, f)
                os.chmod(creds_file, 0o600)  # Owner-only read/write
                logger.info(f"Credentials saved to file for {self.provider_name}")
                return True
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
            return False
    
    def load_credentials(self) -> Optional[Dict[str, str]]:
        """
        Load saved credentials.
        
        Returns:
            Dict of credentials or None if not found
        """
        try:
            if KEYRING_AVAILABLE:
                # Load from system keyring
                creds_json = keyring.get_password(self.SERVICE_NAME, self.key_name)
                if creds_json:
                    credentials = json.loads(creds_json)
                    logger.info(f"Credentials loaded for {self.provider_name}")
                    return credentials
                else:
                    logger.info(f"No saved credentials found for {self.provider_name}")
                    return None
            else:
                # Load from file
                import os
                creds_file = os.path.join(os.path.expanduser("~/.autobackup"), 
                                         f"{self.key_name}.json")
                if os.path.exists(creds_file):
                    with open(creds_file, 'r') as f:
                        credentials = json.load(f)
                    logger.info(f"Credentials loaded from file for {self.provider_name}")
                    return credentials
                else:
                    logger.info(f"No saved credentials found for {self.provider_name}")
                    return None
        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
            return None
    
    def delete_credentials(self) -> bool:
        """
        Delete saved credentials.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if KEYRING_AVAILABLE:
                keyring.delete_password(self.SERVICE_NAME, self.key_name)
                logger.info(f"Credentials deleted for {self.provider_name}")
                return True
            else:
                import os
                creds_file = os.path.join(os.path.expanduser("~/.autobackup"), 
                                         f"{self.key_name}.json")
                if os.path.exists(creds_file):
                    os.remove(creds_file)
                logger.info(f"Credentials deleted for {self.provider_name}")
                return True
        except Exception as e:
            logger.error(f"Failed to delete credentials: {e}")
            return False
    
    def has_credentials(self) -> bool:
        """
        Check if credentials are saved.
        
Returns:
            True if credentials exist, False otherwise
        """
        return self.load_credentials() is not None
