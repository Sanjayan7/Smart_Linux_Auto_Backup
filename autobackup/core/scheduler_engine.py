"""
scheduler_engine.py
===================
Background scheduler for automatic backups.

Uses a single daemon thread that sleeps until the next scheduled time,
then triggers a backup callback.  Thread-safe stop/start.

Modes
-----
  • daily    — runs once per day at a specific HH:MM
  • weekly   — runs once per week on a specific day at HH:MM
  • custom   — runs every N minutes

Thread safety
-------------
  • The scheduler thread is a daemon — it dies when the main app exits.
  • A threading.Event is used for cancellable sleep so stop() is instant.
  • Double-start is prevented by checking _running before launching.
"""

import datetime
import threading
import time
from typing import Callable, Optional

from autobackup.utils.logger import logger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DAYS_OF_WEEK = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]

FREQUENCY_DAILY   = "daily"
FREQUENCY_WEEKLY  = "weekly"
FREQUENCY_CUSTOM  = "custom"


# ---------------------------------------------------------------------------
# SchedulerEngine
# ---------------------------------------------------------------------------

class SchedulerEngine:
    """
    Background scheduler that triggers a callback at configured intervals.

    Parameters
    ----------
    backup_callback : callable
        Called (with no arguments) when a scheduled backup should start.
        Must be thread-safe — e.g. use `widget.after(0, func)` if it
        touches the UI.
    status_callback : callable, optional
        Called with a status string for UI display.
    """

    def __init__(
        self,
        backup_callback: Callable[[], None],
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        self._backup_cb = backup_callback
        self._status_cb = status_callback or (lambda msg: None)

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._lock = threading.Lock()

        # Schedule configuration (set via configure())
        self.frequency: str = FREQUENCY_DAILY
        self.time_str: str = "22:00"       # HH:MM for daily/weekly
        self.day_of_week: str = "Sunday"   # for weekly
        self.interval_minutes: int = 60    # for custom

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def configure(
        self,
        frequency: str = FREQUENCY_DAILY,
        time_str: str = "22:00",
        day_of_week: str = "Sunday",
        interval_minutes: int = 60,
    ) -> None:
        """Update schedule parameters.  Call before start()."""
        self.frequency = frequency
        self.time_str = time_str
        self.day_of_week = day_of_week
        self.interval_minutes = max(1, interval_minutes)

    def start(self) -> None:
        """Start the scheduler in a background thread."""
        with self._lock:
            if self._running:
                logger.info("Scheduler already running — ignoring duplicate start.")
                return
            self._stop_event.clear()
            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop,
                name="SchedulerThread",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                f"Scheduler started: {self.frequency}, "
                f"time={self.time_str}, day={self.day_of_week}, "
                f"interval={self.interval_minutes}m"
            )
            self._status_cb(f"⏰ Scheduler active ({self._describe()})")

    def stop(self) -> None:
        """Stop the scheduler.  Returns immediately."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
            logger.info("Scheduler stopped.")
            self._status_cb("⏸ Scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def next_run_description(self) -> str:
        """Human-readable description of next scheduled run."""
        return self._describe()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _describe(self) -> str:
        """Human-readable schedule description."""
        if self.frequency == FREQUENCY_DAILY:
            return f"Daily at {self.time_str}"
        elif self.frequency == FREQUENCY_WEEKLY:
            return f"Every {self.day_of_week} at {self.time_str}"
        else:
            return f"Every {self.interval_minutes} minute(s)"

    def _run_loop(self) -> None:
        """Main scheduler loop — runs in a daemon thread."""
        logger.info(f"Scheduler thread started: {self._describe()}")
        try:
            while not self._stop_event.is_set():
                delay = self._seconds_until_next()
                logger.info(
                    f"Scheduler: next backup in {delay:.0f}s "
                    f"({delay / 60:.1f} min)"
                )
                self._status_cb(
                    f"⏰ Next backup in {self._format_delay(delay)}"
                )

                # Cancellable sleep
                if self._stop_event.wait(timeout=delay):
                    break  # stop() was called

                if self._stop_event.is_set():
                    break

                # Time to run
                logger.info("Scheduler: triggering scheduled backup")
                self._status_cb("⏰ Scheduled backup starting...")
                try:
                    self._backup_cb()
                except Exception as exc:
                    logger.error(f"Scheduled backup error: {exc}")

        except Exception as exc:
            logger.error(f"Scheduler thread crashed: {exc}")
        finally:
            with self._lock:
                self._running = False
            logger.info("Scheduler thread exited.")

    def _seconds_until_next(self) -> float:
        """Calculate seconds until the next scheduled run."""
        now = datetime.datetime.now()

        if self.frequency == FREQUENCY_CUSTOM:
            return self.interval_minutes * 60.0

        # Parse target time
        try:
            hour, minute = map(int, self.time_str.split(":"))
        except (ValueError, AttributeError):
            hour, minute = 22, 0  # fallback

        if self.frequency == FREQUENCY_DAILY:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            return (target - now).total_seconds()

        elif self.frequency == FREQUENCY_WEEKLY:
            try:
                target_day_idx = DAYS_OF_WEEK.index(self.day_of_week)
            except ValueError:
                target_day_idx = 6  # Sunday fallback

            current_day_idx = now.weekday()  # Monday=0 .. Sunday=6
            days_ahead = (target_day_idx - current_day_idx) % 7

            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            target += datetime.timedelta(days=days_ahead)

            if target <= now:
                target += datetime.timedelta(weeks=1)

            return (target - now).total_seconds()

        # Unknown frequency — default 1 hour
        return 3600.0

    @staticmethod
    def _format_delay(seconds: float) -> str:
        """Format seconds into a human-readable string."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        minutes = seconds / 60
        if minutes < 60:
            return f"{minutes:.0f}m"
        hours = minutes / 60
        if hours < 24:
            return f"{hours:.1f}h"
        days = hours / 24
        return f"{days:.1f}d"
