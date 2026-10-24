import os
import time
import json
import copy
import atexit
import logging
import threading
from collections import deque
from typing import List, Dict, Any, Optional, Tuple, Deque

logger = logging.getLogger("infinite_canvas.history")


# 单条字符串的绝对上限。base64 识别放宽后（_looks_like_base64_blob），
# 非 base64 的大型 ASCII 载荷（上游 JSON 错误体、压缩资源、超长无空格 prompt）
# 会原样落盘，而 history.json 在启动时全量加载 —— 因此保留一条与格式无关的硬上限。
MAX_STRING_CHARS = 256 * 1024


def _looks_like_base64_blob(val: str) -> bool:
    if len(val) <= 4096:
        return False
    sample = val[:512]
    # Human text / prompts contain spaces or non-ASCII characters (e.g. CJK)
    if " " in sample or any(ord(c) > 127 for c in sample):
        return False
    base64_charset = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n")
    return all(c in base64_charset for c in sample)


def _sanitize_value(val: Any) -> Tuple[Any, bool]:
    """Recursively sanitize strings, dicts, and lists to strip multi-megabyte base64 blobs while preserving prompts."""
    if isinstance(val, str):
        if val.startswith("data:") and len(val) > 1024:
            return val[:64] + f"...[inline blob stripped ({len(val)} chars)]", True
        if len(val) > MAX_STRING_CHARS:
            # 绝对上限：无论是否像 base64，超过该长度一律截断，避免
            # history.json 无界增长（该文件在启动时被全量读入内存）
            return val[:4096] + f"...[truncated ({len(val)} chars)]", True
        if len(val) > 4096 and not val.startswith(("http://", "https://", "/output/", "/assets/")):
            if _looks_like_base64_blob(val):
                return val[:64] + f"...[inline blob stripped ({len(val)} chars)]", True
        return val, False
    elif isinstance(val, dict):
        changed = False
        new_d = {}
        for k, v in val.items():
            new_v, c = _sanitize_value(v)
            if c:
                changed = True
            new_d[k] = new_v
        return new_d, changed
    elif isinstance(val, list):
        changed = False
        new_l = []
        for item in val:
            new_item, c = _sanitize_value(item)
            if c:
                changed = True
            new_l.append(new_item)
        return new_l, changed
    return val, False


def _sanitize_record_blobs(rec: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Strip or truncate multi-megabyte inline base64 blobs inside history records."""
    if not isinstance(rec, dict):
        return rec, False
    return _sanitize_value(rec)



class HistoryManager:
    """High-performance, non-blocking history manager.

    Eliminates the 28MB synchronous disk read/write bottleneck in the FastAPI event loop
    by keeping an in-memory cache and flushing changes asynchronously.
    """

    def __init__(self, history_file_path: str, max_records: int = 5000, flush_debounce_sec: float = 1.0):
        self.history_file_path = os.path.abspath(history_file_path)
        self.max_records = max_records
        self.flush_debounce_sec = flush_debounce_sec

        self._lock = threading.Lock()
        self._records: Optional[Deque[Dict[str, Any]]] = None
        self._dirty = False
        self._flush_timer: Optional[threading.Timer] = None
        self._flush_lock = threading.Lock()

        # Ensure flush on process exit to avoid lost writes
        atexit.register(self.flush)

    def _load_from_disk(self) -> deque:
        """Loads and sanitizes records from disk with corruption safeguards."""
        records = []
        needs_flush = False
        if os.path.exists(self.history_file_path):
            try:
                with open(self.history_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    # Load all existing records without silent truncation
                    for item in data:
                        cleaned_item, was_cleaned = _sanitize_record_blobs(item)
                        if was_cleaned:
                            needs_flush = True
                        records.append(cleaned_item)
                    if self.max_records and self.max_records > 0 and len(records) > self.max_records:
                        records = records[:self.max_records]
                        needs_flush = True
                else:
                    logger.warning(f"History file {self.history_file_path} is not a list. Initializing empty.")
            except json.JSONDecodeError as jde:
                # Safeguard: Do NOT destroy corrupted file! Back it up!
                backup_path = f"{self.history_file_path}.corrupt-{int(time.time())}"
                logger.error(f"Failed to parse history JSON: {jde}. Backing up to {backup_path}")
                try:
                    os.replace(self.history_file_path, backup_path)
                except Exception as exc:
                    logger.error(f"Failed to backup corrupt history file: {exc}")
                records = []
            except Exception as exc:
                logger.error(f"Error reading history file: {exc}")
                records = []

        if needs_flush:
            self._dirty = True

        maxlen = self.max_records if (self.max_records and self.max_records > 0) else None
        return deque(records[:self.max_records] if maxlen else records, maxlen=maxlen)

    def _ensure_loaded(self) -> None:
        """Loads history from disk once on demand with corruption safeguards."""
        if self._records is not None:
            return

        needs_flush = False
        with self._lock:
            if self._records is not None:
                return

            self._records = self._load_from_disk()
            needs_flush = self._dirty

        # NOTE: Must call _schedule_flush OUTSIDE of self._lock to avoid lock inversion deadlock with flush()
        if needs_flush:
            self._schedule_flush()

    def add_record(self, record: Dict[str, Any]) -> None:
        """Insert a generation record into history. Returns immediately (O(1))."""
        self._ensure_loaded()

        # Defend caller's dict from in-place mutation by deep copying params
        rec = dict(record)
        if isinstance(rec.get("params"), dict):
            rec["params"] = copy.deepcopy(rec["params"])
        rec, _ = _sanitize_record_blobs(rec)
        if "timestamp" not in rec:
            rec["timestamp"] = time.time()

        with self._lock:
            if self._records is None:
                maxlen = self.max_records if (self.max_records and self.max_records > 0) else None
                self._records = deque(maxlen=maxlen)
            self._records.appendleft(rec)
            self._dirty = True

        self._schedule_flush()

    def save(self, record: Dict[str, Any]) -> None:
        """Save a generation record into history. (Calls add_record)."""
        self.add_record(record)

    def list_records(self, record_type: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """List history records with filtering, served purely from memory in <1ms."""
        self._ensure_loaded()

        with self._lock:
            if self._records is None:
                return []
            # Shallow copy to avoid caller mutating our cache
            items = list(self._records)

        if record_type:
            items = [item for item in items if item.get("type", "zimage") == record_type]

        # Only return items with non-empty images (backward compatible with original logic)
        items = [item for item in items if item.get("images") and len(item["images"]) > 0]

        def sort_key(item):
            ts = item.get("timestamp", 0)
            if isinstance(ts, (int, float)):
                return float(ts)
            return 0

        items.sort(key=sort_key, reverse=True)
        if limit and limit > 0:
            return items[:limit]
        if self.max_records and self.max_records > 0:
            return items[:self.max_records]
        return items

    def delete(self, timestamp: Any) -> Optional[Dict[str, Any]]:
        """Delete a record by timestamp. Returns the deleted record if found, or None."""
        self._ensure_loaded()

        target_record = None
        with self._lock:
            if not self._records:
                return None

            maxlen = self.max_records if (self.max_records and self.max_records > 0) else None
            new_records = deque(maxlen=maxlen)
            for item in self._records:
                is_match = False
                item_ts = item.get("timestamp", 0)
                if isinstance(timestamp, (int, float)) and isinstance(item_ts, (int, float)):
                    if abs(float(item_ts) - float(timestamp)) < 0.001:
                        is_match = True
                elif str(item_ts) == str(timestamp):
                    is_match = True

                if is_match and target_record is None:
                    target_record = item
                else:
                    new_records.append(item)

            if target_record:
                self._records = new_records
                self._dirty = True

        if target_record:
            self._schedule_flush()

        return target_record

    def _on_flush_timer_fired(self) -> None:
        with self._flush_lock:
            self._flush_timer = None
        self.flush()

    def _schedule_flush(self) -> None:
        """Debounced flush to avoid hammering disk during batch generations."""
        with self._flush_lock:
            if self._flush_timer and self._flush_timer.is_alive():
                return
            timer = threading.Timer(self.flush_debounce_sec, self._on_flush_timer_fired)
            timer.daemon = True
            self._flush_timer = timer
            timer.start()

    def flush(self) -> None:
        """Synchronously write dirty in-memory records to disk using atomic rename."""
        needs_reschedule = False
        with self._flush_lock:
            with self._lock:
                if not self._dirty or self._records is None:
                    return
                # Make a snapshot of records to write outside the main lock
                records_snapshot = list(self._records)
                self._dirty = False

            tmp_path = f"{self.history_file_path}.tmp-{os.getpid()}-{threading.get_ident()}"
            try:
                os.makedirs(os.path.dirname(self.history_file_path), exist_ok=True)
                # Write compact JSON to save disk space and I/O time
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(records_snapshot, f, ensure_ascii=False, separators=(",", ":"))
                os.replace(tmp_path, self.history_file_path)
            except Exception as exc:
                logger.error(f"Failed to flush history to disk: {exc}")
                # Mark dirty again so next flush attempts write
                with self._lock:
                    self._dirty = True
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

            with self._lock:
                if self._dirty:
                    needs_reschedule = True

        # Reschedule outside _flush_lock to prevent non-reentrant self-deadlock
        if needs_reschedule:
            self._schedule_flush()
