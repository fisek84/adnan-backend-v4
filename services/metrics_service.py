# services/metrics_service.py

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import copy
import threading
from typing import Any, Dict, List, DefaultDict


class MetricsService:
    """
    METRICS SERVICE — CANONICAL (WORLD-CLASS)

    Odgovornost:
    - IN-MEMORY metrics & events collector
    - THREAD-SAFE
    - READ-ONLY snapshot
    - BEST-EFFORT (nikad ne ruši sistem)

    HARD CANON:
    - nema IO
    - nema persistence
    - nema decision / execution
    """

    _lock = threading.Lock()

    _counters: DefaultDict[str, int] = defaultdict(int)
    _events_by_type: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)

    MAX_EVENTS_PER_TYPE = 500

    # --------------------------------------------------
    # INTERNAL
    # --------------------------------------------------
    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # --------------------------------------------------
    # COUNTERS
    # --------------------------------------------------
    @classmethod
    def incr(cls, key: str, value: int = 1) -> None:
        if not isinstance(key, str) or not key.strip():
            return
        if not isinstance(value, int) or value == 0:
            return

        k = key.strip()

        with cls._lock:
            cls._counters[k] += value

    # --------------------------------------------------
    # EVENTS
    # --------------------------------------------------
    @classmethod
    def emit(cls, event_type: str, payload: Dict[str, Any]) -> None:
        if not isinstance(event_type, str) or not event_type.strip():
            return
        if not isinstance(payload, dict):
            return

        et = event_type.strip()

        event: Dict[str, Any] = {
            "ts": cls._utc_now_iso(),
            "event_type": et,
            "payload": copy.deepcopy(payload),
        }

        with cls._lock:
            bucket = cls._events_by_type[et]
            bucket.append(event)

            # hard cap (backpressure)
            if len(bucket) > cls.MAX_EVENTS_PER_TYPE:
                cls._events_by_type[et] = bucket[-cls.MAX_EVENTS_PER_TYPE :]

    # --------------------------------------------------
    # SNAPSHOT (READ-ONLY)
    # --------------------------------------------------
    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        with cls._lock:
            # UI-friendly flat list
            events_flat: List[Dict[str, Any]] = []
            for evs in cls._events_by_type.values():
                events_flat.extend(evs)

            return {
                "counters": copy.deepcopy(dict(cls._counters)),
                "events": copy.deepcopy(events_flat),
                "events_by_type": copy.deepcopy(dict(cls._events_by_type)),
                "generated_at": cls._utc_now_iso(),
                "read_only": True,
            }

    # --------------------------------------------------
    # RESET (CONTROLLED / TESTING ONLY)
    # --------------------------------------------------
    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._counters.clear()
            cls._events_by_type.clear()
