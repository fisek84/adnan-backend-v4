from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from services.metrics_service import MetricsService

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/")
def metrics_snapshot() -> Dict[str, Any]:
    """
    READ-ONLY Metrics Dashboard Snapshot

    FAZA 9 / #27 — Agent Activity Dashboard

    Returns:
    - global counters
    - raw events
    - derived agent activity view
    """

    snapshot = MetricsService.snapshot()

    events_raw = snapshot.get("events", [])
    counters_raw = snapshot.get("counters", {})

    events: List[Dict[str, Any]] = events_raw if isinstance(events_raw, list) else []
    counters: Dict[str, Any] = counters_raw if isinstance(counters_raw, dict) else {}

    # -------------------------------------------------
    # DERIVED AGENT ACTIVITY VIEW (READ-ONLY)
    # -------------------------------------------------
    agents: Dict[str, Dict[str, Any]] = {}

    for e in events:
        if not isinstance(e, dict):
            continue

        payload_raw = e.get("payload") or {}
        payload: Dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else {}

        agent_id_raw = payload.get("agent_id")
        agent_id = (
            agent_id_raw if isinstance(agent_id_raw, str) and agent_id_raw else ""
        )
        if not agent_id:
            continue

        agent = agents.setdefault(
            agent_id,
            {
                "agent_id": agent_id,
                "executions": 0,
                "failures": 0,
                "last_status": None,
                "last_seen": None,
            },
        )

        event_type = e.get("event_type")

        if event_type == "agent_execution":
            phase = payload.get("phase")
            if phase == "started":
                agent["executions"] = int(agent.get("executions", 0)) + 1
            elif phase == "failed":
                agent["failures"] = int(agent.get("failures", 0)) + 1

            agent["last_status"] = phase
            agent["last_seen"] = e.get("ts")

        elif event_type == "agent_heartbeat":
            agent["last_status"] = payload.get("status")
            agent["last_seen"] = payload.get("timestamp")

    return {
        "ok": True,
        "agents": list(agents.values()),
        "counters": counters,
        "read_only": True,
    }


# Export alias (da import bude stabilan u gateway_server.py)
metrics_router = router
