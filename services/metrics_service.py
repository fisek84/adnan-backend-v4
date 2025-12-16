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

    # --------------------------------------------------
    # COUNTERS
    # --------------------------------------------------
    @classmethod
    def incr(cls, key: str, value: int = 1):
        if not key or value == 0:
            return

        with cls._lock:
            cls._metrics[key] += value

    # --------------------------------------------------
    # EVENTS
    # --------------------------------------------------
    @classmethod
    def emit(cls, event_type: str, payload: Dict[str, Any]):
        if not event_type or not payload:
            return

        with cls._lock:
            cls._events[event_type].append({
                "ts": datetime.utcnow().isoformat(),
                **payload,
            })

            # hard cap per event type (memory safety)
            if len(cls._events[event_type]) > 500:
                cls._events[event_type] = cls._events[event_type][-500:]

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
