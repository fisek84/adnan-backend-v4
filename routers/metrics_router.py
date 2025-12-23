from fastapi import APIRouter
from services.metrics_service import MetricsService

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/")
def metrics_snapshot():
    """
    READ-ONLY Metrics Dashboard Snapshot

    FAZA 9 / #27 — Agent Activity Dashboard

    Returns:
    - global counters
    - raw events
    - derived agent activity view
    """

    snapshot = MetricsService.snapshot()

    events = snapshot.get("events", [])
    counters = snapshot.get("counters", {})

    # -------------------------------------------------
    # DERIVED AGENT ACTIVITY VIEW (READ-ONLY)
    # -------------------------------------------------
    agents = {}

    for e in events:
        payload = e.get("payload") or {}
        agent_id = payload.get("agent_id")
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

        if e.get("event_type") in {"agent_execution"}:
            phase = payload.get("phase")
            if phase == "started":
                agent["executions"] += 1
            elif phase == "failed":
                agent["failures"] += 1

            agent["last_status"] = phase
            agent["last_seen"] = e.get("ts")

        if e.get("event_type") == "agent_heartbeat":
            agent["last_status"] = payload.get("status")
            agent["last_seen"] = payload.get("timestamp")

    return {
        "ok": True,
        "agents": list(agents.values()),
        "counters": counters,
        "read_only": True,
    }
