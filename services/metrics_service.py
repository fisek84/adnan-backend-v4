# services/metrics_service.py

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import copy
import threading
from typing import Any, Dict, List, DefaultDict


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
    _metrics: DefaultDict[str, int] = defaultdict(int)
    _events_by_type: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)

    MAX_EVENTS_PER_TYPE = 500

    # --------------------------------------------------
    # COUNTERS
    # --------------------------------------------------
    @classmethod
    def incr(cls, key: str, value: int = 1) -> None:
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
    def emit(cls, event_type: str, payload: Dict[str, Any]) -> None:
        if not isinstance(event_type, str) or not event_type:
            return
        if not isinstance(payload, dict) or not payload:
            return

        event: Dict[str, Any] = {
            "ts": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "payload": copy.deepcopy(payload),
        }

        with cls._lock:
            cls._events_by_type[event_type].append(event)

            if len(cls._events_by_type[event_type]) > cls.MAX_EVENTS_PER_TYPE:
                cls._events_by_type[event_type] = cls._events_by_type[event_type][
                    -cls.MAX_EVENTS_PER_TYPE :
                ]

    # --------------------------------------------------
    # SNAPSHOT (READ-ONLY)
    # --------------------------------------------------
    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        with cls._lock:
            # flat list of events (UI-friendly)
            events_flat: List[Dict[str, Any]] = []
            for ev_list in cls._events_by_type.values():
                events_flat.extend(ev_list)

            return {
                "counters": copy.deepcopy(dict(cls._metrics)),
                "events": copy.deepcopy(events_flat),
                # keep detailed view for advanced use-cases
                "events_by_type": copy.deepcopy(dict(cls._events_by_type)),
                "read_only": True,
            }

    # --------------------------------------------------
    # RESET (CONTROLLED)
    # --------------------------------------------------
    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._metrics.clear()
            cls._events_by_type.clear()
