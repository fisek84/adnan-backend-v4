# services/metrics_service.py

from typing import Dict, Any
from collections import defaultdict
from datetime import datetime
import threading
import copy


class MetricsService:
    """
    Metrics & KPI Collector (IN-MEMORY v1)

    RULES:
    - No blocking
    - No decisions
    - No execution
    - Best-effort only
    """

    _lock = threading.Lock()
    _metrics: Dict[str, int] = defaultdict(int)
    _events: Dict[str, list] = defaultdict(list)

    MAX_EVENTS_PER_TYPE = 500

    # --------------------------------------------------
    # COUNTERS
    # --------------------------------------------------
    @classmethod
    def incr(cls, key: str, value: int = 1):
        if not isinstance(key, str) or not key:
            return
        if not isinstance(value, int) or value == 0:
            return

        with cls._lock:
            cls._metrics[key] += value

    # --------------------------------------------------
    # EVENTS
    # --------------------------------------------------
    @classmethod
    def emit(cls, event_type: str, payload: Dict[str, Any]):
        if not isinstance(event_type, str) or not event_type:
            return
        if not isinstance(payload, dict) or not payload:
            return

        event = {
            "ts": datetime.utcnow().isoformat(),
            **payload,
        }

        with cls._lock:
            cls._events[event_type].append(event)

            if len(cls._events[event_type]) > cls.MAX_EVENTS_PER_TYPE:
                cls._events[event_type] = cls._events[event_type][-cls.MAX_EVENTS_PER_TYPE:]

    # --------------------------------------------------
    # SNAPSHOT (READ-ONLY)
    # --------------------------------------------------
    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        with cls._lock:
            return {
                "counters": copy.deepcopy(dict(cls._metrics)),
                "events": copy.deepcopy(dict(cls._events)),
            }

    # --------------------------------------------------
    # RESET (CONTROLLED)
    # --------------------------------------------------
    @classmethod
    def reset(cls):
        with cls._lock:
            cls._metrics.clear()
            cls._events.clear()
