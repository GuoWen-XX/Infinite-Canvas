import os
import json
import time
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple, Callable

logger = logging.getLogger("infinite_canvas.canvas_cache")


class CanvasCache:
    """High-performance mtime-based metadata cache for canvases.

    Avoids OOM and eliminates reading/parsing hundreds of large canvas graph JSONs
    on every single listing/poll request.
    """

    def __init__(
        self,
        canvas_dir: str,
        record_builder: Callable[[Dict[str, Any]], Dict[str, Any]],
        trash_retention_ms: int = 30 * 86400 * 1000,
        cleanup_interval_sec: float = 300.0,
    ):
        self.canvas_dir = os.path.abspath(canvas_dir)
        self.record_builder = record_builder
        self.trash_retention_ms = trash_retention_ms
        self.cleanup_interval_sec = cleanup_interval_sec

        self._lock = threading.Lock()
        # filename -> {"mtime_ns": int, "record": dict, "deleted_at": int}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._last_cleanup_time = 0.0

    def iter_records(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """List canvas records with mtime caching.

        Uses os.scandir for high-speed directory traversal. Only modified or new
        files are read from disk.
        """
        self.cleanup_expired_trash_if_needed()

        if not os.path.exists(self.canvas_dir):
            return []

        active_filenames = set()
        records_to_return = []

        with self._lock:
            try:
                with os.scandir(self.canvas_dir) as scanner:
                    for entry in scanner:
                        if not entry.name.endswith(".json") or not entry.is_file():
                            continue

                        active_filenames.add(entry.name)
                        try:
                            stat_info = entry.stat()
                            mtime_ns = stat_info.st_mtime_ns
                        except Exception:
                            continue

                        cached = self._cache.get(entry.name)
                        if cached and cached.get("mtime_ns") == mtime_ns:
                            # Cache HIT: instant reuse without JSON parse
                            is_deleted = bool(cached.get("deleted_at"))
                            if is_deleted == include_deleted:
                                records_to_return.append(dict(cached["record"]))
                            continue

                        # Cache MISS: read and parse
                        try:
                            with open(entry.path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            record = self.record_builder(data)
                            deleted_at = int(data.get("deleted_at") or 0)
                            self._cache[entry.name] = {
                                "mtime_ns": mtime_ns,
                                "record": record,
                                "deleted_at": deleted_at,
                            }
                            if bool(deleted_at) == include_deleted:
                                records_to_return.append(dict(record))
                        except Exception as exc:
                            logger.debug(f"Failed to read canvas file {entry.name}: {exc}")
                            continue

            except Exception as exc:
                logger.error(f"Failed to scan canvas directory: {exc}")
                return []

            # Purge cache entries for files that no longer exist
            stale_keys = set(self._cache.keys()) - active_filenames
            for key in stale_keys:
                self._cache.pop(key, None)

        return records_to_return

    def get_record(self, filename: str) -> Optional[Dict[str, Any]]:
        """Get cached record for a specific canvas filename, updating on mtime change."""
        file_path = os.path.join(self.canvas_dir, filename)
        if not os.path.exists(file_path):
            with self._lock:
                self._cache.pop(filename, None)
            return None

        try:
            mtime_ns = os.stat(file_path).st_mtime_ns
        except Exception:
            return None

        with self._lock:
            cached = self._cache.get(filename)
            if cached and cached.get("mtime_ns") == mtime_ns:
                if cached.get("deleted_at"):
                    return None
                return dict(cached["record"])

            # Cache miss: read and parse once
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                record = self.record_builder(data)
                deleted_at = int(data.get("deleted_at") or 0)
                self._cache[filename] = {
                    "mtime_ns": mtime_ns,
                    "record": record,
                    "deleted_at": deleted_at,
                }
                if deleted_at:
                    return None
                return dict(record)
            except Exception as exc:
                logger.debug(f"Failed to read canvas file {filename}: {exc}")
                return None

    def update(self, filename: str, data: Dict[str, Any]) -> None:
        """Explicitly update or populate the cache entry for a canvas."""
        with self._lock:
            try:
                record = self.record_builder(data)
                deleted_at = int(data.get("deleted_at") or 0)
                file_path = os.path.join(self.canvas_dir, filename)
                mtime_ns = os.stat(file_path).st_mtime_ns if os.path.exists(file_path) else int(time.time() * 1e9)
                self._cache[filename] = {
                    "mtime_ns": mtime_ns,
                    "record": record,
                    "deleted_at": deleted_at,
                }
            except Exception as exc:
                logger.debug(f"Cache update error for {filename}: {exc}")

    def invalidate(self, filename: str) -> None:
        """Evict a canvas from cache when deleted."""
        with self._lock:
            self._cache.pop(filename, None)

    def cleanup_expired_trash_if_needed(self, force: bool = False) -> int:
        """Clean up expired trash canvases, throttled to prevent redundant disk churn."""
        now = time.time()
        if not force and (now - self._last_cleanup_time < self.cleanup_interval_sec):
            return 0

        self._last_cleanup_time = now
        cutoff_ms = int(now * 1000) - self.trash_retention_ms
        removed_count = 0

        if not os.path.exists(self.canvas_dir):
            return 0

        with self._lock:
            try:
                with os.scandir(self.canvas_dir) as scanner:
                    for entry in scanner:
                        if not entry.name.endswith(".json") or not entry.is_file():
                            continue

                        # Check cache first to avoid parsing non-deleted or non-expired files
                        cached = self._cache.get(entry.name)
                        deleted_at = cached.get("deleted_at", 0) if cached else None

                        if deleted_at is None:
                            try:
                                with open(entry.path, "r", encoding="utf-8") as f:
                                    data = json.load(f)
                                deleted_at = int(data.get("deleted_at") or 0)
                            except Exception:
                                continue

                        if deleted_at and 1577836800000 < deleted_at <= cutoff_ms:
                            try:
                                os.remove(entry.path)
                                self._cache.pop(entry.name, None)
                                removed_count += 1
                            except Exception as exc:
                                logger.warning(f"Failed to remove expired canvas trash {entry.name}: {exc}")
            except Exception as exc:
                logger.error(f"Error during trash cleanup: {exc}")

        return removed_count
