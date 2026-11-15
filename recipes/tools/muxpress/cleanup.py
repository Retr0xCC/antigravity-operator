"""Signal handling, temporary files lifecycle management, and source cleanup."""

from __future__ import annotations

import atexit
import os
import signal
import sys
from pathlib import Path
from types import FrameType


class TempFileManager:
    """Manages active temporary files and ensures cleanup on normal exit, error, or signal."""

    _active_temps: set[Path] = set()
    _active_subprocesses: set[int] = set()
    _signals_installed: bool = False

    @classmethod
    def register_temp(cls, path: Path) -> None:
        """Register a temporary file to be tracked."""
        cls._active_temps.add(path.resolve())
        cls.ensure_signal_handlers()

    @classmethod
    def unregister_temp(cls, path: Path) -> None:
        """Unregister a temporary file after it has been committed or removed."""
        cls._active_temps.discard(path.resolve())

    @classmethod
    def cleanup_all_temps(cls) -> None:
        """Remove all currently registered temporary files."""
        for path in list(cls._active_temps):
            try:
                if path.is_file():
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        cls._active_temps.clear()

    @classmethod
    def handle_signal(cls, signum: int, frame: FrameType | None) -> None:
        """Handle SIGINT or SIGTERM by cleaning up and exiting."""
        print(f"\n[INTERRUPT] Received signal {signum}. Cleaning up temporary files...", file=sys.stderr)
        cls.cleanup_all_temps()
        # Exit with standard signal exit code
        sys.exit(128 + signum)

    @classmethod
    def ensure_signal_handlers(cls) -> None:
        """Install signal handlers and atexit hook if not already installed."""
        if cls._signals_installed:
            return

        try:
            signal.signal(signal.SIGINT, cls.handle_signal)
            signal.signal(signal.SIGTERM, cls.handle_signal)
            atexit.register(cls.cleanup_all_temps)
            cls._signals_installed = True
        except (ValueError, OSError):
            # Happens if not in main thread (e.g. in some test environments)
            pass


class TempFileGuard:
    """Context manager for safe tracking of a single temporary file."""

    def __init__(self, temp_path: Path):
        self.temp_path = temp_path
        self._committed = False

    @property
    def path(self) -> Path:
        return self.temp_path

    def __enter__(self) -> TempFileGuard:
        TempFileManager.register_temp(self.temp_path)
        return self

    def commit(self) -> None:
        """Mark temp file as committed (e.g. atomically moved to final destination)."""
        self._committed = True
        TempFileManager.unregister_temp(self.temp_path)

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        TempFileManager.unregister_temp(self.temp_path)
        if not self._committed and self.temp_path.is_file():
            try:
                self.temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def safe_cleanup_sources(files: list[Path], verbose: bool = False) -> None:
    """Safely remove source files after successful merge."""
    for file_path in files:
        if not file_path.is_file():
            continue
        try:
            file_path.unlink(missing_ok=True)
            if verbose:
                print(f"    - Removed source file: {file_path.name}")
        except OSError as e:
            if verbose:
                print(f"    ! Failed to remove source file {file_path.name}: {e}", file=sys.stderr)
