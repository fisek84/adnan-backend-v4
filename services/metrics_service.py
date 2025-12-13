# C:\adnan-backend-v4\services\metrics_service.py

from typing import Dict, Any
from collections import defaultdict
from datetime import datetime
import threading


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
    _metrics: Dict[str, Any] = defaultdict(int)
    _events: Dict[str, list] = defaultdict(list)

    # --------------------------------------------------
    # COUNTERS
    # --------------------------------------------------
    @classmethod
    def incr(cls, key: str, value: int = 1):
        with cls._lock:
            cls._metrics[key] += value

    # --------------------------------------------------
    # EVENTS
    # --------------------------------------------------
    @classmethod
    def emit(cls, event_type: str, payload: Dict[str, Any]):
        with cls._lock:
            cls._events[event_type].append({
                "ts": datetime.utcnow().isoformat(),
                **payload,
            })

    # --------------------------------------------------
    # SNAPSHOT (READ-ONLY)
    # --------------------------------------------------
    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        with cls._lock:
            return {
                "counters": dict(cls._metrics),
                "events": dict(cls._events),
            }

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._metrics.clear()
            cls._events.clear()
