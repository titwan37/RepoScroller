"""In-memory diagnostic ring buffer and system health telemetry for live reporting."""

import collections
import logging
import os
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from reposcroller.config import settings


class InMemoryDiagnosticHandler(logging.Handler):
    """Thread-safe circular buffer capturing log records for real-time frontend reporting."""

    def __init__(self, capacity: int = 400):
        super().__init__()
        self.capacity = capacity
        self.buffer = collections.deque(maxlen=capacity)
        self.lock = threading.RLock()
        self._next_id = 1
        self.start_time = time.time()
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            exc = None
            if record.exc_info:
                exc = logging.Formatter().formatException(record.exc_info)
            with self.lock:
                entry = {
                    "id": self._next_id,
                    "timestamp": time.strftime("%H:%M:%S", time.localtime(record.created)),
                    "iso_timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": msg,
                    "exception": exc,
                    "source": "backend"
                }
                self._next_id += 1
                self.buffer.append(entry)
        except Exception:
            self.handleError(record)

    def log_frontend_issue(self, message: str, stack: Optional[str] = None, level: str = "ERROR", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Record an issue reported by the frontend client into the unified diagnostic log."""
        with self.lock:
            entry = {
                "id": self._next_id,
                "timestamp": time.strftime("%H:%M:%S"),
                "iso_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "level": level.upper(),
                "logger": "frontend.client",
                "message": message,
                "exception": stack,
                "extra": extra or {},
                "source": "frontend"
            }
            self._next_id += 1
            self.buffer.append(entry)
            return entry

    def get_logs(self, since_id: int = 0, limit: int = 200, min_level: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve recent log events optionally filtered by level and ID watermark."""
        level_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        min_val = level_map.get(min_level.upper(), 0) if min_level else 0

        with self.lock:
            results = [
                entry for entry in self.buffer
                if entry["id"] > since_id and level_map.get(entry["level"], 0) >= min_val
            ]
            return results[-limit:]

    def clear(self) -> None:
        """Clear all buffered diagnostic logs."""
        with self.lock:
            self.buffer.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate log counts by severity."""
        with self.lock:
            counts = {"total": len(self.buffer), "ERROR": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0}
            for e in self.buffer:
                lvl = e.get("level", "INFO")
                if lvl in counts:
                    counts[lvl] += 1
                else:
                    counts[lvl] = 1
            return counts


# Singleton in-memory diagnostic buffer
diagnostic_buffer = InMemoryDiagnosticHandler(capacity=500)


def setup_diagnostic_logging() -> None:
    """Attach the in-memory diagnostic handler to root and application loggers."""
    app_logger = logging.getLogger("reposcroller")
    app_logger.setLevel(logging.DEBUG)
    diagnostic_buffer.setLevel(logging.DEBUG)

    if diagnostic_buffer not in app_logger.handlers:
        app_logger.addHandler(diagnostic_buffer)


# Automatically initialize diagnostic logging on import
setup_diagnostic_logging()


def get_system_health() -> Dict[str, Any]:
    """Gather live runtime health, storage mount connectivity, and database telemetry."""
    now = time.time()
    uptime_seconds = int(now - diagnostic_buffer.start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_formatted = f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"

    # Database file stats
    db_file = Path(settings.DB_PATH)
    db_exists = db_file.exists()
    db_size_bytes = db_file.stat().st_size if db_exists else 0
    wal_file = Path(f"{settings.DB_PATH}-wal")
    wal_size_bytes = wal_file.stat().st_size if wal_file.exists() else 0

    # Storage mounts accessibility
    roots_status = []
    online_count = 0
    for root in settings.STORAGE_ROOTS:
        accessible = False
        try:
            accessible = os.path.exists(root) and os.path.isdir(root)
        except (OSError, PermissionError):
            accessible = False

        if accessible:
            online_count += 1
        roots_status.append({
            "root": root,
            "accessible": accessible,
            "type": "smb_unc" if root.startswith(r"\\") else "cloud_mount"
        })

    # Active threads
    active_threads = threading.active_count()
    thread_names = [t.name for t in threading.enumerate() if t.is_alive()]
    crawler_workers = [name for name in thread_names if "RepoCrawler" in name or "watchdog" in name.lower()]

    log_stats = diagnostic_buffer.get_stats()

    return {
        "status": "healthy" if log_stats["ERROR"] == 0 else "degraded",
        "uptime_seconds": uptime_seconds,
        "uptime": uptime_formatted,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "active_threads": active_threads,
        "crawler_workers": crawler_workers,
        "database": {
            "path": str(db_file),
            "exists": db_exists,
            "size_kb": round(db_size_bytes / 1024, 2),
            "wal_size_kb": round(wal_size_bytes / 1024, 2),
            "wal_mode": True
        },
        "storage": {
            "total_configured": len(settings.STORAGE_ROOTS),
            "online_count": online_count,
            "roots": roots_status
        },
        "diagnostics": {
            "log_counts": log_stats,
            "has_errors": log_stats["ERROR"] > 0,
            "has_warnings": log_stats["WARNING"] > 0
        }
    }
