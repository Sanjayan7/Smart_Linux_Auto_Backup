import subprocess
import re
import os
from typing import List, Callable, Optional, Dict, Any
from autobackup.utils.logger import logger

class RsyncEngine:
    def __init__(self):
        self._process: Optional[subprocess.Popen] = None

    def run_rsync(
                      self,
                      source: str,
                      destination: str,
                      exclude_patterns: List[str],
                      dry_run: bool = False,
                      progress_callback: Optional[Callable[[dict], None]] = None,
                      link_dest: Optional[str] = None,
                      compress: bool = False) -> Dict[str, Any]: # New parameter for compression
        """
        Executes rsync command and provides real-time progress.
        Returns a dictionary with backup summary statistics.
        """
        rsync_cmd = [
            'rsync',
            '-aHv', # Archive mode, human-readable, verbose
            '--info=progress2', # Show overall progress
            '--stats', # Give a brief summary at the end
            '--delete-excluded' # Essential for proper incremental with excludes
        ]

        if dry_run:
            rsync_cmd.append('--dry-run')
            logger.info("Performing a dry-run backup.")

        if compress: # Add compression flag if enabled
            rsync_cmd.append('--compress')
            logger.info("Compression enabled for rsync.")

        if link_dest:
            if os.path.isabs(link_dest):
                rsync_cmd.extend([f'--link-dest={link_dest}/']) # Add trailing slash
                logger.info(f"Using --link-dest={link_dest}/ for incremental backup.")
            else:
                logger.warning(f"Skipping --link-dest because path is not absolute: {link_dest}")


        for pattern in exclude_patterns:
            if pattern:
                rsync_cmd.extend(['--exclude', pattern])

        # Ensure source ends with a slash for "contents of directory" behavior
        if not source.endswith(os.sep):
            source += os.sep

        rsync_cmd.extend([source, destination])

        logger.info(f"Executing rsync command: {' '.join(rsync_cmd)}")

        full_output = []
        start_time = None
        end_time = None

        try:
            start_time = os.times().elapsed
            self._process = subprocess.Popen(
                rsync_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Redirect stderr to stdout for easier parsing
                text=True,
                bufsize=1, # Line-buffered output
                universal_newlines=True
            )

            # Regex to parse rsync --info=progress2 output
            progress_pattern = re.compile(
                r'^\s*(?P<total_bytes>[0-9,]+)\s+'
                r'(?P<percentage>\d+)%\s+'
                r'(?P<speed>[\d.]+\w+/s)\s+'
                r'(?P<eta>\d+:\d+:\d+|\d+:\d+)\s+'
                r'.*to-chk=(?P<to_check>\d+/\d+)'
            )

            for line in self._process.stdout:
                full_output.append(line)
                match = progress_pattern.match(line)
                if match:
                    progress_data = match.groupdict()
                    if progress_callback:
                        progress_callback(progress_data)
                elif 'rsync error:' in line.lower():
                    logger.error(f"Rsync error: {line.strip()}")

            self._process.wait()
            end_time = os.times().elapsed

            if self._process.returncode != 0:
                error_message = f"Rsync command failed with exit code {self._process.returncode}. Output:\n{''.join(full_output)}"
                logger.error(error_message)
                raise RuntimeError(error_message)

            return self._parse_rsync_stats(''.join(full_output), (end_time - start_time) if start_time and end_time else 0.0)

        except FileNotFoundError:
            error_message = "Rsync command not found. Please ensure rsync is installed and in your PATH."
            logger.error(error_message)
            raise RuntimeError(error_message)
        except Exception as e:
            logger.error(f"An unexpected error occurred during rsync: {e}")
            raise

    def _parse_rsync_stats(self, output: str, duration: float) -> Dict[str, Any]:
        """Parses the rsync --stats output for summary information."""
        summary = {
            "files_transferred": 0,
            "total_size_bytes": 0,
            "duration_seconds": duration,
            "total_files_read": 0,
            "total_files_written": 0,
            "total_file_size": 0,
            "number_of_files": 0
        }

        # Regex patterns for various stats
        total_size_pattern = re.compile(r"Total file size: ([\d,\.]+)\s*(.B|K.B|M.B|G.B|T.B)")
        number_of_files_pattern = re.compile(r"Number of files: ([\d,]+)")
        files_transferred_pattern = re.compile(r"Number of files transferred: ([\d,]+)")
        total_read_pattern = re.compile(r"Total transferred file size: ([\d,\.]+)\s*(.B|K.B|M.B|G.B|T.B)") # This is the actual data transferred
        
        # New: Total bytes sent/received over network (more accurate for network usage)
        total_bytes_sent_pattern = re.compile(r"Total bytes sent: ([\d,]+)")
        total_bytes_received_pattern = re.compile(r"Total bytes received: ([\d,]+)")


        def parse_size_to_bytes(size_str: str, unit_str: str) -> int:
            size = float(size_str.replace(',', ''))
            unit_map = {
                "B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4,
                "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4
            }
            # Handle units with dots like "K.B"
            unit_str = unit_str.replace('.', '') 
            return int(size * unit_map.get(unit_str, 1))

        for line in output.splitlines():
            if "Number of files transferred:" in line:
                match = files_transferred_pattern.search(line)
                if match:
                    summary["files_transferred"] = int(match.group(1).replace(',', ''))
            elif "Number of files:" in line:
                match = number_of_files_pattern.search(line)
                if match:
                    summary["number_of_files"] = int(match.group(1).replace(',', ''))
            elif "Total file size:" in line:
                match = total_size_pattern.search(line)
                if match:
                    summary["total_file_size"] = parse_size_to_bytes(match.group(1), match.group(2))
            elif "Total transferred file size:" in line:
                match = total_read_pattern.search(line)
                if match:
                    # This might be ambiguous with total_file_size, let's keep it separate for now.
                    # This represents the size of data that was actually written/transferred.
                    summary["total_size_bytes"] = parse_size_to_bytes(match.group(1), match.group(2))
            elif "Total bytes sent:" in line:
                match = total_bytes_sent_pattern.search(line)
                if match:
                    summary["total_bytes_sent"] = int(match.group(1).replace(',', ''))
            elif "Total bytes received:" in line:
                match = total_bytes_received_pattern.search(line)
                if match:
                    summary["total_bytes_received"] = int(match.group(1).replace(',', ''))


        return summary

    def stop_rsync(self):
        if self._process and self._process.poll() is None:
            logger.info("Terminating rsync process.")
            self._process.terminate()
            self._process.wait(timeout=5)
            if self._process.poll() is None:
                logger.warning("Rsync process did not terminate, killing it.")
                self._process.kill()
            logger.info("Rsync process terminated.")