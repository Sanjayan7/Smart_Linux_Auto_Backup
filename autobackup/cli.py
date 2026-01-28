import argparse
import os
import sys
import datetime

# Add the parent directory to the Python path to allow importing autobackup modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from autobackup.config.settings import settings
from autobackup.core.backup_manager import BackupManager
from autobackup.utils.logger import logger

def run_cli_backup():
    parser = argparse.ArgumentParser(description="AutoBackup CLI for scheduled backups.")
    # No arguments needed for now, as config is loaded from settings.
    # Future arguments could override config values.
    args = parser.parse_args()

    logger.info("AutoBackup CLI started.")

    try:
        config = settings.get_backup_config()
        manager = BackupManager(config)
        
        # When run from CLI (e.g., cron), we want the backup to run in the main thread
        # of the CLI script, so we don't return until it's done.
        # This simplifies cron management and allows notifications to be sent after completion.
        # The GUI version starts a thread so the UI remains responsive.
        
        # Call the internal _run_backup_in_thread directly
        # For simplicity, we create a dummy job for the CLI run
        job_id = "backup_cli_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        dummy_job = manager._current_job = manager._create_dummy_job_for_cli(job_id, config)
        
        logger.info(f"CLI: Starting backup job: {dummy_job.id}")
        manager._run_backup_in_thread(dummy_job) # Run directly
        
        logger.info("AutoBackup CLI finished.")

    except Exception as e:
        logger.error(f"AutoBackup CLI encountered an error: {e}")
        sys.exit(1) # Exit with an error code

if __name__ == "__main__":
    run_cli_backup()