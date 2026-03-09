# services/world_state_engine.py
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.notion_service import try_get_notion_service

JsonDict = Dict[str, Any]

SNAPSHOT_VERSION = "sotw.v1"


# ============================================================
# Helpers (deterministic / safe)
# ============================================================
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_str(x: Any) -> str:
    if isinstance(x, str) and x.strip():
        return x.strip()
    return "UNKNOWN"


def safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def parse_iso(s: Any) -> Optional[datetime]:
    if not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# ============================================================
# CAPS (hard limits)
# ============================================================
CAPS = {
    "goals.top": 5,
    "goals.blocked": 5,
    "goals.stale": 5,
    "projects.top": 10,
    "projects.at_risk": 10,
    "projects.blocked": 10,
    "tasks.critical_path": 10,
    "tasks.overdue": 5,
    "tasks.due_soon": 10,
    "tasks.unlinked.sample": 5,
    "kpis.summary": 10,
    "kpis.alerts": 10,
    "agents.health": 10,
    "agents.last_outputs": 3,
    "agents.errors": 3,
    "summaries.recent": 5,
    "summaries.by_goal": 3,
    "risks": 7,
    "alerts": 20,
}


# ============================================================
# World State Engine
# ============================================================
class WorldStateEngine:
    """
    CANONICAL State of the World Engine (Option B)

    - Notion is read ONLY via backend service
    - CEO Advisor never touches Notion
    - Output is deterministic SSOT snapshot

    CANON: this module MUST be import-safe (no Notion singleton required at import time).
    """

    # ----------------------------
    # Public API
    # ----------------------------
    @classmethod
    def build_snapshot_from_knowledge_snapshot(
        cls, knowledge_snapshot: Dict[str, Any]
    ) -> JsonDict:
        """Pure transform: KnowledgeSnapshotService.get_snapshot() -> sotw.v1.

        HARD CANON:
        - NO IO
        - NO NotionService usage
        - Deterministic output (stable sorting)

        Input is expected to be the wrapper returned by KnowledgeSnapshotService.get_snapshot(),
        but we also tolerate passing its `payload` dict directly.
        """

        def _payload_from_wrapper(snap: Any) -> Dict[str, Any]:
            if isinstance(snap, dict):
                p = snap.get("payload")
                if isinstance(p, dict):
                    return p
                return snap
            return {}

        def _list(x: Any) -> List[Dict[str, Any]]:
            if isinstance(x, list):
                return [it for it in x if isinstance(it, dict)]
            return []

        def _fields(item: Dict[str, Any]) -> Dict[str, Any]:
            f = item.get("fields")
            return f if isinstance(f, dict) else {}

        def _date_start(v: Any) -> str:
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                s = v.get("start")
                if isinstance(s, str) and s.strip():
                    return s.strip()
            return "UNKNOWN"

        def _people_join(v: Any) -> str:
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, list):
                xs = [x.strip() for x in v if isinstance(x, str) and x.strip()]
                xs2 = sorted(set(xs))
                return ", ".join(xs2) if xs2 else "UNKNOWN"
            return "UNKNOWN"

        def _first_relation_id(v: Any) -> str:
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, str) and it.strip():
                        return it.strip()
            return "UNKNOWN"

        def _cap(items: List[Any], key: str) -> List[Any]:
            return items[: CAPS.get(key, len(items))]

        def _priority_rank(s: str) -> int:
            v = (s or "").strip().lower()
            if v in {"p0", "urgent", "critical", "highest", "very high"}:
                return 0
            if v in {"high", "p1"}:
                return 1
            if v in {"medium", "normal", "p2"}:
                return 2
            if v in {"low", "p3"}:
                return 3
            return 9

        now = utc_now()
        tw_end = now
        tw_start = tw_end - timedelta(days=7)
        time_window = {
            "label": "last_7_days",
            "start": iso(tw_start),
            "end": iso(tw_end),
            "timezone": "UTC",
        }

        snap = knowledge_snapshot if isinstance(knowledge_snapshot, dict) else {}
        payload = _payload_from_wrapper(snap)
        goals_items = _list(payload.get("goals"))
        tasks_items = _list(payload.get("tasks"))
        projects_items = _list(payload.get("projects"))

        # ----------------------------
        # Goals
        # ----------------------------
        goals_all: List[JsonDict] = []
        goals_blocked: List[JsonDict] = []
        goals_stale: List[JsonDict] = []

        for it in goals_items:
            f = _fields(it)
            last_edit = parse_iso(it.get("last_edited_time"))
            stale_days = int((now - last_edit).days) if last_edit else 0

            status = safe_str(f.get("status"))
            progress_raw = f.get("progress")
            progress_pct = (
                int(progress_raw) if isinstance(progress_raw, (int, float)) else 0
            )

            goal: JsonDict = {
                "id": safe_str(it.get("id")),
                "title": safe_str(it.get("title")),
                "priority": safe_str(f.get("priority")),
                "status": status,
                "progress": {"pct": progress_pct, "confidence": "UNKNOWN"},
                "deadline": safe_str(_date_start(f.get("due"))),
                "owner": safe_str(_people_join(f.get("owner"))),
                "activity": {
                    "last_updated_at": safe_str(it.get("last_edited_time")),
                    "stale_days": stale_days,
                },
                "blockers": [],
                "next_step": {"text": "UNKNOWN", "due": "UNKNOWN"},
            }

            if stale_days >= 14:
                goals_stale.append(goal)

            if status.strip().lower() in {"blocked", "stuck"}:
                goals_blocked.append(goal)

            goals_all.append(goal)

        # Deterministic: highest progress first, then id asc
        goals_all_sorted = sorted(
            goals_all,
            key=lambda g: (
                -safe_int(((g.get("progress") or {}).get("pct")), 0),
                safe_str(g.get("id")),
            ),
        )

        goals_section: JsonDict = {
            "top": _cap(goals_all_sorted, "goals.top"),
            "blocked": _cap(
                sorted(goals_blocked, key=lambda g: safe_str(g.get("id"))),
                "goals.blocked",
            ),
            "stale": _cap(
                sorted(goals_stale, key=lambda g: safe_str(g.get("id"))),
                "goals.stale",
            ),
            "counts": {
                "active": len(goals_all),
                "blocked": len(goals_blocked),
                "stale": len(goals_stale),
            },
        }

        # ----------------------------
        # Projects
        # ----------------------------
        projects_all: List[JsonDict] = []
        projects_at_risk: List[JsonDict] = []
        projects_blocked: List[JsonDict] = []

        for it in projects_items:
            f = _fields(it)
            status = safe_str(f.get("status"))
            next_step = safe_str(f.get("next_step"))

            proj: JsonDict = {
                "id": safe_str(it.get("id")),
                "title": safe_str(it.get("title")),
                "priority": safe_str(f.get("priority")),
                "status": status,
                "deadline": safe_str(_date_start(f.get("target_deadline"))),
                "owner": "UNKNOWN",
                "progress": {
                    "pct": int(f.get("progress"))
                    if isinstance(f.get("progress"), (int, float))
                    else 0
                },
                "next_step": {"text": next_step, "due": "UNKNOWN"},
                "risk": {"level": "low", "reasons": []},
                "links": {
                    "goal_id": safe_str(_first_relation_id(f.get("primary_goal"))),
                },
            }

            blocked_like = next_step == "UNKNOWN" or status.strip().lower() in {
                "blocked",
                "stuck",
            }
            if blocked_like:
                proj["risk"]["level"] = "high"
                if next_step == "UNKNOWN":
                    proj["risk"]["reasons"].append("no_next_step")
                if status.strip().lower() in {"blocked", "stuck"}:
                    proj["risk"]["reasons"].append("status_blocked")
                projects_blocked.append(proj)
                projects_at_risk.append(proj)
            projects_all.append(proj)

        # Deterministic: priority, then id asc
        projects_all_sorted = sorted(
            projects_all,
            key=lambda p: (
                _priority_rank(safe_str(p.get("priority"))),
                safe_str(p.get("id")),
            ),
        )

        projects_section: JsonDict = {
            "top": _cap(projects_all_sorted, "projects.top"),
            "at_risk": _cap(
                sorted(projects_at_risk, key=lambda p: safe_str(p.get("id"))),
                "projects.at_risk",
            ),
            "blocked": _cap(
                sorted(projects_blocked, key=lambda p: safe_str(p.get("id"))),
                "projects.blocked",
            ),
            "counts": {
                "active": len(projects_all),
                "at_risk": len(projects_at_risk),
                "blocked": len(projects_blocked),
            },
        }

        # ----------------------------
        # Tasks
        # ----------------------------
        tasks_all: List[JsonDict] = []
        tasks_overdue: List[JsonDict] = []
        tasks_due_soon: List[JsonDict] = []
        tasks_unlinked: List[JsonDict] = []

        for it in tasks_items:
            f = _fields(it)
            due_s = _date_start(f.get("due"))
            due_dt = parse_iso(due_s) if due_s != "UNKNOWN" else None
            is_overdue = bool(due_dt and due_dt < now)
            hours_to_due = (
                int((due_dt - now).total_seconds() // 3600) if due_dt else None
            )

            task: JsonDict = {
                "id": safe_str(it.get("id")),
                "title": safe_str(it.get("title")),
                "priority": safe_str(f.get("priority")),
                "status": safe_str(f.get("status")),
                "due": safe_str(due_s),
                "owner": safe_str(_people_join(f.get("assigned_to"))),
                "links": {
                    "project_id": safe_str(_first_relation_id(f.get("project"))),
                    "goal_id": safe_str(_first_relation_id(f.get("goal"))),
                },
                "is_blocker": False,
            }

            if is_overdue:
                tasks_overdue.append(task)
            if hours_to_due is not None and 0 <= hours_to_due <= 72:
                tasks_due_soon.append(task)
            if (
                task["links"]["project_id"] == "UNKNOWN"
                and task["links"]["goal_id"] == "UNKNOWN"
            ):
                tasks_unlinked.append(task)

            tasks_all.append(task)

        def _due_sort_key(t: JsonDict) -> str:
            d = safe_str(t.get("due"))
            return "9999" if d == "UNKNOWN" else d

        tasks_all_sorted = sorted(
            tasks_all,
            key=lambda t: (
                _priority_rank(safe_str(t.get("priority"))),
                _due_sort_key(t),
                safe_str(t.get("id")),
            ),
        )

        tasks_section: JsonDict = {
            "critical_path": _cap(tasks_all_sorted, "tasks.critical_path"),
            "overdue": _cap(
                sorted(tasks_overdue, key=lambda t: _due_sort_key(t)),
                "tasks.overdue",
            ),
            "due_soon": _cap(
                sorted(tasks_due_soon, key=lambda t: _due_sort_key(t)),
                "tasks.due_soon",
            ),
            "data_quality": {
                "unlinked_count": len(tasks_unlinked),
                "unlinked_sample": _cap(
                    sorted(tasks_unlinked, key=lambda t: safe_str(t.get("id"))),
                    "tasks.unlinked.sample",
                ),
            },
        }

        risks: List[JsonDict] = []
        if int(tasks_section["data_quality"]["unlinked_count"]) > 0:
            risks.append(
                {
                    "id": "risk_unlinked_tasks",
                    "title": "Unlinked tasks present",
                    "severity": "medium",
                    "category": "data",
                    "evidence": ["tasks without goal/project"],
                    "owner": "UNKNOWN",
                }
            )

        # KPI / Agents / Summaries remain not wired here, match canonical WSE output.
        kpis = {"summary": [], "alerts": [], "as_of": iso(tw_end)}
        agents = {"health": [], "last_outputs": [], "errors": [], "as_of": iso(tw_end)}
        summaries = {"recent": [], "by_goal": []}
        alerts = [
            {
                "code": "NO_DATA",
                "severity": "info",
                "message": "KPI DB not wired",
                "source": "KPIDB",
                "details": {},
            },
            {
                "code": "NO_DATA",
                "severity": "info",
                "message": "Agent DB not wired",
                "source": "AgentDB",
                "details": {},
            },
            {
                "code": "NO_DATA",
                "severity": "info",
                "message": "Summary DB not wired",
                "source": "SummaryDB",
                "details": {},
            },
        ]

        ready_flag = bool(snap.get("ready")) if isinstance(snap, dict) else False
        status = safe_str(snap.get("status")) if isinstance(snap, dict) else "UNKNOWN"
        expired = bool(snap.get("expired")) if isinstance(snap, dict) else False

        sources_loaded: List[JsonDict] = [
            {
                "source": "KnowledgeSnapshotService",
                "rows_fetched": {
                    "goals": int(len(goals_items)),
                    "tasks": int(len(tasks_items)),
                    "projects": int(len(projects_items)),
                },
                "ok": True,
                "reason": "from_cached_knowledge_snapshot",
                "knowledge_status": status,
                "knowledge_expired": expired,
                "knowledge_last_sync": snap.get("last_sync")
                if isinstance(snap, dict)
                else None,
            }
        ]

        snapshot_out: JsonDict = {
            "generated_at": iso(utc_now()),
            "time_window": time_window,
            "goals": goals_section,
            "projects": projects_section,
            "tasks": tasks_section,
            "kpis": kpis,
            "pipeline": {"enabled": False, "stages": []},
            "agents": agents,
            "summaries": summaries,
            "risks": _cap(risks, "risks"),
            "alerts": _cap(alerts, "alerts"),
            "trace": {
                "snapshot_version": SNAPSHOT_VERSION,
                "sources_loaded": sources_loaded,
                "caps": CAPS,
                "determinism": {"sorting": "stable", "tie_breaker": "id_asc"},
                "transform": {
                    "source": "KnowledgeSnapshotService.get_snapshot",
                    "io": "none",
                },
            },
            "ready": bool(ready_flag),
        }

        snapshot_out.setdefault("trace", {})
        snapshot_out["trace"]["ready"] = bool(ready_flag)

        return snapshot_out

    def build_snapshot(self) -> JsonDict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Nema running event loop → sigurno je koristiti asyncio.run
            # Enterprise: close loop-local Notion client before loop teardown.
            async def _run() -> JsonDict:
                try:
                    return await self.abuild_snapshot()
                finally:
                    try:
                        notion = try_get_notion_service()
                        if notion is not None:
                            await notion.aclose_current_loop()
                    except Exception:
                        pass

            return asyncio.run(_run())

        # Ima running event loop → ne smijemo zvati asyncio.run (to pravi warning)
        raise RuntimeError("Use await abuild_snapshot() inside event loop")

    async def abuild_snapshot(self) -> JsonDict:
        tw_end = utc_now()
        tw_start = tw_end - timedelta(days=7)

        time_window = {
            "label": "last_7_days",
            "start": iso(tw_start),
            "end": iso(tw_end),
            "timezone": "UTC",
        }

        try:
            trace_sources: List[JsonDict] = []
            alerts: List[JsonDict] = []

            goals_pages, goals_trace = await self._fetch("goals", "GoalsDB")
            tasks_pages, tasks_trace = await self._fetch("tasks", "TasksDB")
            projects_pages, projects_trace = await self._fetch("projects", "ProjectsDB")

            trace_sources += [goals_trace, tasks_trace, projects_trace]

            goals = self._build_goals(goals_pages, tasks_pages)
            tasks = self._build_tasks(tasks_pages)
            projects = self._build_projects(projects_pages, tasks_pages)

            # KPI / Agents / Summaries not wired → explicit UNKNOWN
            kpis = {"summary": [], "alerts": [], "as_of": iso(tw_end)}
            agents = {
                "health": [],
                "last_outputs": [],
                "errors": [],
                "as_of": iso(tw_end),
            }
            summaries = {"recent": [], "by_goal": []}

            alerts += [
                self._alert("NO_DATA", "info", "KPI DB not wired", "KPIDB"),
                self._alert("NO_DATA", "info", "Agent DB not wired", "AgentDB"),
                self._alert("NO_DATA", "info", "Summary DB not wired", "SummaryDB"),
            ]

            risks = self._build_risks(goals, projects, tasks)

            snapshot: JsonDict = {
                "generated_at": iso(utc_now()),
                "time_window": time_window,
                "goals": goals,
                "projects": projects,
                "tasks": tasks,
                "kpis": kpis,
                "pipeline": {"enabled": False, "stages": []},
                "agents": agents,
                "summaries": summaries,
                "risks": self._cap(risks, "risks"),
                "alerts": self._cap(alerts, "alerts"),
                "trace": {
                    "snapshot_version": SNAPSHOT_VERSION,
                    "sources_loaded": trace_sources,
                    "caps": CAPS,
                    "determinism": {
                        "sorting": "stable",
                        "tie_breaker": "id_asc",
                    },
                },
            }

            # Best-effort: operational diagnostics (does not affect determinism expectations).
            try:
                notion = try_get_notion_service()
                if notion is not None and hasattr(notion, "client_stats"):
                    snapshot.setdefault("trace", {})
                    snapshot["trace"]["notion_client"] = notion.client_stats()
            except Exception:
                pass

            # enterprise locked: ready flags (success)
            snapshot["ready"] = True
            snapshot.setdefault("trace", {})
            snapshot["trace"]["ready"] = True

            return snapshot

        except Exception as e:
            snapshot_fallback: JsonDict = {
                "generated_at": iso(utc_now()),
                "time_window": time_window,
                "goals": {
                    "top": [],
                    "blocked": [],
                    "stale": [],
                    "counts": {"active": 0, "blocked": 0, "stale": 0},
                },
                "projects": {
                    "top": [],
                    "at_risk": [],
                    "blocked": [],
                    "counts": {"active": 0, "at_risk": 0, "blocked": 0},
                },
                "tasks": {
                    "critical_path": [],
                    "overdue": [],
                    "due_soon": [],
                    "data_quality": {"unlinked_count": 0, "unlinked_sample": []},
                },
                "kpis": {"summary": [], "alerts": [], "as_of": iso(tw_end)},
                "pipeline": {"enabled": False, "stages": []},
                "agents": {
                    "health": [],
                    "last_outputs": [],
                    "errors": [],
                    "as_of": iso(tw_end),
                },
                "summaries": {"recent": [], "by_goal": []},
                "risks": [],
                "alerts": [],
                "trace": {
                    "snapshot_version": SNAPSHOT_VERSION,
                    "sources_loaded": [],
                    "caps": CAPS,
                    "determinism": {
                        "sorting": "stable",
                        "tie_breaker": "id_asc",
                    },
                },
            }

            # enterprise locked: ready flags (failure)
            snapshot_fallback["ready"] = False
            snapshot_fallback.setdefault("trace", {})
            snapshot_fallback["trace"]["ready"] = False
            snapshot_fallback["trace"]["error"] = str(e)

            return snapshot_fallback

    # ============================================================
    # Fetch
    # ============================================================
    async def _fetch(
        self, db_key: str, source_name: str
    ) -> Tuple[List[JsonDict], JsonDict]:
        """
        CANON:
          - Never hard-require Notion singleton at import-time
          - Deterministic output even if Notion is not initialized
        """
        notion = try_get_notion_service()
        if notion is None:
            trace = {
                "source": source_name,
                "rows_fetched": 0,
                "rows_after_filter": 0,
                "last_edited_at_max": "UNKNOWN",
                "ok": False,
                "reason": "notion_service_not_initialized",
            }
            return [], trace

        pages: List[JsonDict] = []
        err: Optional[str] = None

        try:
            res = await notion.query_database(
                db_key=db_key,
                query={
                    "sorts": [
                        {
                            "timestamp": "last_edited_time",
                            "direction": "descending",
                        }
                    ],
                    "page_size": 200,
                },
            )
            pages = res.get("results", []) or []
            if not isinstance(pages, list):
                pages = []
        except Exception as exc:
            pages = []
            err = f"{type(exc).__name__}: {exc}"

        last_edit = "UNKNOWN"
        dts = [
            parse_iso(p.get("last_edited_time")) for p in pages if isinstance(p, dict)
        ]
        dts = [d for d in dts if d is not None]
        if dts:
            last_edit = iso(max(dts))

        trace: JsonDict = {
            "source": source_name,
            "rows_fetched": len(pages),
            "rows_after_filter": len(pages),
            "last_edited_at_max": last_edit,
            "ok": err is None,
        }
        if err:
            trace["error"] = err

        return pages, trace

    # ============================================================
    # Builders
    # ============================================================
    def _build_goals(
        self, goals_pages: List[JsonDict], tasks_pages: List[JsonDict]
    ) -> JsonDict:
        goals = []
        blocked = []
        stale = []

        now = utc_now()

        for p in goals_pages:
            if not isinstance(p, dict):
                continue

            gid = safe_str(p.get("id"))
            last_edit = parse_iso(p.get("last_edited_time"))
            staleness_days = (now - last_edit).days if last_edit else 0

            goal = {
                "id": gid,
                "title": safe_str(self._prop_title(p, "Name")),
                "priority": safe_str(self._prop_select(p, "Priority")),
                "status": safe_str(self._prop_select(p, "Status")),
                "progress": {"pct": 0, "confidence": "UNKNOWN"},
                "deadline": safe_str(self._prop_date(p, "Deadline")),
                "owner": safe_str(self._prop_people(p, "Assigned To")),
                "activity": {
                    "last_updated_at": safe_str(p.get("last_edited_time")),
                    "stale_days": staleness_days,
                },
                "blockers": [],
                "next_step": {
                    "text": safe_str(self._prop_rich(p, "Next Step")),
                    "due": "UNKNOWN",
                },
            }

            if staleness_days >= 14:
                stale.append(goal)

            if goal["next_step"]["text"] == "UNKNOWN":
                blocked.append(goal)

            goals.append(goal)

        return {
            "top": self._cap(goals, "goals.top"),
            "blocked": self._cap(blocked, "goals.blocked"),
            "stale": self._cap(stale, "goals.stale"),
            "counts": {
                "active": len(goals),
                "blocked": len(blocked),
                "stale": len(stale),
            },
        }

    def _build_projects(
        self, project_pages: List[JsonDict], task_pages: List[JsonDict]
    ) -> JsonDict:
        projects = []
        at_risk = []
        blocked = []

        for p in project_pages:
            if not isinstance(p, dict):
                continue

            proj = {
                "id": safe_str(p.get("id")),
                "title": safe_str(self._prop_title(p, "Project Name")),
                "priority": safe_str(self._prop_select(p, "Priority")),
                "status": safe_str(self._prop_select(p, "Status")),
                "deadline": safe_str(self._prop_date(p, "Target Deadline")),
                "owner": safe_str(self._prop_select(p, "Handled By")),
                "progress": {"pct": 0},
                "next_step": {
                    "text": safe_str(self._prop_rich(p, "Next Step")),
                    "due": "UNKNOWN",
                },
                "risk": {"level": "low", "reasons": []},
            }

            if proj["next_step"]["text"] == "UNKNOWN":
                proj["risk"]["level"] = "high"
                proj["risk"]["reasons"].append("no_next_step")
                blocked.append(proj)
                at_risk.append(proj)

            projects.append(proj)

        return {
            "top": self._cap(projects, "projects.top"),
            "at_risk": self._cap(at_risk, "projects.at_risk"),
            "blocked": self._cap(blocked, "projects.blocked"),
            "counts": {
                "active": len(projects),
                "at_risk": len(at_risk),
                "blocked": len(blocked),
            },
        }

    def _build_tasks(self, task_pages: List[JsonDict]) -> JsonDict:
        tasks = []
        overdue = []
        due_soon = []
        unlinked = []

        now = utc_now()

        for p in task_pages:
            if not isinstance(p, dict):
                continue

            due = parse_iso(self._prop_date(p, "Due Date"))
            is_overdue = bool(due and due < now)
            hours_to_due = int((due - now).total_seconds() // 3600) if due else None

            task = {
                "id": safe_str(p.get("id")),
                "title": safe_str(self._prop_title(p, "Name")),
                "priority": safe_str(self._prop_select(p, "Priority")),
                "status": safe_str(self._prop_select(p, "Status")),
                "due": safe_str(self._prop_date(p, "Due Date")),
                "owner": safe_str(self._prop_people(p, "Assigned To")),
                "links": {
                    "project_id": safe_str(self._prop_relation(p, "Project")),
                    "goal_id": safe_str(self._prop_relation(p, "Goal")),
                },
                "is_blocker": False,
            }

            if is_overdue:
                overdue.append(task)

            if hours_to_due is not None and 0 <= hours_to_due <= 72:
                due_soon.append(task)

            if (
                task["links"]["project_id"] == "UNKNOWN"
                and task["links"]["goal_id"] == "UNKNOWN"
            ):
                unlinked.append(task)

            tasks.append(task)

        return {
            "critical_path": self._cap(tasks, "tasks.critical_path"),
            "overdue": self._cap(overdue, "tasks.overdue"),
            "due_soon": self._cap(due_soon, "tasks.due_soon"),
            "data_quality": {
                "unlinked_count": len(unlinked),
                "unlinked_sample": self._cap(unlinked, "tasks.unlinked.sample"),
            },
        }

    def _build_risks(
        self, goals: JsonDict, projects: JsonDict, tasks: JsonDict
    ) -> List[JsonDict]:
        risks = []

        if tasks["data_quality"]["unlinked_count"] > 0:
            risks.append(
                {
                    "id": "risk_unlinked_tasks",
                    "title": "Unlinked tasks present",
                    "severity": "medium",
                    "category": "data",
                    "evidence": ["tasks without goal/project"],
                    "owner": "UNKNOWN",
                }
            )

        return risks

    # ============================================================
    # Utils
    # ============================================================
    def _cap(self, items: List[Any], key: str) -> List[Any]:
        return items[: CAPS.get(key, len(items))]

    def _alert(self, code: str, severity: str, message: str, source: str) -> JsonDict:
        return {
            "code": code,
            "severity": severity,
            "message": message,
            "source": source,
            "details": {},
        }

    # ============================================================
    # Notion property helpers
    # ============================================================
    def _prop_title(self, p: JsonDict, name: str) -> str:
        try:
            arr = p["properties"][name]["title"]
            return " ".join(t["plain_text"] for t in arr if t.get("plain_text"))
        except Exception:
            return "UNKNOWN"

    def _prop_select(self, p: JsonDict, name: str) -> str:
        try:
            return safe_str(p["properties"][name]["select"]["name"])
        except Exception:
            return "UNKNOWN"

    def _prop_date(self, p: JsonDict, name: str) -> str:
        try:
            return safe_str(p["properties"][name]["date"]["start"])
        except Exception:
            return "UNKNOWN"

    def _prop_people(self, p: JsonDict, name: str) -> str:
        """
        CANON: Assigned To is typically a Notion "people" property.
        Be tolerant: if workspace schema uses multi_select, handle it too.
        """
        try:
            arr = p["properties"][name].get("people") or []
            if isinstance(arr, list) and arr:
                names: List[str] = []
                for a in arr:
                    if not isinstance(a, dict):
                        continue
                    nm = (
                        a.get("name") or a.get("person", {}).get("email") or a.get("id")
                    )
                    if isinstance(nm, str) and nm.strip():
                        names.append(nm.strip())
                return ", ".join(names) if names else "UNKNOWN"
        except Exception:
            pass

        # fallback: multi_select
        try:
            arr2 = p["properties"][name].get("multi_select") or []
            if isinstance(arr2, list) and arr2:
                names2 = [
                    a["name"] for a in arr2 if isinstance(a, dict) and a.get("name")
                ]
                return ", ".join(names2) if names2 else "UNKNOWN"
        except Exception:
            pass

        return "UNKNOWN"

    def _prop_relation(self, p: JsonDict, name: str) -> str:
        try:
            arr = p["properties"][name]["relation"]
            return safe_str(arr[0]["id"]) if arr else "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    def _prop_rich(self, p: JsonDict, name: str) -> str:
        try:
            arr = p["properties"][name]["rich_text"]
            return " ".join(t["plain_text"] for t in arr if t.get("plain_text"))
        except Exception:
            return "UNKNOWN"
