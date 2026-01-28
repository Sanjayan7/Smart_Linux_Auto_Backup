
# Automated Backup Tool

A simple, configurable, and automated backup tool written in Python. This tool creates compressed backups of a specified directory, stores them with a timestamp, and automatically cleans up old backups.

## Features

-   **Easy Configuration**: All settings are managed in a simple `backup.conf` file.
-   **Compressed Backups**: Creates `.tar.gz` archives to save space.
-   **Timestamped**: Backup files are named with the date and time of creation.
-   **Exclusion Patterns**: Specify files or directories to exclude from backups using glob patterns.
-   **Basic Restore Functionality**: Extract backup archives to a specified location.
-   **Logging**: Records all operations, errors, and activities to a log file (`backup.log`).
-   **Backup Rotation**: Automatically deletes backups older than a configurable number of days.
-   **Flexible**: Command-line arguments can be used to override settings in the configuration file.

## Project Structure

```
autobackup/
├── backup.py         # The command-line interface (CLI) script
├── backup_core.py    # Contains the core backup, restore, and rotation logic
├── backup.conf       # Configuration file
├── backup.log        # Log file (created on first run)
└── README.md         # This file
```

## How to Use

This tool now supports both a Command-Line Interface (CLI) and will soon have a Graphical User Interface (GUI) powered by Tkinter.

### 1. Configure the Backup

Edit the `backup.conf` file to set your backup parameters.

```ini
[Backup]
# The source directory you want to back up.
# IMPORTANT: Use absolute paths for reliability, especially with cron.
# Example: /home/user/documents
source_dir = /home/sanjayan/Arch_Proj/my_important_data

# The destination directory where backups will be stored.
# IMPORTANT: Use absolute paths.
# Example: /home/user/backups
dest_dir = /home/sanjayan/Arch_Proj/my_backup_storage

# Number of days to keep backups. Older backups will be deleted.
# Set to 0 to disable automatic deletion.
retention_days = 7

# Comma-separated list of glob patterns to exclude from backup.
# Example: *.log, __pycache__/, .git/
excludes = *.log, __pycache__/

[Logging]
# The file to store log messages.
log_file = backup.log
```

**Important:** You **must** change the `source_dir` and `dest_dir` placeholders to actual, absolute paths on your system if you are setting up this project yourself.

### 2. Command-Line Interface (CLI) Usage

The `backup.py` script now uses subcommands for different operations.

#### 2.1. Perform a Backup

To trigger a backup manually using the CLI:

```bash
python3 backup.py backup
```

The script will use the settings from `backup.conf`. You can also override these settings with command-line arguments:

```bash
# Back up a different directory
python3 backup.py backup --source /path/to/another/folder

# Back up to a different destination and exclude specific files
python3 backup.py backup --dest /path/to/another/destination --exclude "*.tmp" "log/*.log"

# Override retention policy
python3 backup.py backup --retention 14
```

#### 2.2. Restore a Backup

To restore an existing backup archive:

```bash
python3 backup.py restore /path/to/your/backup_file.tar.gz /path/to/restore/destination
```

#### 2.3. View Help

To see all available commands and options:

```bash
python3 backup.py --help
python3 backup.py backup --help
python3 backup.py restore --help
```

### 3. Schedule Automatic Backups with Cron

To make the backup process automatic, you can schedule it to run at regular intervals using `cron`.

1.  Open your crontab file for editing:
    ```bash
    crontab -e
    ```

2.  Add a new line to the file to schedule the `backup.py` script. The syntax is:
    `MIN HOUR DAY(month) MONTH DAY(week) /path/to/python3 /path/to/backup.py [subcommand] [options]`

    **Example:** To run the **backup subcommand** every day at 2:30 AM:

    ```
    30 2 * * * /usr/bin/python3 /home/sanjayan/Arch_Proj/autobackup/backup.py backup
    ```

    **IMPORTANT**: You **must** use absolute paths for both the Python interpreter (`/usr/bin/python3`) and the `backup.py` script. The paths in the example above are illustrative; make sure to use the correct paths for your system. You can find the path to your Python 3 executable by running `which python3`.

3.  Save and close the crontab file. Cron will now automatically execute your backup script at the scheduled time. Check the `backup.log` file to ensure it's running as expected.
