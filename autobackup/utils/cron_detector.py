"""
Utility for detecting cron availability on the system.
"""
import shutil
import subprocess
from typing import Tuple


def is_cron_available() -> bool:
    """
    Check if cron (crontab command) is available on the system.
    
    Returns:
        bool: True if crontab command is found, False otherwise.
    """
    return shutil.which("crontab") is not None


def get_cron_status() -> Tuple[bool, str]:
    """
    Get the status of cron availability with a user-friendly message.
    
    Returns:
        Tuple[bool, str]: (is_available, status_message)
    """
    if is_cron_available():
        try:
            # Try to check if cron service is running
            result = subprocess.run(
                ["systemctl", "is-active", "cronie"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip() == "active":
                return True, "✓ Auto-backup available (cron service running)"
            else:
                return True, "⚠️ Cron installed but service may not be active"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # systemctl not available or timeout, but crontab exists
            return True, "✓ Auto-backup available (crontab found)"
    else:
        return False, "⚠️ Auto-backup unavailable (cron not installed)"


def get_short_status_message() -> str:
    """
    Get a short status message for UI display.
    
    Returns:
        str: Short status message
    """
    _, message = get_cron_status()
    return message
