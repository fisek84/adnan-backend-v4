# routers/chat_router.py
# PHASE 6: Notion Ops ARMED Gate

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid

from datetime import datetime, timezone
from types import SimpleNamespace

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.ceo_advisor_agent import (
    create_ceo_advisor_agent,
    LLMNotConfiguredError,
    _render_snapshot_summary,
)
from dependencies import get_memory_read_only_service
from services.ceo_conversation_state_store import ConversationStateStore

# Must match gateway_server.PROPOSAL_WRAPPER_INTENT
from models.canon import PROPOSAL_WRAPPER_INTENT

# PHASE 6: Import shared Notion Ops state management
from services.notion_ops_state import (
    set_armed as _set_armed_shared,
    get_state as _get_state_shared,
)

# Commands that are NOT considered "structured/actionable proposals" for fallback detection.
_NON_ACTIONABLE_PROPOSALS = {"refresh_snapshot", "notion_ops_toggle"}

# Activation keywords (exact per spec)
_ACTIVATE_KEYWORDS = (
    "notion ops active",
    "notion ops aktivan",
    "notion ops aktiviraj",
    "notion ops uključi",
    "notion ops ukljuci",
)


logger = logging.getLogger(__name__)

# Deactivation keywords (exact per spec + Bosnian variants mentioned)
_DEACTIVATE_KEYWORDS = (
    "stop notion ops",
    "notion ops deaktiviraj",
    "notion ops ugasi",
    "notion ops isključi",
    "notion ops iskljuci",
    "notion ops deactivate",
)


_SHOW_GOALS_TASKS_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"\b(?:pokazi|poka\u017ei|prikazi|prika\u017ei|izlistaj|navedi|lista|pregled|overview)\b"
    r".*\b(?:cilj\w*|goal\w*|task\w*|zadac\w*|zadat\w*)"
    r"|"
    r"\b(?:cilj\w*|goal\w*|task\w*|zadac\w*|zadat\w*)\b"
    r".*\b(?:pokazi|poka\u017ei|prikazi|prika\u017ei|izlistaj|navedi|lista|pregled|overview)\b"
    r"|"
    # Natural question forms (Bosnian): "Kakve imamo ciljeve?", "Koje ciljeve imamo?"
    r"\b(?:kakv\w*|koje|koji|sta|\u0161ta)\b\s+\b(?:imamo|su)\b"
    r".*\b(?:cilj\w*|goal\w*|task\w*|zadac\w*|zadat\w*)\b"
    r")"
)


_TOP_GOAL_RE = re.compile(
    r"(?i)(?:"
    # Order A: adjective/keyword before 'goal'
    r"\b(?:najbitnij\w*|najvaznij\w*|najprioritetnij\w*|top|glavn\w*|main|most\s+important|highest\s+priority|primary)\b.*\b(?:cilj\w*|goal\w*)\b"
    r"|"
    # Order B: 'goal' before adjective/keyword (e.g., 'Koji cilj je glavni?')
    r"\b(?:cilj\w*|goal\w*)\b.*\b(?:najbitnij\w*|najvaznij\w*|najprioritetnij\w*|top|glavn\w*|main|most\s+important|highest\s+priority|primary)\b"
    r")"
)


def _is_top_goal_intent(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # Guard: "Zašto je ... cilj glavni?" is a WHY follow-up, not a top-goal listing request.
    if re.search(r"(?i)\b(zasto|zašto)\b", t):
        return False
    return bool(_TOP_GOAL_RE.search(t))


def _is_show_goals_tasks_intent(text: str) -> bool:
    """Return True when the prompt is a Bosnian/English show/list goals+tasks intent."""
    t = (text or "").strip()
    if not t:
        return False
    # Guard: do NOT treat goal-scoped task follow-ups as a global "show goals+tasks" intent.
    # Examples:
    #   - "Koji su zadaci povezani sa ovim ciljem?"
    #   - "Imamo li aktivne zadatke za taj cilj?"
    if re.search(r"(?i)\b(task|taskovi|zadat|zadac)\w*\b", t) and re.search(
        r"(?i)\b(ovaj|ovom|ovog|ovome|ovo|taj|tom|tog|tome|ovim)\b.*\b(cilj|goal)\w*\b",
        t,
    ):
        return False
    return bool(_SHOW_GOALS_TASKS_RE.search(t))


def _compute_ceo_view(snapshot: Any) -> Dict[str, Any]:
    """Build a compact (<= 4 KB) CEO_VIEW derived from an SSOT snapshot wrapper.

    Source: snapshot.payload.goals / snapshot.payload.tasks (normalized by
    _normalize_snapshot_wrapper, so lists are always present).
    Defensive: prefers item.fields.* for status/due/priority if available.
    Deterministic ordering: rank goals by status urgency + due date (see
    goals_top3_criteria in returned dict). This avoids "top 3" being interpreted
    as "most important" while being just the first three in payload order.
    """

    def _norm_ascii(text: str) -> str:
        t = (text or "").strip().lower()
        return (
            t.replace("č", "c")
            .replace("ć", "c")
            .replace("š", "s")
            .replace("đ", "dj")
            .replace("ž", "z")
        )

    def _status_bucket(status: str) -> int:
        s = _norm_ascii(status or "")
        if any(x in s for x in ("blocked", "blokir", "at risk", "rizik", "stuck")):
            return 0
        if any(
            x in s
            for x in (
                "in progress",
                "u toku",
                "active",
                "aktiv",
                "doing",
                "ongoing",
            )
        ):
            return 1
        if any(
            x in s
            for x in (
                "not started",
                "planned",
                "plan",
                "todo",
                "to do",
                "backlog",
            )
        ):
            return 2
        if any(
            x in s
            for x in (
                "done",
                "completed",
                "closed",
                "archived",
                "cancel",
                "zavrs",
                "gotov",
            )
        ):
            return 3
        return 9

    def _parse_due(due_str: str) -> Optional[datetime]:
        s = (due_str or "").strip()
        if not s or s == "-":
            return None
        try:
            # Accept ISO date and datetime. Handle trailing Z.
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            pass
        try:
            # Best-effort: take YYYY-MM-DD prefix.
            if len(s) >= 10:
                return datetime.fromisoformat(s[:10])
        except Exception:
            pass
        return None

    def _s(v: Any, default: str = "-") -> str:
        if isinstance(v, str):
            s = v.strip()
            return s if s else default
        if isinstance(v, (int, float, bool)):
            return str(v)
        if isinstance(v, dict):
            for k in ("title", "name", "value", "status"):
                if k in v:
                    vv = v[k]
                    if isinstance(vv, str) and vv.strip():
                        return vv.strip()
        return default

    def _due(v: Any) -> str:
        if isinstance(v, str):
            return v.strip() or "-"
        if isinstance(v, dict):
            for k in ("start", "date", "value"):
                vv = v.get(k)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
        return "-"

    snap = snapshot if isinstance(snapshot, dict) else {}
    payload0 = snap.get("payload") if isinstance(snap.get("payload"), dict) else None
    payload = payload0 if isinstance(payload0, dict) else snap
    if not isinstance(payload, dict):
        payload = {}

    goals_raw = payload.get("goals") if isinstance(payload.get("goals"), list) else []
    tasks_raw = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []

    ranked_goals: List[Dict[str, Any]] = [g for g in goals_raw if isinstance(g, dict)]
    ranked_goals_with_key: List[tuple] = []
    for idx, it in enumerate(ranked_goals):
        f = it.get("fields") if isinstance(it.get("fields"), dict) else {}
        title0 = _s(
            it.get("title") or it.get("name") or f.get("title") or f.get("name")
        )
        status0 = _s(
            f.get("status") or f.get("Status") or it.get("status") or it.get("Status")
        )
        due0 = _due(f.get("due") or f.get("Due") or it.get("due"))
        due_dt = _parse_due(due0)
        ranked_goals_with_key.append(
            (
                _status_bucket(status0),
                1 if due_dt is None else 0,
                due_dt or datetime.max,
                _norm_ascii(title0),
                idx,
                it,
            )
        )

    ranked_goals_with_key.sort(key=lambda x: x[:5])

    goals_top3 = []
    for _k in ranked_goals_with_key[:3]:
        it = _k[-1]
        if not isinstance(it, dict):
            continue
        f = it.get("fields") if isinstance(it.get("fields"), dict) else {}
        gid = None
        for k in ("id", "notion_id", "notionId"):
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                gid = v.strip()
                break
        goals_top3.append(
            {
                "id": gid,
                "title": _s(
                    it.get("title") or it.get("name") or f.get("title") or f.get("name")
                ),
                "status": _s(
                    f.get("status")
                    or f.get("Status")
                    or it.get("status")
                    or it.get("Status")
                ),
                "due": _due(f.get("due") or f.get("Due") or it.get("due")),
                "owner": _s(
                    f.get("owner")
                    or f.get("Owner")
                    or f.get("assigned_to")
                    or f.get("Assigned To")
                    or it.get("owner")
                    or it.get("assigned_to")
                ),
            }
        )

    tasks_top10 = []
    for it in tasks_raw[:10]:
        if not isinstance(it, dict):
            continue
        f = it.get("fields") if isinstance(it.get("fields"), dict) else {}
        goal_ids = (
            it.get("goal_ids")
            or it.get("goalIds")
            or it.get("goal_id")
            or it.get("goal")
            or f.get("goal_ids")
            or f.get("goalIds")
            or f.get("goal_id")
            or f.get("goal")
            or []
        )
        if isinstance(goal_ids, str) and goal_ids.strip():
            goal_ids = [goal_ids.strip()]
        tasks_top10.append(
            {
                "title": _s(
                    it.get("title") or it.get("name") or f.get("title") or f.get("name")
                ),
                "status": _s(
                    f.get("status")
                    or f.get("Status")
                    or it.get("status")
                    or it.get("Status")
                ),
                "due": _due(f.get("due") or f.get("Due") or it.get("due")),
                "priority": _s(
                    f.get("priority")
                    or f.get("Priority")
                    or it.get("priority")
                    or it.get("Priority")
                ),
                "owner": _s(
                    f.get("assigned_to")
                    or f.get("Assigned To")
                    or f.get("owner")
                    or f.get("Owner")
                    or it.get("assigned_to")
                    or it.get("owner")
                ),
                "goal_ids": goal_ids if isinstance(goal_ids, list) else [],
            }
        )

    return {
        "goals_count": len(goals_raw),
        "tasks_count": len(tasks_raw),
        "goals_top3_criteria": "Deterministic rank: status urgency (blocked/at-risk > in-progress/active > planned/todo > done) then due date (soonest first).",
        "goals_top3": goals_top3,
        "tasks_top10": tasks_top10,
    }


def build_chat_router(agent_router: Optional[Any] = None) -> APIRouter:
    router = APIRouter()

    def _chat_streaming_enabled() -> bool:
        raw = (os.getenv("CHAT_STREAMING_ENABLED") or "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _iso_utc_now() -> str:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _chunk_text(text: str, *, max_chars: int = 240) -> List[str]:
        t = text or ""
        if not t:
            return []
        if max_chars <= 0:
            return [t]
        out: List[str] = []
        i = 0
        n = len(t)
        while i < n:
            j = min(n, i + max_chars)
            # Prefer splitting at whitespace when possible.
            if j < n:
                k = t.rfind(" ", i, j)
                if k > i + int(max_chars * 0.6):
                    j = k + 1
            out.append(t[i:j])
            i = j
        return out

    def _attach_session_id(
        content: Dict[str, Any], session_id: Optional[str]
    ) -> Dict[str, Any]:
        if isinstance(session_id, str) and session_id.strip():
            content.setdefault("session_id", session_id.strip())
        return content

    def _deep_merge_dicts(
        base: Dict[str, Any], incoming: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Re-export the existing deep-merge util (keeps behavior aligned across routes)."""

        try:
            from services.agent_router_service import _deep_merge_dicts as _dm  # noqa: PLC0415

            return _dm(base, incoming)
        except Exception:
            # Minimal fallback (only used if import fails unexpectedly)
            for key, incoming_value in (incoming or {}).items():
                base_value = base.get(key)
                if isinstance(base_value, dict) and isinstance(incoming_value, dict):
                    _deep_merge_dicts(base_value, incoming_value)
                else:
                    base[key] = incoming_value
            return base

    def _normalize_snapshot_wrapper(raw: Any) -> Dict[str, Any]:
        """Normalize snapshot wrapper so payload lists are never null.

        Required for Windows PowerShell semantics: @($null).Count == 1.
        We guarantee payload.{goals,tasks,projects} are lists (possibly empty).
        """

        snap = raw if isinstance(raw, dict) else {}
        payload0 = (
            snap.get("payload") if isinstance(snap.get("payload"), dict) else None
        )
        payload = (
            payload0
            if isinstance(payload0, dict)
            else (snap if isinstance(snap, dict) else {})
        )
        if not isinstance(payload, dict):
            payload = {}

        payload_norm: Dict[str, Any] = dict(payload)

        # Normalize canonical collections (never null).
        for k in ("goals", "tasks", "projects"):
            if not isinstance(payload_norm.get(k), list):
                payload_norm[k] = []

        # Back-compat: some producers provide collections under dashboard.
        try:
            dash = payload_norm.get("dashboard")
            if isinstance(dash, dict):
                for k in ("goals", "tasks", "projects"):
                    if payload_norm.get(k) == [] and isinstance(dash.get(k), list):
                        payload_norm[k] = dash.get(k) or []
        except Exception:
            pass

        out = dict(snap)
        out["payload"] = payload_norm

        # Ensure ready is a stable boolean.
        ready_raw = out.get("ready")
        if isinstance(ready_raw, bool):
            out["ready"] = bool(ready_raw)
        elif ready_raw is None:
            out["ready"] = bool(out)
        else:
            out["ready"] = bool(ready_raw)

        # Snapshot correctness invariants (post-compute, single place):
        # If meta indicates budget exceeded or errors, snapshot must not be ready/fresh/ok.
        try:
            meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
            meta = dict(meta) if isinstance(meta, dict) else {}
            budget = meta.get("budget") if isinstance(meta.get("budget"), dict) else {}

            has_errors = bool(meta.get("errors"))
            exceeded = bool(budget.get("exceeded"))
            meta_ok = meta.get("ok")

            if exceeded or has_errors or meta_ok is False:
                out["ready"] = False
                if out.get("status") == "fresh":
                    out["status"] = "partial"
                meta["ok"] = False
                if "reason" not in meta:
                    meta["reason"] = "budget_exceeded" if exceeded else "errors_present"
                out["meta"] = meta
        except Exception:
            pass

        return out

    def _grounding_bundle(
        *,
        prompt: str,
        knowledge_snapshot: Dict[str, Any],
        memory_snapshot: Dict[str, Any],
        legacy_trace: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            from services.grounding_pack_service import (  # noqa: PLC0415
                GroundingPackService,
            )

            gp = GroundingPackService.build(
                prompt=prompt,
                knowledge_snapshot=knowledge_snapshot,
                memory_public_snapshot=memory_snapshot,
                legacy_trace=legacy_trace,
                agent_id=agent_id,
            )
        except Exception:
            gp = {
                "enabled": False,
                "feature_flags": {"CEO_GROUNDING_PACK_ENABLED": False},
            }

        out: Dict[str, Any] = {"grounding_pack": gp}
        if isinstance(gp, dict):
            diag = gp.get("diagnostics")
            tr2 = gp.get("trace")
            if isinstance(diag, dict):
                out["diagnostics"] = diag
            if isinstance(tr2, dict):
                out["trace_v2"] = tr2

            # Debug-only mirror used for strict API verification in tests.
            # This is a *small* view (kb-only), not the full grounding_pack.
            gp_trace = tr2 if isinstance(tr2, dict) else {}
            gp_kb = (
                gp.get("kb_retrieved")
                if isinstance(gp.get("kb_retrieved"), dict)
                else {}
            )

            kb_meta = (
                gp_trace.get("kb_meta")
                if isinstance(gp_trace.get("kb_meta"), dict)
                else {}
            )
            kb_hits = (
                gp_trace.get("kb_hits")
                if isinstance(gp_trace.get("kb_hits"), int)
                else None
            )
            kb_used_entry_ids = (
                gp_trace.get("kb_used_entry_ids")
                if isinstance(gp_trace.get("kb_used_entry_ids"), list)
                else None
            )

            # Fallbacks (still grounded on GroundingPackService output).
            if not kb_meta and isinstance(gp_kb.get("meta"), dict):
                kb_meta = gp_kb.get("meta")  # type: ignore[assignment]
            if kb_hits is None:
                kb_hits = (
                    int(kb_meta.get("hit_count"))
                    if isinstance(kb_meta, dict)
                    and isinstance(kb_meta.get("hit_count"), int)
                    else 0
                )
            if kb_used_entry_ids is None:
                kb_used_entry_ids = (
                    gp_kb.get("used_entry_ids")
                    if isinstance(gp_kb.get("used_entry_ids"), list)
                    else []
                )

            out["context"] = {
                "grounding_pack": {
                    "kb_meta": kb_meta,
                    "kb_hits": int(kb_hits),
                    "kb_used_entry_ids": kb_used_entry_ids[:16]
                    if isinstance(kb_used_entry_ids, list)
                    else kb_used_entry_ids,
                }
            }
        return out

    async def _knowledge_bundle(*, request: Optional[Request] = None) -> Dict[str, Any]:
        """Enterprise contract: /api/chat always returns SSOT snapshot fields.

        CANON: knowledge_snapshot is server-owned.
        - Read path MUST remain pure: KnowledgeSnapshotService.get_snapshot() has no IO.
        - Request boundary: if snapshot is not ready or expired, refresh best-effort.
        - Fail-soft: never block /api/chat on refresh failures.
        """

        # Request-scope memoization (avoid duplicate refresh work within a single request).
        try:
            if request is not None:
                cached = getattr(request.state, "knowledge_bundle", None)
                if isinstance(cached, dict):
                    return cached
        except Exception:
            pass

        try:
            from services.knowledge_snapshot_service import (  # noqa: PLC0415
                KnowledgeSnapshotService,
            )

            ks = KnowledgeSnapshotService.get_snapshot()
        except Exception:
            ks = {}

        if not isinstance(ks, dict):
            ks = {}

        def _needs_refresh(snap: Dict[str, Any]) -> bool:
            try:
                if bool(snap.get("expired") is True):
                    return True
                if bool(snap.get("ready") is not True):
                    return True
                st = snap.get("status")
                if isinstance(st, str) and st.strip() in {"missing_data"}:
                    return True
            except Exception:
                return True
            return False

        if _needs_refresh(ks):
            # Tests/CI must remain offline and deterministic (no network calls).
            is_test_mode = (os.getenv("TESTING") or "").strip() == "1" or (
                "PYTEST_CURRENT_TEST" in os.environ
            )
            try:
                from dependencies import (  # noqa: PLC0415
                    services_status,
                    get_sync_service,
                )

                if (not is_test_mode) and bool(services_status().get("sync")):
                    sync = get_sync_service()
                    ok = await sync.sync_knowledge_snapshot()
                    if ok:
                        try:
                            ks2 = KnowledgeSnapshotService.get_snapshot()
                            if isinstance(ks2, dict):
                                ks = ks2
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning("knowledge_snapshot_refresh_failed: %s", exc)

        snapshot_meta = {
            "knowledge_status": ks.get("status"),
            "knowledge_last_sync": ks.get("last_sync"),
            "knowledge_generated_at": ks.get("generated_at"),
            "knowledge_ready": bool(ks.get("ready"))
            if isinstance(ks.get("ready"), bool)
            else bool(ks.get("ready")),
            "knowledge_expired": bool(ks.get("expired"))
            if isinstance(ks.get("expired"), bool)
            else bool(ks.get("expired")),
            "knowledge_ttl_seconds": ks.get("ttl_seconds"),
            "knowledge_age_seconds": ks.get("age_seconds"),
            "schema_version": ks.get("schema_version"),
        }

        out = {"knowledge_snapshot": ks, "snapshot_meta": snapshot_meta}
        try:
            if request is not None:
                request.state.knowledge_bundle = out
        except Exception:
            pass
        return out

    def _extract_prompt(payload: AgentInput) -> str:
        for k in ("message", "text", "input_text", "prompt"):
            v = getattr(payload, k, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _extract_session_id(payload: AgentInput) -> Optional[str]:
        """
        PHASE 6: Notion Ops ARMED Gate
        Best-effort extraction from payload/metadata.
        NOTE: the /api/chat endpoint may generate a session_id when missing.
        """
        for attr in ("session_id", "sessionId"):
            v = getattr(payload, attr, None)
            if isinstance(v, str) and v.strip():
                return v.strip()

        md = getattr(payload, "metadata", None)
        if isinstance(md, dict):
            v = md.get("session_id") or md.get("sessionId")
            if isinstance(v, str) and v.strip():
                return v.strip()

        return None

    def _extract_conversation_id(payload: AgentInput) -> Optional[str]:
        v = getattr(payload, "conversation_id", None)
        if isinstance(v, str) and v.strip():
            return v.strip()
        return None

    def _responses_mode_enabled() -> bool:
        return (
            os.getenv("OPENAI_API_MODE") or "assistants"
        ).strip().lower() == "responses"

    def _require_conversation_id() -> bool:
        v = (os.getenv("CEO_RESPONSES_REQUIRE_CONVERSATION_ID") or "").strip().lower()
        return v in {"1", "true", "yes", "on"}

    def _norm_text(s: str) -> str:
        return " ".join((s or "").strip().lower().split())

    def _norm_bhs_ascii(text: str) -> str:
        t = (text or "").strip().lower()
        if not t:
            return ""
        return (
            t.replace("č", "c")
            .replace("ć", "c")
            .replace("š", "s")
            .replace("đ", "dj")
            .replace("ž", "z")
        )

    def _is_short_confirmation(text: str) -> bool:
        """True only for short, explicit confirmations.

        IMPORTANT: must NOT match normal questions like "da li...".
        """

        raw = (text or "").strip()
        if not raw:
            return False

        # Defensive: do not treat questions as confirmations.
        if "?" in raw:
            return False

        t = _norm_bhs_ascii(raw)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = " ".join(t.split())

        if not t:
            return False
        if t.startswith("da li ") or t.startswith("da l "):
            return False

        allowed = {
            "da",
            "yes",
            "y",
            "ok",
            "okay",
            "u redu",
            "uredu",
            "zelim",
            "hocu",
            "hoc u",
            "moze",
            "moze to",
            "potvrdi",
            "confirm",
            "slazem se",
            "uradi to",
            "go ahead",
            "proceed",
        }
        if t in allowed:
            return True

        # Also allow tiny variants like "da, zelim".
        if len(t) <= 20 and re.fullmatch(
            r"(da|zelim|ok|okay|potvrdi|confirm|yes|y)(\s+(da|zelim|ok|okay|yes|y))?",
            t,
        ):
            return True

        return False

    def _is_short_decline(text: str) -> bool:
        """True only for short, explicit declines.

        Used to cancel/clear pending proposals so users don't get stuck in
        confirmation loops.
        """

        raw = (text or "").strip()
        if not raw:
            return False

        # Defensive: do not treat questions as declines.
        if "?" in raw:
            return False

        t = _norm_bhs_ascii(raw)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = " ".join(t.split())

        if not t:
            return False
        if t.startswith("da li ") or t.startswith("da l "):
            return False

        allowed = {
            "ne",
            "no",
            "n",
            "nemoj",
            "nemam namjeru",
            "samo pitanje",
            "ne trazim",
            "odustani",
            "otkazi",
            "dismiss",
            "stop",
            "cancel",
            "ignore",
            "not now",
            "no thanks",
            "ne hvala",
            "ne zelim",
            "necu",
            "necu to",
        }
        if t in allowed:
            return True

        # Also allow tiny variants like "ne, hvala".
        if len(t) <= 24 and re.fullmatch(
            r"(ne|no|n|nemoj|cancel|stop)(\s+(hvala|thanks))?",
            t,
        ):
            return True

        return False

    def _is_pending_proposal_dismiss(text: str) -> bool:
        """Return True if the user is explicitly dismissing a pending proposal.

        This is intentionally a broader match than _is_short_decline because users
        often reply with longer clarifications like "samo pitanje".
        """

        raw = (text or "").strip()
        if not raw:
            return False

        t = _norm_bhs_ascii(raw)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = " ".join(t.split())
        if not t:
            return False

        # Exact single-token dismisses.
        if t in {
            "ne",
            "no",
            "n",
            "nemoj",
            "necu",
            "ne zelim",
            "otkazi",
            "cancel",
            "dismiss",
            "stop",
            "ignore",
        }:
            return True

        # Phrase-based dismisses (BHS+EN) that should clear pending state.
        for phrase in (
            "nemam namjeru",
            "samo pitanje",
            "ne trazim",
        ):
            if re.search(r"\b" + re.escape(phrase) + r"\b", t):
                return True

        return False

    def _pending_prompt_count(*, conversation_id: Optional[str]) -> int:
        if not (isinstance(conversation_id, str) and conversation_id.strip()):
            return 0
        try:
            meta = ConversationStateStore.get_meta(
                conversation_id=conversation_id.strip()
            )
            if not isinstance(meta, dict):
                return 0
            v = meta.get("pending_proposal_confirm_prompt_count")
            return int(v) if isinstance(v, (int, float)) else 0
        except Exception:
            return 0

    def _pending_prompt_bump(*, conversation_id: Optional[str]) -> int:
        if not (isinstance(conversation_id, str) and conversation_id.strip()):
            return 0
        try:
            cur = _pending_prompt_count(conversation_id=conversation_id)
            nxt = int(cur) + 1
            ConversationStateStore.update_meta(
                conversation_id=conversation_id.strip(),
                updates={
                    "pending_proposal_confirm_prompt_count": nxt,
                    "pending_proposal_confirm_prompt_last_at": float(time.time()),
                },
            )
            return nxt
        except Exception:
            return 0

    def _pending_prompt_reset(*, conversation_id: Optional[str]) -> None:
        if not (isinstance(conversation_id, str) and conversation_id.strip()):
            return
        try:
            ConversationStateStore.update_meta(
                conversation_id=conversation_id.strip(),
                updates={"pending_proposal_confirm_prompt_count": 0},
            )
        except Exception:
            return

    def _classify_pending_response(text: str) -> str:
        """Classify user reply when a pending proposal exists.

        Returns: YES | NO | NEW_REQUEST | UNKNOWN
        """
        if _is_short_confirmation(text):
            return "YES"

        # Broad dismiss handling: clear pending proposals without looping.
        if _is_pending_proposal_dismiss(text):
            return "NO"
        if _is_short_decline(text):
            return "NO"

        raw = (text or "").strip()
        if not raw:
            return "UNKNOWN"

        t = _norm_bhs_ascii(raw)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = " ".join(t.split())
        if not t:
            return "UNKNOWN"
        if t.startswith("da li ") or t.startswith("da l "):
            return "UNKNOWN"

        neg = bool(
            re.search(
                r"(?i)\b("
                r"ne|nemoj|necu|ne\s+zelim|"
                r"nemam\s+namjeru|samo\s+pitanje|ne\s+trazim|"
                r"odustani|otkazi|dismiss|ignore|"
                r"stop|cancel|preskoci|skip|umjesto|instead|bez"
                r")\b",
                t,
            )
        )
        req = bool(
            re.search(
                r"(?i)\b(treba\s+mi|hoc\w*|uradi|napravi|pripremi|daj\s+mi|plan|prioritet\w*|strateg\w*|funnel|marketing|sales|prodaj\w*|kampanj\w*|sekvenc\w*|email\w*|poruk\w*)\b",
                t,
            )
        )

        if neg and req:
            return "NEW_REQUEST"
        if neg:
            return "NO"
        if req:
            return "NEW_REQUEST"

        return "UNKNOWN"

    def _load_pending_proposal(
        conversation_id: Optional[str],
    ) -> Optional[List[Dict[str, Any]]]:
        if not (isinstance(conversation_id, str) and conversation_id.strip()):
            return None

        try:
            meta = ConversationStateStore.get_meta(
                conversation_id=conversation_id.strip()
            )
        except Exception:
            return None

        if not isinstance(meta, dict):
            return None

        pcs = meta.get("pending_proposed_commands")
        if not isinstance(pcs, list) or not pcs:
            return None

        # Optional TTL (fail-open: if missing, allow).
        ts = meta.get("pending_proposal_created_at")
        if isinstance(ts, (int, float)):
            if (time.time() - float(ts)) > 15 * 60:
                return None

        # Ensure list items are dicts.
        out = [x for x in pcs if isinstance(x, dict) and x]
        return out or None

    def _persist_pending_proposal(
        conversation_id: Optional[str], proposed_commands_out: List[Dict[str, Any]]
    ) -> None:
        if not (isinstance(conversation_id, str) and conversation_id.strip()):
            return
        try:
            updates: Dict[str, Any] = {}
            if isinstance(proposed_commands_out, list) and proposed_commands_out:
                updates = {
                    "pending_proposal": True,
                    "pending_proposed_commands": proposed_commands_out,
                    "pending_proposal_created_at": float(time.time()),
                }
            else:
                updates = {
                    "pending_proposal": False,
                    "pending_proposed_commands": [],
                }

            ConversationStateStore.update_meta(
                conversation_id=conversation_id.strip(),
                updates=updates,
            )
        except Exception:
            return

    def _is_activate(text: str) -> bool:
        t = _norm_text(text)
        return any(k in t for k in _ACTIVATE_KEYWORDS)

    def _is_deactivate(text: str) -> bool:
        t = _norm_text(text)
        return any(k in t for k in _DEACTIVATE_KEYWORDS)

    async def _set_armed(
        session_id: str, armed: bool, *, prompt: str
    ) -> Dict[str, Any]:
        """
        PHASE 6: Notion Ops ARMED Gate
        SSOT session state - delegates to shared state module.

        Note: This function sets the state for ANY session_id.
        Access control should be handled by the caller (e.g., chat endpoint).
        CEO users can activate without restrictions.
        """
        return await _set_armed_shared(session_id, armed, prompt=prompt)

    async def _get_state(session_id: str) -> Dict[str, Any]:
        """
        PHASE 6: Notion Ops ARMED Gate
        Gets session state - delegates to shared state module.
        """
        return await _get_state_shared(session_id)

    def _debug_enabled(payload: AgentInput) -> bool:
        md = getattr(payload, "metadata", None)
        include_debug = False
        if isinstance(md, dict):
            v = md.get("include_debug")
            include_debug = v is True or (
                isinstance(v, str) and v.strip().lower() in {"1", "true", "yes", "on"}
            )

        env = (os.getenv("DEBUG_API_RESPONSES") or "").strip().lower()
        env_debug = env in {"1", "true", "yes", "on"}
        return bool(include_debug or env_debug)

    def _debug_enabled_request(request: Request) -> bool:
        def _truthy(v: Any) -> bool:
            if v is True:
                return True
            if not isinstance(v, str):
                return False
            return v.strip().lower() in {"1", "true", "yes", "on"}

        try:
            if _truthy(request.headers.get("X-Debug")):
                return True
        except Exception:
            pass

        try:
            qp = request.query_params.get("include_debug")
            if _truthy(qp):
                return True
        except Exception:
            pass

        return False

    def _minimal_trace_intent(trace_obj: Any) -> Dict[str, Any]:
        if not isinstance(trace_obj, dict):
            return {}
        out: Dict[str, Any] = {}

        intent = trace_obj.get("intent")
        if isinstance(intent, str) and intent.strip():
            out["intent"] = intent.strip()

        used = trace_obj.get("used_sources")
        if isinstance(used, list):
            out["used_sources"] = [x for x in used if isinstance(x, str) and x.strip()]

        snap = trace_obj.get("snapshot")
        if isinstance(snap, dict) and snap:
            out["snapshot"] = snap

        # KB debug/meta pass-through (required for TTL/cache verification in API smoke tests).
        kb_meta = trace_obj.get("kb_meta")
        if isinstance(kb_meta, dict):
            out["kb_meta"] = kb_meta

        kb_hits = trace_obj.get("kb_hits")
        if isinstance(kb_hits, int):
            out["kb_hits"] = int(kb_hits)

        kb_used_entry_ids = trace_obj.get("kb_used_entry_ids")
        if isinstance(kb_used_entry_ids, list):
            out["kb_used_entry_ids"] = kb_used_entry_ids[:16]
        elif kb_used_entry_ids is not None:
            # Preserve non-list values verbatim (debug)
            out["kb_used_entry_ids"] = kb_used_entry_ids

        return out

    def _ensure_trace_snapshot_and_sources(
        trace_obj: Any,
        *,
        grounding_pack: Dict[str, Any],
        snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        tr = trace_obj if isinstance(trace_obj, dict) else {}

        # Mirror snapshot into trace (stable, non-null payload lists).
        try:
            tr["snapshot"] = _normalize_snapshot_wrapper(snapshot)
        except Exception:
            tr["snapshot"] = snapshot if isinstance(snapshot, dict) else {}

        # Derive used_sources from grounding_pack trace_v2, plus notion_snapshot.
        used_existing = (
            tr.get("used_sources") if isinstance(tr.get("used_sources"), list) else []
        )
        used_set = {x for x in used_existing if isinstance(x, str) and x.strip()}

        gp_trace = (
            grounding_pack.get("trace")
            if isinstance(grounding_pack.get("trace"), dict)
            else {}
        )
        used_raw = (
            gp_trace.get("used_sources")
            if isinstance(gp_trace.get("used_sources"), list)
            else []
        )
        used_raw = [x for x in used_raw if isinstance(x, str) and x.strip()]
        mapping = {"kb_snapshot": "kb", "memory_snapshot": "memory"}
        used_set |= {mapping.get(x, x) for x in used_raw}

        # Always include notion_snapshot when we injected a snapshot.
        used_set.add("notion_snapshot")

        tr["used_sources"] = sorted(used_set)
        return tr

    def _apply_kb_trace_passthrough_from_context(
        trace_obj: Any,
        *,
        grounding_bundle: Dict[str, Any],
    ) -> None:
        """Pass-through KB debug/meta fields into the API trace.

        IMPORTANT:
        - No new network calls: uses already-built grounding_bundle.
        - Kept here (response-assembly path) so tests can prove it.
        """

        if not isinstance(trace_obj, dict):
            return

        ctx = (
            grounding_bundle.get("context")
            if isinstance(grounding_bundle, dict)
            else None
        )
        ctx_gp = ctx.get("grounding_pack") if isinstance(ctx, dict) else None
        if isinstance(ctx_gp, dict):
            if isinstance(ctx_gp.get("kb_meta"), dict):
                trace_obj["kb_meta"] = ctx_gp.get("kb_meta")
            if isinstance(ctx_gp.get("kb_hits"), int):
                trace_obj["kb_hits"] = int(ctx_gp.get("kb_hits"))
            if "kb_used_entry_ids" in ctx_gp:
                ids = ctx_gp.get("kb_used_entry_ids")
                if isinstance(ids, list):
                    trace_obj["kb_used_entry_ids"] = ids[:16]
                else:
                    trace_obj["kb_used_entry_ids"] = ids

        # Keep existing derived fields stable for other tests.
        gp = (
            grounding_bundle.get("grounding_pack")
            if isinstance(grounding_bundle, dict)
            else None
        )
        gp_kb = (
            gp.get("kb_retrieved")
            if isinstance(gp, dict) and isinstance(gp.get("kb_retrieved"), dict)
            else {}
        )
        kb_entries = (
            gp_kb.get("entries") if isinstance(gp_kb.get("entries"), list) else []
        )
        kb_ids_used = (
            [
                x
                for x in (gp_kb.get("used_entry_ids") or [])
                if isinstance(x, str) and x.strip()
            ]
            if isinstance(gp_kb.get("used_entry_ids"), list)
            else []
        )

        kb_meta = (
            trace_obj.get("kb_meta")
            if isinstance(trace_obj.get("kb_meta"), dict)
            else {}
        )
        if isinstance(kb_meta, dict):
            trace_obj.setdefault(
                "kb_loaded_total",
                kb_meta.get("total_entries")
                if isinstance(kb_meta.get("total_entries"), int)
                else None,
            )

        trace_obj.setdefault("kb_ids_used", kb_ids_used)
        trace_obj.setdefault("kb_entries_injected", len(kb_entries))

        # Back-compat fields (kept stable for downstream tooling).
        trace_obj.setdefault("kb_used_entry_ids", kb_ids_used[:16])
        trace_obj.setdefault(
            "kb_hits",
            kb_meta.get("hit_count")
            if isinstance(kb_meta, dict) and isinstance(kb_meta.get("hit_count"), int)
            else len(kb_entries),
        )

    def _normalize_proposed_commands(raw: Any) -> List[ProposedCommand]:
        if raw is None:
            return []
        items = [raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        out: List[ProposedCommand] = []
        for item in items:
            try:
                pc = (
                    ProposedCommand.model_validate(item)
                    if hasattr(ProposedCommand, "model_validate")
                    else ProposedCommand.parse_obj(item)
                )
            except Exception:
                d = item if isinstance(item, dict) else {}
                args = d.get("args") or d.get("params") or {}
                pc = ProposedCommand(
                    command=str(d.get("command") or ""),
                    args=args if isinstance(args, dict) else {},
                )

            try:
                pc.dry_run = True
            except Exception:
                pass

            out.append(pc)

        return out

    def _looks_like_preview_request(text: str) -> bool:
        t = (text or "").strip().lower()
        if not t:
            return False

        notion_markers = (
            "notion",
            "notion ops",
            "notion upis",
            "notion write",
        )
        preview_markers = (
            "preview",
            "pregled",
            "prikaz",
            "show preview",
            "show payload",
            "samo preview",
        )
        no_execute_markers = (
            "nemoj izvršiti",
            "nemoj izvrsiti",
            "bez izvršenja",
            "bez izvrsenja",
            "no execute",
            "do not execute",
            "don't execute",
        )
        prepare_markers = (
            "pripremi",
            "prepare",
            "pretvori",
            "transform",
            "convert",
        )
        structure_markers = (
            "goal",
            "cilj",
            "task",
            "zadat",
            "zadac",
        )

        has_notion_target = any(k in t for k in notion_markers)
        has_structure_target = any(k in t for k in structure_markers)
        has_preview_word = any(k in t for k in preview_markers)
        has_no_execute = any(k in t for k in no_execute_markers)
        has_prepare_word = any(k in t for k in prepare_markers)

        if has_notion_target and (
            has_preview_word or has_no_execute or has_prepare_word
        ):
            return True

        return (
            has_structure_target
            and has_prepare_word
            and (has_preview_word or has_no_execute)
        )

    def _looks_like_write_intent(text: str) -> bool:
        t = (text or "").strip().lower()
        if not t:
            return False
        # IMPORTANT:
        # - /api/chat is canonical read-only.
        # - We only want to enforce the ARMED gate when the user is asking for
        #   an actual write operation (create/update/delete/archive), not when
        #   they mention concepts like "goal/cilj/task" in advisory questions.
        write_verbs = (
            "create",
            "kreiraj",
            "napravi",
            "pretvori",
            "transform",
            "convert",
            "pripremi",
            "prepare",
            "povezi",
            "poveži",
            "link",
            "linkaj",
            "dodaj",
            "update",
            "azuriraj",
            "ažuriraj",
            "izmijeni",
            "izmeni",
            "promijeni",
            "promeni",
            "delete",
            "obrisi",
            "obriši",
            "ukloni",
            "archive",
            "arhiviraj",
        )

        explicit_targeting = (
            "db:",
            "database:",
            "database id",
            "database_id",
            "page_id",
        )

        if any(k in t for k in explicit_targeting):
            return True

        if _looks_like_preview_request(t):
            return True

        # Avoid hijacking generic phrasing like "napravi email"; for Notion gating,
        # require an explicit Notion mention (or explicit targeting above).
        if "notion" not in t:
            return False

        return any(k in t for k in write_verbs)

    def _armed_write_ack(prompt: str, *, has_actionable: bool) -> str:
        if has_actionable:
            return "Notion Ops je spreman. Pregledaj prijedlog i odobri izvršenje."
        # write intent but no structured proposal
        return (
            "Zahtjev izgleda kao write, ali treba dodatno preciziranje prije izvršenja."
        )

    def _build_contract_noop_wrapper(prompt: str, *, reason: str) -> ProposedCommand:
        safe_prompt = (prompt or "").strip() or "noop"
        pc = ProposedCommand(
            command=PROPOSAL_WRAPPER_INTENT,
            args={"prompt": safe_prompt},
            reason=reason,
            dry_run=True,
            requires_approval=False,
            risk="NONE",
            scope="none",
            payload_summary={
                "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                "source": "api_chat",
                "kind": "contract_noop",
            },
        )
        return pc

    def _build_approval_wrapper(prompt: str, *, reason: str) -> ProposedCommand:
        safe_prompt = (prompt or "").strip() or "noop"
        pc = ProposedCommand(
            command=PROPOSAL_WRAPPER_INTENT,
            args={"prompt": safe_prompt},
            reason=reason,
            dry_run=True,
            requires_approval=True,
            risk="LOW",
            scope="api_execute_raw",
            payload_summary={
                "endpoint": "/api/execute/raw",
                "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                "source": "api_chat",
                "confidence_score": 0.5,
                "assumption_count": 0,
                "recommendation_type": "OPERATIONAL",
            },
        )
        return pc

    def _preview_initiator(payload: AgentInput, session_id: Optional[str]) -> str:
        md = getattr(payload, "metadata", None)
        if isinstance(md, dict):
            for key in ("principal_sub", "initiator", "session_id"):
                value = md.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        identity_pack = getattr(payload, "identity_pack", None)
        if isinstance(identity_pack, dict):
            identity_payload = identity_pack.get("payload")
            if isinstance(identity_payload, dict):
                sub = identity_payload.get("sub")
                if isinstance(sub, str) and sub.strip():
                    return sub.strip()

        if isinstance(session_id, str) and session_id.strip():
            return session_id.strip()

        return "ceo_chat"

    async def _attach_preview_if_requested(
        content: Dict[str, Any],
        *,
        prompt: str,
        request: Request,
        payload: AgentInput,
        session_id: Optional[str],
    ) -> Dict[str, Any]:
        if not _looks_like_preview_request(prompt):
            return content

        raw_pcs = content.get("proposed_commands")
        pcs = raw_pcs if isinstance(raw_pcs, list) else []
        candidate = next(
            (
                pc
                for pc in pcs
                if isinstance(pc, dict)
                and isinstance(pc.get("command"), str)
                and pc.get("command", "").strip()
            ),
            None,
        )
        if not isinstance(candidate, dict):
            return content

        try:
            from gateway.gateway_server import execute_preview_command  # noqa: PLC0415

            preview = await execute_preview_command(
                request=request,
                payload=dict(candidate),
                principal=SimpleNamespace(sub=_preview_initiator(payload, session_id)),
            )
        except Exception:
            return content

        if not isinstance(preview, dict) or preview.get("ok") is not True:
            return content

        content["text"] = "Structured preview je spreman. Nema izvršenja."
        content["command"] = preview.get("command")
        content["review"] = preview.get("review")
        content["notion"] = preview.get("notion")

        trace0 = content.get("trace")
        trace0 = dict(trace0) if isinstance(trace0, dict) else {}
        trace0["chat_preview_bridge"] = {
            "enabled": True,
            "canon": "api_chat_to_execute_preview",
            "source_command": candidate.get("command"),
            "source_intent": candidate.get("intent") or candidate.get("command"),
        }
        content["trace"] = trace0
        return content

    def _pc_to_dict(pc: ProposedCommand, *, prompt: str) -> Dict[str, Any]:
        d = (
            pc.model_dump(by_alias=False)
            if hasattr(pc, "model_dump")
            else pc.dict(by_alias=False)
        )
        if not isinstance(d, dict):
            return {}
        args = d.get("args")
        if not isinstance(args, dict):
            args = {}
            d["args"] = args

        # Legacy behavior: wrapper proposals expect a prompt for Notion translation.
        # Canonical exception: memory_write.v1 proposals must not carry free-form prompt.
        if d.get("command") == PROPOSAL_WRAPPER_INTENT:
            schema = args.get("schema_version")
            is_memory_write_v1 = (
                isinstance(schema, str) and schema.strip() == "memory_write.v1"
            )
            if not is_memory_write_v1:
                p = args.get("prompt")
                if not isinstance(p, str) or not p.strip():
                    args["prompt"] = (prompt or "").strip() or "noop"
        return d

    def _ensure_payload_summary_contract(pc_dict: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(pc_dict, dict):
            return {}

        ps = pc_dict.get("payload_summary")
        if not isinstance(ps, dict):
            ps = {}
            pc_dict["payload_summary"] = ps

        kind = ps.get("kind")
        is_noop = kind == "contract_noop"

        cs = ps.get("confidence_score")
        if not isinstance(cs, (int, float)):
            cs = 1.0 if is_noop else 0.5
        csf = float(cs)
        if csf < 0.0:
            csf = 0.0
        if csf > 1.0:
            csf = 1.0
        ps["confidence_score"] = csf

        ac = ps.get("assumption_count")
        if not isinstance(ac, int) or ac < 0:
            ac = 0
        ps["assumption_count"] = ac

        rt = ps.get("recommendation_type")
        if not isinstance(rt, str) or not rt.strip():
            ps["recommendation_type"] = "INFORMATIONAL" if is_noop else "OPERATIONAL"

        return pc_dict

    def _is_actionable(pc: ProposedCommand) -> bool:
        cmd = getattr(pc, "command", None)
        if not isinstance(cmd, str) or not cmd.strip():
            return False
        if cmd == PROPOSAL_WRAPPER_INTENT:
            return False
        if cmd in _NON_ACTIONABLE_PROPOSALS:
            return False
        return True

    def _finalize_actionable(pc: ProposedCommand) -> None:
        try:
            pc.dry_run = True
        except Exception:
            pass

        try:
            if getattr(pc, "requires_approval", None) is not True:
                pc.requires_approval = True
        except Exception:
            pass

        try:
            scope = getattr(pc, "scope", None)
            if not isinstance(scope, str) or not scope.strip():
                pc.scope = "api_execute_raw"
        except Exception:
            pass

        try:
            risk = getattr(pc, "risk", None)
            if not isinstance(risk, str) or not risk.strip():
                pc.risk = "LOW"
        except Exception:
            pass

    def _blocked_response(
        *,
        out: Any,
        prompt: str,
        session_id: Optional[str],
        state: Dict[str, Any],
        why: str,
        kb: Dict[str, Any],
        grounding: Dict[str, Any],
        debug_on: bool,
        audit_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> JSONResponse:
        msg = "Notion Ops nije aktivan. Želiš aktivirati? (napiši: 'notion ops aktiviraj' / 'notion ops uključi')"
        if isinstance(why, str) and why.strip():
            msg = f"{msg}\n\nReason: {why}"

        # IMPORTANT: do not emit notion_ops_toggle proposals here.
        # Arming/disarming is a CEO-only direct endpoint and should be invoked
        # explicitly by the user via chat keywords or the dedicated toggle route.
        pcs_out: List[Dict[str, Any]] = []

        tr = out.trace or {} if hasattr(out, "trace") else {}
        if not isinstance(tr, dict):
            tr = {}
        tr.setdefault("phase6_notion_ops_gate", {})
        tr["phase6_notion_ops_gate"] = {
            "armed": False,
            "session_id_present": bool(session_id),
            "why": why,
        }

        content: Dict[str, Any] = {
            "text": (getattr(out, "text", "") or "").strip() or msg,
            "proposed_commands": pcs_out,
            "agent_id": getattr(out, "agent_id", None),
            "read_only": True,
            "session_id": session_id,
            "notion_ops": {
                "armed": False,
                "armed_at": None,
                "session_id": session_id,
                "armed_state": state,
            },
        }

        if debug_on:
            content["trace"] = tr
            content.update(kb)
            content.update(grounding)
        else:
            mt = _minimal_trace_intent(tr)
            if mt:
                content["trace"] = mt

        if audit_fn is not None:
            try:
                content = audit_fn(content)
            except Exception:
                pass
        return JSONResponse(content=content)

    @router.post("/chat", response_model=AgentOutput, response_model_by_alias=False)
    async def chat(payload: AgentInput, request: Request):
        audit_request_id = uuid.uuid4().hex
        audit_started_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        debug_req_on = _debug_enabled_request(request)

        def _truthy(v: Any) -> bool:
            if v is True:
                return True
            if not isinstance(v, str):
                return False
            return v.strip().lower() in {"1", "true", "yes", "on"}

        def _snapshot_counts(snap: Any) -> Dict[str, Any]:
            s = snap if isinstance(snap, dict) else {}
            payload0 = s.get("payload") if isinstance(s.get("payload"), dict) else None
            payload = (
                payload0
                if isinstance(payload0, dict)
                else (s if isinstance(s, dict) else {})
            )
            if not isinstance(payload, dict):
                payload = {}

            def _count_list(x: Any) -> int:
                return int(len(x)) if isinstance(x, list) else 0

            dash = (
                payload.get("dashboard")
                if isinstance(payload.get("dashboard"), dict)
                else {}
            )
            out = {
                "ready": bool(s.get("ready") is True),
                "status": s.get("status"),
                "schema_version": s.get("schema_version"),
                "last_sync": s.get("last_sync")
                or (
                    payload.get("last_sync")
                    if isinstance(payload.get("last_sync"), str)
                    else None
                ),
                "goals": _count_list(payload.get("goals")),
                "tasks": _count_list(payload.get("tasks")),
                "projects": _count_list(payload.get("projects")),
                "dashboard_goals": _count_list(dash.get("goals")),
                "dashboard_tasks": _count_list(dash.get("tasks")),
                "dashboard_projects": _count_list(dash.get("projects")),
                "has_dashboard": bool(isinstance(payload.get("dashboard"), dict)),
            }
            return out

        def _grounding_trace_v2(grounding: Any) -> Dict[str, Any]:
            if not isinstance(grounding, dict):
                return {}
            tr2 = (
                grounding.get("trace_v2")
                if isinstance(grounding.get("trace_v2"), dict)
                else None
            )
            if isinstance(tr2, dict):
                return tr2
            gp = (
                grounding.get("grounding_pack")
                if isinstance(grounding.get("grounding_pack"), dict)
                else {}
            )
            tr = gp.get("trace") if isinstance(gp.get("trace"), dict) else {}
            return tr if isinstance(tr, dict) else {}

        def _attach_and_log_audit(
            content: Dict[str, Any],
            *,
            session_id: Optional[str],
            conversation_id: Optional[str],
            agent_id: Optional[str],
            snapshot: Any,
            trace: Any,
            grounding: Any,
            debug_on: bool,
            exit_path: str,
            targeted_reads: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            # Build audit (no raw Notion data; counts + reasons only).
            snap_counts = _snapshot_counts(snapshot)
            trace0 = trace if isinstance(trace, dict) else {}
            snap_trace = (
                trace0.get("snapshot")
                if isinstance(trace0.get("snapshot"), dict)
                else {}
            )
            gp_trace = _grounding_trace_v2(grounding)

            snapshot_tasks_count = int(snap_counts.get("tasks") or 0)
            extracted_tasks_count = (
                int(snap_trace.get("extracted_tasks_count") or 0)
                if isinstance(snap_trace, dict)
                else 0
            )
            if extracted_tasks_count == 0:
                extracted_tasks_count = (
                    int(snap_trace.get("tasks_count") or 0)
                    if isinstance(snap_trace, dict)
                    else 0
                )
            final_tasks_count_used_by_llm = (
                int(snap_trace.get("final_tasks_count_used_by_llm") or 0)
                if isinstance(snap_trace, dict)
                else extracted_tasks_count
            )
            if final_tasks_count_used_by_llm == 0:
                final_tasks_count_used_by_llm = extracted_tasks_count
            invariant_triggered = bool(
                isinstance(snap_trace, dict)
                and snap_trace.get("invariant_triggered") is True
            )
            extraction_source_priority = (
                snap_trace.get("extraction_source_priority")
                if isinstance(snap_trace, dict)
                else None
            )
            if (
                not isinstance(extraction_source_priority, str)
                or not extraction_source_priority.strip()
            ):
                extraction_source_priority = None

            mismatch = None
            try:
                if (
                    int(snap_counts.get("tasks") or 0) > 0
                    and int(snap_trace.get("tasks_count") or 0) == 0
                ):
                    mismatch = {
                        "kind": "tasks_missing_in_agent_trace",
                        "snapshot_tasks": int(snap_counts.get("tasks") or 0),
                        "agent_tasks": int(snap_trace.get("tasks_count") or 0),
                    }
                    if gp_trace.get("budget_exceeded") is True:
                        mismatch["reason"] = "grounding_budget_exceeded"
                    elif (
                        isinstance(targeted_reads, dict)
                        and targeted_reads.get("cache_hit") is True
                    ):
                        mismatch["reason"] = "targeted_reads_cache_hit"
                    else:
                        mismatch["reason"] = "unknown"
            except Exception:
                mismatch = None

            audit_level = "ERROR" if invariant_triggered else "INFO"

            audit: Dict[str, Any] = {
                "level": audit_level,
                "ts": audit_started_at,
                "request_id": audit_request_id,
                "exit_path": exit_path,
                "agent_id": agent_id,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "debug_requested": bool(debug_req_on),
                "snapshot_tasks_count": snapshot_tasks_count,
                "extracted_tasks_count": extracted_tasks_count,
                "final_tasks_count_used_by_llm": final_tasks_count_used_by_llm,
                "invariant_triggered": bool(invariant_triggered),
                "extraction_source_priority": extraction_source_priority,
                "snapshot": snap_counts,
                "agent_trace_snapshot": {
                    "ready": snap_trace.get("ready"),
                    "available": snap_trace.get("available"),
                    "tasks_count": snap_trace.get("tasks_count"),
                    "goals_count": snap_trace.get("goals_count"),
                    "source": snap_trace.get("source"),
                }
                if isinstance(snap_trace, dict)
                else {},
                "grounding": {
                    "enabled": bool(
                        isinstance(grounding, dict)
                        and isinstance(grounding.get("grounding_pack"), dict)
                        and grounding.get("grounding_pack", {}).get("enabled")
                        is not False
                    ),
                    "budget_exceeded": bool(gp_trace.get("budget_exceeded") is True),
                    "payload_bytes": gp_trace.get("payload_bytes"),
                    "used_sources": gp_trace.get("used_sources"),
                    "not_used": gp_trace.get("not_used"),
                },
                "targeted_reads": targeted_reads or {},
            }
            if mismatch:
                audit["mismatch"] = mismatch

            try:
                line = json.dumps(audit, ensure_ascii=False, separators=(",", ":"))
                if audit_level == "ERROR":
                    logger.error("CEO_AUDIT %s", line)
                else:
                    logger.info("CEO_AUDIT %s", line)
            except Exception:
                pass

            if debug_on:
                try:
                    dbg = (
                        content.get("debug")
                        if isinstance(content.get("debug"), dict)
                        else {}
                    )
                    dbg = dict(dbg)
                    dbg["audit"] = audit
                    content["debug"] = dbg
                except Exception:
                    pass
            return content

        def _norm_bhs_ascii(text: str) -> str:
            t = (text or "").lower()
            return (
                t.replace("č", "c")
                .replace("ć", "c")
                .replace("š", "s")
                .replace("đ", "dj")
                .replace("ž", "z")
            )

        def _snapshot_tasks_list(snapshot: Any) -> List[Dict[str, Any]]:
            if not isinstance(snapshot, dict):
                return []
            payload = snapshot.get("payload")
            payload = payload if isinstance(payload, dict) else snapshot

            # Canonical SSOT collections live under payload.*.
            # _normalize_snapshot_wrapper already back-fills payload.* from dashboard.* when needed.
            payload_tasks = payload.get("tasks") if isinstance(payload, dict) else None
            if isinstance(payload_tasks, list):
                return [t for t in payload_tasks if isinstance(t, dict)]
            return []

        def _pick_str(v: Any, default: str = "-") -> str:
            if v is None:
                return default
            if isinstance(v, str):
                s = v.strip()
                return s if s else default
            if isinstance(v, (int, float, bool)):
                return str(v)
            if isinstance(v, dict):
                for k in ("title", "name", "value", "status"):
                    if k in v:
                        return _pick_str(v.get(k), default=default)
            return default

        def _pick_due(v: Any) -> str:
            if isinstance(v, str):
                return _pick_str(v)
            if isinstance(v, dict):
                for k in ("start", "date", "value"):
                    if k in v:
                        return _pick_due(v.get(k))
            return "-"

        def _render_snapshot_tasks_override(
            snapshot: Any, snapshot_tasks_count: int
        ) -> str:
            tasks = _snapshot_tasks_list(snapshot)
            lines: List[str] = [
                f"Imamo {int(snapshot_tasks_count)} taskova u Tasks DB.",
                "",
                "TASKS (top 5)",
            ]

            linked = 0
            unlinked = 0

            for i, it in enumerate(tasks[:5], start=1):
                fields = it.get("fields") if isinstance(it.get("fields"), dict) else {}

                title = _pick_str(
                    it.get("title")
                    or it.get("name")
                    or fields.get("title")
                    or fields.get("name")
                )
                status = _pick_str(
                    fields.get("status")
                    or fields.get("Status")
                    or it.get("status")
                    or it.get("Status")
                )
                due = _pick_due(fields.get("due") or fields.get("Due") or it.get("due"))

                goal_id = _pick_str(
                    it.get("goal_id") or fields.get("goal_id"), default=""
                )
                if goal_id:
                    linked += 1
                else:
                    unlinked += 1

                lines.append(f"{i}) {title} | {status} | {due}")

            if linked or unlinked:
                lines.append("")
                lines.append(
                    f"Povezano sa ciljevima: {linked} | Nepovezano: {unlinked}"
                )

            return "\n".join(lines).strip()

        def _snapshot_goals_list(snapshot: Any) -> List[Dict[str, Any]]:
            if not isinstance(snapshot, dict):
                return []
            payload = snapshot.get("payload")
            payload = payload if isinstance(payload, dict) else snapshot

            # Canonical SSOT collections live under payload.*.
            # _normalize_snapshot_wrapper already back-fills payload.* from dashboard.* when needed.
            payload_goals = payload.get("goals") if isinstance(payload, dict) else None
            if isinstance(payload_goals, list):
                return [g for g in payload_goals if isinstance(g, dict)]
            return []

        def _render_snapshot_goals_override(
            snapshot: Any, snapshot_goals_count: int
        ) -> str:
            goals = _snapshot_goals_list(snapshot)
            lines: List[str] = [
                f"Imamo {int(snapshot_goals_count)} ciljeva u Goals DB.",
                "",
                "GOALS (top 3)",
            ]

            for i, it in enumerate(goals[:3], start=1):
                fields = it.get("fields") if isinstance(it.get("fields"), dict) else {}
                title = _pick_str(
                    it.get("title")
                    or it.get("name")
                    or fields.get("title")
                    or fields.get("name")
                )
                status = _pick_str(
                    fields.get("status")
                    or fields.get("Status")
                    or it.get("status")
                    or it.get("Status")
                )
                due = _pick_due(fields.get("due") or fields.get("Due") or it.get("due"))
                lines.append(f"{i}) {title} | {status} | {due}")

            return "\n".join(lines).strip()

        def _apply_post_answer_snapshot_consistency_guard(
            text: str,
            *,
            snapshot: Any,
        ) -> str:
            snap_counts = _snapshot_counts(snapshot)
            snapshot_tasks_count = int(snap_counts.get("tasks") or 0)
            snapshot_goals_count = int(snap_counts.get("goals") or 0)
            if snapshot_tasks_count <= 0 and snapshot_goals_count <= 0:
                return text

            t = _norm_bhs_ascii(text or "")
            # Robust contradiction guard (BHS tolerant): negation + task/zadatak
            # Examples: "nema evidentiranih taskova", "trenutno nema zadataka", "bez taskova"
            if snapshot_tasks_count > 0 and re.search(
                r"(?i)\b(nema|nemamo|ne\s+postoji|bez)\b.*\b(task|zadac|zadat)\w*",
                t,
            ):
                return _render_snapshot_tasks_override(snapshot, snapshot_tasks_count)

            # Same for goals/ciljevi.
            if snapshot_goals_count > 0 and re.search(
                r"(?i)\b(nema|nemamo|ne\s+postoji|bez)\b.*\b(cilj|goal)\w*",
                t,
            ):
                return _render_snapshot_goals_override(snapshot, snapshot_goals_count)
            return text

        # ------------------------------------------------------------
        # MINIMAL ROUTING FIX (explicit Dept Ops only)
        # If caller explicitly requests Dept Ops (preferred_agent_id or prefix),
        # route directly to dept_ops_agent strict backend and return JSON-only.
        # HARD RULES:
        # - no fallback to CEO Advisor if this path fails
        # - do not add KB/memory to dept_ops_agent ctx
        # - keep /api/chat response shape stable
        # ------------------------------------------------------------
        try:
            msg0 = getattr(payload, "message", None)
            msg = msg0 if isinstance(msg0, str) else ""

            pref = getattr(payload, "preferred_agent_id", None)
            ctx_hint = getattr(payload, "context_hint", None)
            pref2 = None
            if isinstance(ctx_hint, dict):
                pref2 = ctx_hint.get("preferred_agent_id")
            else:
                pref2 = getattr(ctx_hint, "preferred_agent_id", None)

            effective_pref = pref if isinstance(pref, str) and pref.strip() else pref2
            effective_pref_norm = (
                effective_pref.strip().lower()
                if isinstance(effective_pref, str) and effective_pref.strip()
                else ""
            )

            explicit_fin_prefix = (
                (msg or "").strip().lower().startswith("dept finance:")
            )
            is_explicit_dept_finance = (
                effective_pref_norm == "dept_finance" or explicit_fin_prefix
            )

            explicit_prefix = (msg or "").strip().lower().startswith("dept ops:")
            is_explicit_dept_ops = effective_pref_norm == "dept_ops" or explicit_prefix
        except Exception:
            is_explicit_dept_finance = False
            is_explicit_dept_ops = False
            msg = (
                getattr(payload, "message", None) if hasattr(payload, "message") else ""
            )
            msg = msg if isinstance(msg, str) else ""

        # ------------------------------------------------------------
        # MINIMAL ROUTING FIX (explicit Dept Finance only)
        # If caller explicitly requests Dept Finance (preferred_agent_id or prefix),
        # route directly to dept_finance_agent strict backend and return JSON-only.
        # HARD RULES:
        # - no fallback to CEO Advisor if this path fails
        # - do not add KB/memory to dept_finance_agent ctx
        # - keep /api/chat response shape stable
        # ------------------------------------------------------------
        if is_explicit_dept_finance:
            from services.department_agents import dept_finance_agent  # noqa: PLC0415

            session_id = _extract_session_id(payload)
            if not (isinstance(session_id, str) and session_id.strip()):
                hdr = (request.headers.get("X-Session-Id") or "").strip()
                if hdr:
                    session_id = hdr
            if not (isinstance(session_id, str) and session_id.strip()):
                session_id = str(uuid.uuid4())
                try:
                    payload.session_id = session_id  # type: ignore[attr-defined]
                except Exception:
                    pass

            conversation_id = _extract_conversation_id(payload) or session_id
            if isinstance(conversation_id, str) and conversation_id.strip():
                try:
                    payload.conversation_id = conversation_id.strip()
                except Exception:
                    pass

            debug_on = bool(debug_req_on or _debug_enabled(payload))

            identity_pack = (
                payload.identity_pack
                if isinstance(getattr(payload, "identity_pack", None), dict)
                else {}
            )
            snapshot = (
                payload.snapshot
                if isinstance(getattr(payload, "snapshot", None), dict)
                else {}
            )
            md0 = (
                payload.metadata
                if isinstance(getattr(payload, "metadata", None), dict)
                else {}
            )

            dept_payload = AgentInput(
                message=msg,
                identity_pack=identity_pack,
                snapshot=snapshot,
                conversation_id=conversation_id,
                history=getattr(payload, "history", None),
                preferred_agent_id="dept_finance",
                metadata=md0,
            )

            try:
                out = await dept_finance_agent(
                    dept_payload, ctx={"conversation_id": conversation_id}
                )
            except Exception as exc:
                return JSONResponse(
                    status_code=500,
                    content=_attach_session_id(
                        _attach_and_log_audit(
                            {
                                "text": str(exc)
                                if str(exc)
                                else "dept_finance_strict_backend_failed",
                                "proposed_commands": [],
                                "agent_id": "dept_finance",
                                "read_only": True,
                                "trace": {
                                    "intent": "error",
                                    "exit_reason": "error.dept_finance_strict_backend_failed",
                                    "error_type": exc.__class__.__name__,
                                    "error": str(exc),
                                },
                                "session_id": session_id,
                            },
                            session_id=session_id,
                            conversation_id=conversation_id,
                            agent_id="dept_finance",
                            snapshot=snapshot,
                            trace={
                                "intent": "error",
                                "exit_reason": "error.dept_finance_strict_backend_failed",
                            },
                            grounding={},
                            debug_on=bool(debug_on),
                            exit_path="dept_finance.strict.error",
                        ),
                        session_id,
                    ),
                )

            st0 = (
                await _get_state(session_id)
                if session_id
                else {"armed": False, "armed_at": None}
            )

            tr0 = out.trace if hasattr(out, "trace") else {}
            tr0 = tr0 if isinstance(tr0, dict) else {}

            content: Dict[str, Any] = {
                "text": (getattr(out, "text", "") or "").strip(),
                "proposed_commands": [],
                "agent_id": getattr(out, "agent_id", "dept_finance") or "dept_finance",
                "read_only": True,
                "trace": tr0,
                "session_id": session_id,
                "notion_ops": {
                    "armed": False,
                    "armed_at": None,
                    "session_id": session_id,
                    "armed_state": st0,
                },
            }

            content = _attach_and_log_audit(
                content,
                session_id=session_id,
                conversation_id=conversation_id,
                agent_id=content.get("agent_id"),
                snapshot=snapshot,
                trace=tr0,
                grounding={},
                debug_on=bool(debug_on),
                exit_path="dept_finance.strict.ok",
            )
            return JSONResponse(content=_attach_session_id(content, session_id))

        if is_explicit_dept_ops:
            from services.department_agents import dept_ops_agent  # noqa: PLC0415

            # Deterministic session_id handling (same as canonical path).
            session_id = _extract_session_id(payload)
            if not (isinstance(session_id, str) and session_id.strip()):
                hdr = (request.headers.get("X-Session-Id") or "").strip()
                if hdr:
                    session_id = hdr
            if not (isinstance(session_id, str) and session_id.strip()):
                session_id = str(uuid.uuid4())
                try:
                    payload.session_id = session_id  # type: ignore[attr-defined]
                except Exception:
                    pass

            conversation_id = _extract_conversation_id(payload) or session_id
            if isinstance(conversation_id, str) and conversation_id.strip():
                try:
                    payload.conversation_id = conversation_id.strip()
                except Exception:
                    pass

            debug_on = bool(debug_req_on or _debug_enabled(payload))

            # Minimal AgentInput for dept_ops_agent (force preferred_agent_id so strict branch activates).
            identity_pack = (
                payload.identity_pack
                if isinstance(getattr(payload, "identity_pack", None), dict)
                else {}
            )
            snapshot = (
                payload.snapshot
                if isinstance(getattr(payload, "snapshot", None), dict)
                else {}
            )
            md0 = (
                payload.metadata
                if isinstance(getattr(payload, "metadata", None), dict)
                else {}
            )

            dept_payload = AgentInput(
                message=msg,
                identity_pack=identity_pack,
                snapshot=snapshot,
                conversation_id=conversation_id,
                history=getattr(payload, "history", None),
                preferred_agent_id="dept_ops",
                metadata=md0,
            )

            try:
                out = await dept_ops_agent(
                    dept_payload, ctx={"conversation_id": conversation_id}
                )
            except Exception as exc:
                # No fallback: strict dept_ops failure is a hard 500.
                return JSONResponse(
                    status_code=500,
                    content=_attach_session_id(
                        _attach_and_log_audit(
                            {
                                "text": str(exc)
                                if str(exc)
                                else "dept_ops_strict_backend_failed",
                                "proposed_commands": [],
                                "agent_id": "dept_ops",
                                "read_only": True,
                                "trace": {
                                    "intent": "error",
                                    "exit_reason": "error.dept_ops_strict_backend_failed",
                                    "error_type": exc.__class__.__name__,
                                    "error": str(exc),
                                },
                                "session_id": session_id,
                            },
                            session_id=session_id,
                            conversation_id=conversation_id,
                            agent_id="dept_ops",
                            snapshot=snapshot,
                            trace={
                                "intent": "error",
                                "exit_reason": "error.dept_ops_strict_backend_failed",
                            },
                            grounding={},
                            debug_on=bool(debug_on),
                            exit_path="dept_ops.strict.error",
                        ),
                        session_id,
                    ),
                )

            # Keep /api/chat response shape stable.
            kb = await _knowledge_bundle(request=request)
            ks0 = kb.get("knowledge_snapshot") if isinstance(kb, dict) else {}
            ks0 = ks0 if isinstance(ks0, dict) else {}
            snapshot_meta = kb.get("snapshot_meta") if isinstance(kb, dict) else {}
            snapshot_meta = snapshot_meta if isinstance(snapshot_meta, dict) else {}

            st0 = (
                await _get_state(session_id)
                if session_id
                else {"armed": False, "armed_at": None}
            )

            tr0 = out.trace if hasattr(out, "trace") else {}
            tr0 = tr0 if isinstance(tr0, dict) else {}

            content: Dict[str, Any] = {
                "text": (getattr(out, "text", "") or "").strip(),
                "proposed_commands": [],
                "agent_id": getattr(out, "agent_id", "dept_ops") or "dept_ops",
                "read_only": True,
                "trace": tr0,
                "session_id": session_id,
                "notion_ops": {
                    "armed": bool(st0.get("armed") is True),
                    "armed_at": st0.get("armed_at"),
                    "session_id": session_id,
                    "armed_state": st0,
                },
                "knowledge_snapshot": ks0,
                "snapshot_meta": snapshot_meta,
            }

            content = _attach_and_log_audit(
                content,
                session_id=session_id,
                conversation_id=conversation_id,
                agent_id=content.get("agent_id"),
                snapshot=snapshot,
                trace=tr0,
                grounding={},
                debug_on=bool(debug_on),
                exit_path="dept_ops.strict.ok",
            )
            return JSONResponse(content=_attach_session_id(content, session_id))

        memory_provider = "readonly_memory_service"
        memory_error: Optional[str] = None
        mem_snapshot: Dict[str, Any] = {}
        try:
            mem_ro = get_memory_read_only_service()
            mem_snapshot = mem_ro.export_public_snapshot() if mem_ro else {}
            if not isinstance(mem_snapshot, dict):
                mem_snapshot = {}
        except Exception as exc:
            mem_snapshot = {}
            memory_error = str(exc) if str(exc) else exc.__class__.__name__

        memory_items_count = 0
        try:
            memory_items_count = int(mem_snapshot.get("memory_items_count") or 0)
        except Exception:
            memory_items_count = 0

        prompt = _extract_prompt(payload)

        # Deterministic session key for proposal persistence/replay.
        # Do NOT rely on cookies (PowerShell WebSession has no Set-Cookie here).
        session_id = _extract_session_id(payload)
        if not (isinstance(session_id, str) and session_id.strip()):
            hdr = (request.headers.get("X-Session-Id") or "").strip()
            if hdr:
                session_id = hdr

        if not (isinstance(session_id, str) and session_id.strip()):
            session_id = str(uuid.uuid4())
            try:
                payload.session_id = session_id  # type: ignore[attr-defined]
            except Exception:
                pass

        # Keep conversation_id for downstream multi-turn summaries;
        # proposal persistence/replay uses session_id as the key.
        conversation_id = _extract_conversation_id(payload) or session_id
        proposal_key = session_id

        debug_on = bool(debug_req_on or _debug_enabled(payload))
        # Responses+CEO multi-turn can require a stable id when explicitly enabled.
        if (
            _responses_mode_enabled()
            and _require_conversation_id()
            and not (isinstance(conversation_id, str) and conversation_id.strip())
        ):
            return JSONResponse(
                status_code=400,
                content=_attach_session_id(
                    _attach_and_log_audit(
                        {
                            "text": "Missing conversation id. Provide 'session_id' (recommended) or 'conversation_id' for CEO Responses mode.",
                            "proposed_commands": [],
                            "agent_id": "ceo_advisor",
                            "read_only": True,
                            "error": {
                                "code": "error.missing_conversation_id",
                                "message": "Provide session_id or conversation_id.",
                            },
                        },
                        session_id=session_id,
                        conversation_id=conversation_id,
                        agent_id="ceo_advisor",
                        snapshot=getattr(payload, "snapshot", None),
                        trace={
                            "intent": "error",
                            "exit_reason": "error.missing_conversation_id",
                        },
                        grounding={},
                        debug_on=bool(debug_on),
                        exit_path="ceo_chat.error.missing_conversation_id",
                    ),
                    session_id,
                ),
            )

        # Ensure agent_input has conversation_id populated for downstream.
        if isinstance(conversation_id, str) and conversation_id.strip():
            try:
                payload.conversation_id = conversation_id.strip()
            except Exception:
                pass

        # ------------------------------------------------------------
        # CANON RESTORE: pending proposal replay / cancel / intent switch
        # ------------------------------------------------------------
        pending_declined = False
        pending = _load_pending_proposal(proposal_key)
        if pending:
            cls = _classify_pending_response(prompt)

            if cls == "YES":
                _pending_prompt_reset(conversation_id=proposal_key)
                st0 = (
                    await _get_state(session_id)
                    if session_id
                    else {"armed": False, "armed_at": None}
                )
                content = {
                    "text": "Uredu — evo posljednjeg prijedloga ponovo. Pregledaj i odobri izvršenje.",
                    "proposed_commands": pending,
                    "agent_id": "ceo_advisor",
                    "read_only": True,
                    "notion_ops": {
                        "armed": bool(st0.get("armed") is True),
                        "armed_at": st0.get("armed_at"),
                        "session_id": session_id,
                        "armed_state": st0,
                    },
                    "trace": {
                        "intent": "approve_last_proposal_replay",
                        "canon": "api_chat_pending_proposal_replay",
                    },
                }

                if debug_on:
                    kb0 = await _knowledge_bundle(request=request)
                    content.update(kb0)

                content = _attach_and_log_audit(
                    content,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    agent_id=content.get("agent_id"),
                    snapshot=getattr(payload, "snapshot", None),
                    trace=content.get("trace"),
                    grounding={},
                    debug_on=bool(debug_on),
                    exit_path="ceo_chat.pending_proposal.replay",
                )
                return JSONResponse(content=_attach_session_id(content, session_id))

            if cls in {"NO", "NEW_REQUEST"}:
                pending_declined = cls == "NO"
                _persist_pending_proposal(proposal_key, [])
                _pending_prompt_reset(conversation_id=proposal_key)
            else:
                # UNKNOWN: ask once, then auto-cancel on the next unknown.
                cnt = _pending_prompt_count(conversation_id=proposal_key)
                if cnt < 1:
                    _pending_prompt_bump(conversation_id=proposal_key)
                    st0 = (
                        await _get_state(session_id)
                        if session_id
                        else {"armed": False, "armed_at": None}
                    )
                    content = {
                        "text": (
                            "Imam prijedlog na čekanju. Odgovori 'da' da ga ponovim, ili 'ne' da ga otkažem. "
                            "Ako imaš novi zahtjev, napiši ga (npr. 'umjesto toga…')."
                        ),
                        "proposed_commands": pending,
                        "agent_id": "ceo_advisor",
                        "read_only": True,
                        "notion_ops": {
                            "armed": bool(st0.get("armed") is True),
                            "armed_at": st0.get("armed_at"),
                            "session_id": session_id,
                            "armed_state": st0,
                        },
                        "trace": {
                            "intent": "pending_proposal_confirm_needed",
                            "canon": "api_chat_pending_proposal_confirm_needed",
                        },
                    }
                    if debug_on:
                        kb0 = await _knowledge_bundle(request=request)
                        content.update(kb0)
                    content = _attach_and_log_audit(
                        content,
                        session_id=session_id,
                        conversation_id=conversation_id,
                        agent_id=content.get("agent_id"),
                        snapshot=getattr(payload, "snapshot", None),
                        trace=content.get("trace"),
                        grounding={},
                        debug_on=bool(debug_on),
                        exit_path="ceo_chat.pending_proposal.confirm_needed",
                    )
                    return JSONResponse(content=_attach_session_id(content, session_id))

                # Second unknown: auto-cancel and continue normal routing.
                _persist_pending_proposal(proposal_key, [])
                _pending_prompt_reset(conversation_id=proposal_key)

        conv_summary = None
        if isinstance(conversation_id, str) and conversation_id.strip():
            s = ConversationStateStore.get_summary(
                conversation_id=conversation_id.strip()
            )
            conv_summary = s.summary_text
        notion_calls_for_trace: Optional[int] = None
        debug_on = bool(debug_on)

        def _is_test_mode() -> bool:
            return (os.getenv("TESTING") or "").strip() == "1" or (
                "PYTEST_CURRENT_TEST" in os.environ
            )

        def _snapshot_meta_from_ks(ks: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "knowledge_status": ks.get("status"),
                "knowledge_last_sync": ks.get("last_sync"),
                "knowledge_generated_at": ks.get("generated_at"),
                "knowledge_ready": bool(ks.get("ready"))
                if isinstance(ks.get("ready"), bool)
                else bool(ks.get("ready")),
                "knowledge_expired": bool(ks.get("expired"))
                if isinstance(ks.get("expired"), bool)
                else bool(ks.get("expired")),
                "knowledge_ttl_seconds": ks.get("ttl_seconds"),
                "knowledge_age_seconds": ks.get("age_seconds"),
                "schema_version": ks.get("schema_version"),
            }

        kb = await _knowledge_bundle(request=request)
        ks_for_gp = kb.get("knowledge_snapshot") if isinstance(kb, dict) else {}
        if not isinstance(ks_for_gp, dict):
            ks_for_gp = {}

        # Preserve server SSOT knowledge snapshot for the response contract.
        ks_ssot = ks_for_gp

        targeted_reads_info: Dict[str, Any] = {
            "attempted": False,
            "cache_hit": False,
            "source": None,
            "db_keys_csv": None,
            "ttl_seconds": None,
            "min_last_sync": None,
        }

        # ------------------------------------------------------------
        # READ SNAPSHOT INJECTION (CANON)
        # The UI may send an empty snapshot; for dashboard/show *and* planning/advisory
        # prompts that depend on goals/tasks/projects/KPIs context, we should hydrate
        # from server-side read snapshot (no Notion Ops arming required for reads).
        # ------------------------------------------------------------
        try:
            t0 = (prompt or "").strip().lower()

            # Adaptive grounding policy: read-only Notion targeted reads for operational questions.
            # This is best-effort and cached per session. Tests remain offline.
            try:
                from services.grounding_policy import classify_prompt  # noqa: PLC0415
                from services.session_snapshot_cache import (
                    SESSION_SNAPSHOT_CACHE,
                )  # noqa: PLC0415
                from services.notion_service import (  # noqa: PLC0415
                    get_or_init_notion_service,
                )

                pol = classify_prompt(prompt)
                snap_in0 = getattr(payload, "snapshot", None)
                has_snap0 = isinstance(snap_in0, dict) and bool(snap_in0)

                def _extract_last_sync(snap: Any) -> Optional[str]:
                    if not isinstance(snap, dict):
                        return None

                    # Avoid treating synthetic SSOT last_sync (often == generated_at) as a
                    # freshness marker; it changes per-request and would defeat caching.
                    try:
                        gen = snap.get("generated_at")
                        ls = snap.get("last_sync")
                        trace0 = (
                            snap.get("trace")
                            if isinstance(snap.get("trace"), dict)
                            else {}
                        )
                        if (
                            isinstance(gen, str)
                            and isinstance(ls, str)
                            and gen.strip()
                            and ls.strip()
                            and gen.strip() == ls.strip()
                            and trace0.get("service") == "KnowledgeSnapshotService"
                        ):
                            ls = None
                        v = ls
                    except Exception:
                        v = snap.get("last_sync")

                    if isinstance(v, str) and v.strip():
                        return v.strip()
                    p0 = (
                        snap.get("payload")
                        if isinstance(snap.get("payload"), dict)
                        else None
                    )
                    if isinstance(p0, dict):
                        v2 = p0.get("last_sync")
                        if isinstance(v2, str) and v2.strip():
                            return v2.strip()

                    m0 = (
                        snap.get("meta") if isinstance(snap.get("meta"), dict) else None
                    )
                    if isinstance(m0, dict):
                        v3 = m0.get("synced_at")
                        if isinstance(v3, str) and v3.strip():
                            return v3.strip()
                    return None

                def _needs_notion_refresh(snap: Any) -> bool:
                    if not isinstance(snap, dict):
                        return True
                    status = snap.get("status")
                    if isinstance(status, str) and status.strip() in {"missing_data"}:
                        return True
                    payload0 = (
                        snap.get("payload")
                        if isinstance(snap.get("payload"), dict)
                        else snap
                    )
                    if not isinstance(payload0, dict):
                        return True
                    # If none of the required collections have data, treat as missing.
                    for k in pol.notion_db_keys:
                        v = payload0.get(k)
                        if isinstance(v, list) and len(v) > 0:
                            return False
                    return True

                if (
                    not _is_test_mode()
                    and pol.needs_notion
                    and pol.notion_db_keys
                    and (not has_snap0 or _needs_notion_refresh(snap_in0))
                    and (os.getenv("CEO_NOTION_TARGETED_READS_ENABLED") or "true")
                    .strip()
                    .lower()
                    == "true"
                ):
                    targeted_reads_info["attempted"] = True
                    db_keys_csv = ",".join(pol.notion_db_keys)
                    targeted_reads_info["db_keys_csv"] = db_keys_csv
                    ttl_s_raw = (
                        os.getenv("CEO_CHAT_SNAPSHOT_TTL_SECONDS") or "60"
                    ).strip()
                    try:
                        ttl_s = int(ttl_s_raw)
                    except Exception:
                        ttl_s = 60
                    targeted_reads_info["ttl_seconds"] = int(ttl_s)

                    # Freshness gating should be driven by the caller-provided snapshot
                    # (if any). SSOT snapshot timestamps can legitimately change during
                    # a long-running test run and must not defeat per-session caching.
                    min_last_sync = _extract_last_sync(snap_in0)
                    targeted_reads_info["min_last_sync"] = min_last_sync

                    cached = None
                    if isinstance(session_id, str) and session_id.strip():
                        cached = SESSION_SNAPSHOT_CACHE.get(
                            session_id=session_id.strip(),
                            db_keys_csv=db_keys_csv,
                            min_last_sync=min_last_sync,
                        )
                    if isinstance(cached, dict) and cached:
                        targeted_reads_info["cache_hit"] = True
                        targeted_reads_info["source"] = "cache"
                        payload.snapshot = cached
                        kb = {
                            "knowledge_snapshot": cached,
                            "snapshot_meta": _snapshot_meta_from_ks(cached),
                        }
                        ks_for_gp = cached
                    else:
                        # If SSOT snapshot already satisfies required collections, prefer it
                        # over burning Notion budget on a live targeted read.
                        used_ssot_instead_of_live = False
                        try:
                            ssot_payload = (
                                ks_ssot.get("payload")
                                if isinstance(ks_ssot.get("payload"), dict)
                                else ks_ssot
                            )
                            ssot_ok = True
                            if not isinstance(ssot_payload, dict):
                                ssot_ok = False
                            else:
                                for k in pol.notion_db_keys:
                                    v = ssot_payload.get(k)
                                    if not (isinstance(v, list) and len(v) > 0):
                                        ssot_ok = False
                                        break
                            if ssot_ok and isinstance(ks_ssot, dict) and ks_ssot:
                                targeted_reads_info["source"] = "ssot"
                                payload.snapshot = ks_ssot
                                kb = {
                                    "knowledge_snapshot": ks_ssot,
                                    "snapshot_meta": _snapshot_meta_from_ks(ks_ssot),
                                }
                                ks_for_gp = ks_ssot
                                used_ssot_instead_of_live = True
                        except Exception:
                            pass

                        notion = (
                            None
                            if used_ssot_instead_of_live
                            else get_or_init_notion_service()
                        )
                        if notion is not None:
                            targeted_reads_info["source"] = "live"
                            max_items = {"tasks": 50, "projects": 30, "goals": 30}
                            snap = await notion.build_knowledge_snapshot(
                                db_keys=list(pol.notion_db_keys),
                                max_items_by_db=max_items,
                            )
                            if isinstance(snap, dict) and snap:
                                payload.snapshot = snap
                                kb = {
                                    "knowledge_snapshot": snap,
                                    "snapshot_meta": _snapshot_meta_from_ks(snap),
                                }
                                ks_for_gp = snap
                                try:
                                    m = (
                                        snap.get("meta")
                                        if isinstance(snap.get("meta"), dict)
                                        else {}
                                    )
                                    if isinstance(m.get("notion_calls"), int):
                                        notion_calls_for_trace = int(
                                            m.get("notion_calls")
                                        )
                                except Exception:
                                    notion_calls_for_trace = None
                                if isinstance(session_id, str) and session_id.strip():
                                    SESSION_SNAPSHOT_CACHE.set(
                                        session_id=session_id.strip(),
                                        db_keys_csv=db_keys_csv,
                                        value=snap,
                                        ttl_seconds=ttl_s,
                                    )
            except Exception:
                # Fail-soft: never block chat on Notion targeted reads.
                pass

            wants_target = bool(
                re.search(
                    r"(?i)\b(cilj\w*|goal\w*|task\w*|zadat\w*|zadac\w*|kpi\w*|project\w*|projekat\w*)\b",
                    t0,
                )
            )

            wants_show = bool(
                re.search(
                    r"(?i)\b(pokazi|poka\u017ei|prika\u017ei|prikazi|izlistaj|show|list|pogledaj|procitaj|read|what\s+goals|which\s+goals|which\s+tasks)\b",
                    t0,
                )
                and wants_target
            )

            wants_plan = bool(
                re.search(
                    r"(?i)\b(predlo\u017ei|predlozi|predlag\w*|suggest|recommend|idej\w*)\b",
                    t0,
                )
                and wants_target
                and ("notion" in t0 or "zapis" in t0 or "upis" in t0)
            )

            snap_in = getattr(payload, "snapshot", None)
            has_snap = isinstance(snap_in, dict) and bool(snap_in)

            if wants_show and not has_snap:
                from services.system_read_executor import SystemReadExecutor  # noqa: PLC0415

                sys_snap = SystemReadExecutor().snapshot()
                ceo_snap = sys_snap.get("ceo_notion_snapshot")
                if isinstance(ceo_snap, dict) and ceo_snap:
                    payload.snapshot = ceo_snap
                else:
                    ks = sys_snap.get("knowledge_snapshot")
                    if isinstance(ks, dict) and ks:
                        payload.snapshot = ks

            # Planning: prefer cached knowledge snapshot (do not hit Notion live here).
            if wants_plan and not has_snap and not wants_show:
                try:
                    from services.knowledge_snapshot_service import (  # noqa: PLC0415
                        KnowledgeSnapshotService,
                    )

                    ks2 = KnowledgeSnapshotService.get_snapshot()
                    if isinstance(ks2, dict) and ks2:
                        payload.snapshot = ks2
                except Exception:
                    pass

            # Final fallback: if still no snapshot, inject the SSOT knowledge wrapper.
            # This is read-only, has no IO, and improves grounding/traceability.
            snap_in2 = getattr(payload, "snapshot", None)
            has_snap2 = isinstance(snap_in2, dict) and bool(snap_in2)
            if not has_snap2:
                try:
                    from services.knowledge_snapshot_service import (  # noqa: PLC0415
                        KnowledgeSnapshotService,
                    )

                    ks3 = KnowledgeSnapshotService.get_snapshot()
                    if isinstance(ks3, dict) and ks3:
                        payload.snapshot = ks3
                except Exception:
                    pass
        except Exception:
            # Fail-soft: never break /api/chat because snapshot hydration failed.
            pass

        # ------------------------------------------------------------
        # Snapshot normalization + propagation into agent/grounding
        # - keep response knowledge_snapshot as server SSOT (schema_version v1)
        # - but ensure the agent + grounding_pack get an SSOT-shaped snapshot
        #   with payload lists never null (PowerShell count bug).
        # ------------------------------------------------------------
        try:
            snap_in3 = getattr(payload, "snapshot", None)

            # Some upstream producers wrap the SSOT snapshot under `knowledge_snapshot`.
            if isinstance(snap_in3, dict) and isinstance(
                snap_in3.get("knowledge_snapshot"), dict
            ):
                snap_in3 = snap_in3.get("knowledge_snapshot")

            # If client provided a non-SSOT stub (e.g. {"now": ...}), fall back to server SSOT.
            is_ssot_like = False
            if isinstance(snap_in3, dict):
                if isinstance(snap_in3.get("schema_version"), str) and snap_in3.get(
                    "schema_version"
                ):
                    is_ssot_like = True
                elif isinstance(snap_in3.get("payload"), dict):
                    is_ssot_like = True
                elif isinstance(snap_in3.get("dashboard"), dict):
                    is_ssot_like = True
                elif any(k in snap_in3 for k in ("goals", "tasks", "projects")):
                    is_ssot_like = True

            snap_src = (
                snap_in3 if (is_ssot_like and isinstance(snap_in3, dict)) else ks_ssot
            )
            snap_norm = _normalize_snapshot_wrapper(snap_src)

            payload.snapshot = snap_norm
            ks_for_gp = snap_norm
        except Exception:
            # Fail-soft: do not break chat on snapshot normalization.
            ks_for_gp = ks_ssot

        # PHASE 6: Notion Ops ARMED Gate (activation/deactivation)
        if session_id and _is_activate(prompt):
            st = await _set_armed(session_id, True, prompt=prompt)
            tr = {
                "phase6_notion_ops_gate": {"event": "armed", "session_id": session_id}
            }
            grounding = _grounding_bundle(
                prompt=prompt,
                knowledge_snapshot=ks_for_gp,
                memory_snapshot=mem_snapshot,
                legacy_trace=tr,
                agent_id=None,
            )
            content: Dict[str, Any] = {
                "text": "NOTION OPS: ARMED",
                "proposed_commands": [],
                "agent_id": None,
                "read_only": True,
                "notion_ops": {
                    "armed": True,
                    "armed_at": st.get("armed_at"),
                    "session_id": session_id,
                    "armed_state": st,
                },
            }
            if debug_on:
                content["trace"] = tr
                content.update(kb)
                content.update(grounding)
            content = _attach_and_log_audit(
                content,
                session_id=session_id,
                conversation_id=conversation_id,
                agent_id=content.get("agent_id"),
                snapshot=ks_for_gp,
                trace=tr,
                grounding=grounding,
                debug_on=bool(debug_on),
                exit_path="ceo_chat.notion_ops.armed",
                targeted_reads=targeted_reads_info,
            )
            return JSONResponse(content=_attach_session_id(content, session_id))

        if session_id and _is_deactivate(prompt):
            st = await _set_armed(session_id, False, prompt=prompt)
            tr = {
                "phase6_notion_ops_gate": {
                    "event": "disarmed",
                    "session_id": session_id,
                }
            }
            grounding = _grounding_bundle(
                prompt=prompt,
                knowledge_snapshot=ks_for_gp,
                memory_snapshot=mem_snapshot,
                legacy_trace=tr,
                agent_id=None,
            )
            content: Dict[str, Any] = {
                "text": "NOTION OPS: DISARMED",
                "proposed_commands": [],
                "agent_id": None,
                "read_only": True,
                "notion_ops": {
                    "armed": False,
                    "armed_at": None,
                    "session_id": session_id,
                    "armed_state": st,
                },
            }
            if debug_on:
                content["trace"] = tr
                content.update(kb)
                content.update(grounding)
            content = _attach_and_log_audit(
                content,
                session_id=session_id,
                conversation_id=conversation_id,
                agent_id=content.get("agent_id"),
                snapshot=ks_for_gp,
                trace=tr,
                grounding=grounding,
                debug_on=bool(debug_on),
                exit_path="ceo_chat.notion_ops.disarmed",
                targeted_reads=targeted_reads_info,
            )
            return JSONResponse(content=_attach_session_id(content, session_id))

        # Determine armed state (default false if no session_id)
        st = (
            await _get_state(session_id)
            if session_id
            else {"armed": False, "armed_at": None}
        )
        armed = bool(st.get("armed") is True)

        # ------------------------------------------------------------
        # CEO-NATIVE UX: create_task for active goal context (2-turn)
        # - If user says "Dodaj zadatak za ovaj cilj" and we have last_referenced_goal_id,
        #   ask only for the task title (do NOT ask for goal).
        # - On the next user message, treat it as the title and propose create_task
        #   with goal_id threaded into the proposal wrapper params.
        # ------------------------------------------------------------
        def _load_conv_meta(cid: Optional[str]) -> Dict[str, Any]:
            if not (isinstance(cid, str) and cid.strip()):
                return {}
            try:
                m0 = ConversationStateStore.get_meta(conversation_id=cid.strip())
                return dict(m0) if isinstance(m0, dict) else {}
            except Exception:
                return {}

        def _update_conv_meta(cid: Optional[str], updates: Dict[str, Any]) -> None:
            if not (isinstance(cid, str) and cid.strip()):
                return
            try:
                ConversationStateStore.update_meta(
                    conversation_id=cid.strip(),
                    updates=updates if isinstance(updates, dict) else {},
                )
            except Exception:
                return

        def _extract_inline_task_title(user_text: str) -> str:
            s = (user_text or "").strip()
            if not s:
                return ""

            # Prefer quoted title.
            m_q = re.search(r"\"([^\"\n\r]+)\"|\'([^\'\n\r]+)\'", s)
            if m_q:
                cand = (m_q.group(1) or m_q.group(2) or "").strip()
                return cand.strip(" \t\r\n\"'.,;:!?")

            # Colon/dash form: "Dodaj zadatak: XYZ" / "Kreiraj task - XYZ".
            m = re.search(
                r"(?i)\b(?:dodaj|kreiraj|napravi|create)\s+(?:zadatak|task)\b\s*[:\-\u2013\u2014]\s*(.+)$",
                s,
            )
            if m:
                tail = (m.group(1) or "").strip()
                # Cut common follow-up goal refs.
                tail = re.split(
                    r"(?i)\b(?:za\s+ovaj\s+cilj|za\s+taj\s+cilj|za\s+ovaj|za\s+taj|ovaj\s+cilj|taj\s+cilj)\b",
                    tail,
                    maxsplit=1,
                )[0].strip()
                return tail.strip(" \t\r\n\"'.,;:!?")

            return ""

        def _looks_like_for_this_goal(user_text: str) -> bool:
            t = _norm_bhs_ascii(user_text)
            return bool(
                re.search(
                    r"(?i)\b(za\s+ovaj\s+cilj|za\s+taj\s+cilj|ovaj\s+cilj|taj\s+cilj|ovim\s+ciljem|tim\s+ciljem)\b",
                    t,
                )
            )

        conv_meta_for_ux = _load_conv_meta(conversation_id)
        pending_ct = conv_meta_for_ux.get("pending_create_task_for_goal")
        if isinstance(pending_ct, dict):
            exp = pending_ct.get("expires_at")
            try:
                exp_f = float(exp) if exp is not None else 0.0
            except Exception:
                exp_f = 0.0
            if exp_f and exp_f < float(time.time()):
                _update_conv_meta(
                    conversation_id, {"pending_create_task_for_goal": None}
                )
                pending_ct = None

        if isinstance(pending_ct, dict) and (prompt or "").strip():
            # Allow cancel.
            p_norm = _norm_bhs_ascii(prompt).strip()
            if p_norm in {"ne", "otkazi", "otkaži", "cancel", "stop"}:
                _update_conv_meta(
                    conversation_id, {"pending_create_task_for_goal": None}
                )
                txt_out = "Uredu — otkazano."
                try:
                    if isinstance(conversation_id, str) and conversation_id.strip():
                        ConversationStateStore.append_turn(
                            conversation_id=conversation_id.strip(),
                            user_text=prompt or "",
                            assistant_text=txt_out,
                        )
                except Exception:
                    pass
                content = {
                    "text": txt_out,
                    "proposed_commands": [],
                    "agent_id": "ceo_advisor",
                    "read_only": True,
                    "notion_ops": {
                        "armed": bool(armed),
                        "armed_at": st.get("armed_at") if armed else None,
                        "session_id": session_id,
                        "armed_state": st,
                    },
                    "trace": {
                        "intent": "create_task_active_goal_cancel",
                        "canon": "ceo_native_create_task_slot_fill",
                    },
                }
                if debug_on:
                    content.update(kb)
                content = _attach_and_log_audit(
                    content,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    agent_id=content.get("agent_id"),
                    snapshot=getattr(payload, "snapshot", None),
                    trace=content.get("trace"),
                    grounding={},
                    debug_on=bool(debug_on),
                    exit_path="ceo_chat.create_task_active_goal.cancel",
                    targeted_reads=targeted_reads_info,
                )
                return JSONResponse(content=_attach_session_id(content, session_id))

            title = (prompt or "").strip().strip(" \t\r\n\"'.,;:!?")
            if title:
                goal_id0 = pending_ct.get("goal_id")
                goal_id0 = goal_id0.strip() if isinstance(goal_id0, str) else ""
                if goal_id0:
                    try:
                        mdx = getattr(payload, "metadata", None)
                        mdx = dict(mdx) if isinstance(mdx, dict) else {}
                        mdx["goal_id"] = goal_id0
                        payload.metadata = mdx  # type: ignore[assignment]
                    except Exception:
                        pass

                # Synthesize a canonical create_task prompt so unwrap fast-path extracts title reliably.
                try:
                    payload.message = f"Kreiraj task: {title}"  # type: ignore[attr-defined]
                except Exception:
                    pass
                prompt = f"Kreiraj task: {title}"

                _update_conv_meta(
                    conversation_id, {"pending_create_task_for_goal": None}
                )

        # If the current message is a create_task request scoped to "ovaj cilj",
        # and we have an active goal context, either:
        # - extract inline title and proceed, or
        # - ask only for title and persist pending state.
        try:
            from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415

            _ux_intent = NotionKeywordMapper.detect_intent(prompt or "")
        except Exception:
            _ux_intent = None

        if (
            _ux_intent == "create_task"
            and _looks_like_for_this_goal(prompt or "")
            and isinstance(conversation_id, str)
            and conversation_id.strip()
        ):
            active_goal_id = conv_meta_for_ux.get("last_referenced_goal_id")
            active_goal_id = (
                active_goal_id.strip() if isinstance(active_goal_id, str) else ""
            )

            if not active_goal_id:
                txt_out = (
                    'Ne mogu pouzdano odrediti na koji cilj misliš ("ovaj/taj cilj"). '
                    "Pošalji tačan title cilja ili kopiraj cijeli red iz liste (npr. '2) Title | Status | Due')."
                )
                try:
                    ConversationStateStore.append_turn(
                        conversation_id=conversation_id.strip(),
                        user_text=prompt or "",
                        assistant_text=txt_out,
                    )
                except Exception:
                    pass
                content = {
                    "text": txt_out,
                    "proposed_commands": [],
                    "agent_id": "ceo_advisor",
                    "read_only": True,
                    "notion_ops": {
                        "armed": bool(armed),
                        "armed_at": st.get("armed_at") if armed else None,
                        "session_id": session_id,
                        "armed_state": st,
                    },
                    "trace": {
                        "intent": "create_task_active_goal_missing_goal_context",
                        "canon": "ceo_native_create_task_slot_fill",
                    },
                }
                if debug_on:
                    content.update(kb)
                content = _attach_and_log_audit(
                    content,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    agent_id=content.get("agent_id"),
                    snapshot=getattr(payload, "snapshot", None),
                    trace=content.get("trace"),
                    grounding={},
                    debug_on=bool(debug_on),
                    exit_path="ceo_chat.create_task_active_goal.missing_goal_context",
                    targeted_reads=targeted_reads_info,
                )
                return JSONResponse(content=_attach_session_id(content, session_id))

            inline_title = _extract_inline_task_title(prompt or "")
            if not inline_title:
                # Ask ONLY for title.
                _update_conv_meta(
                    conversation_id,
                    {
                        "pending_create_task_for_goal": {
                            "goal_id": active_goal_id,
                            "created_at": float(time.time()),
                            "expires_at": float(time.time()) + 10 * 60.0,
                        }
                    },
                )
                txt_out = "Kako se zove zadatak? (pošalji samo naslov)"
                try:
                    ConversationStateStore.append_turn(
                        conversation_id=conversation_id.strip(),
                        user_text=prompt or "",
                        assistant_text=txt_out,
                    )
                except Exception:
                    pass
                content = {
                    "text": txt_out,
                    "proposed_commands": [],
                    "agent_id": "ceo_advisor",
                    "read_only": True,
                    "notion_ops": {
                        "armed": bool(armed),
                        "armed_at": st.get("armed_at") if armed else None,
                        "session_id": session_id,
                        "armed_state": st,
                    },
                    "trace": {
                        "intent": "create_task_active_goal_ask_title",
                        "canon": "ceo_native_create_task_slot_fill",
                    },
                }
                if debug_on:
                    content.update(kb)
                content = _attach_and_log_audit(
                    content,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    agent_id=content.get("agent_id"),
                    snapshot=getattr(payload, "snapshot", None),
                    trace=content.get("trace"),
                    grounding={},
                    debug_on=bool(debug_on),
                    exit_path="ceo_chat.create_task_active_goal.ask_title",
                    targeted_reads=targeted_reads_info,
                )
                return JSONResponse(content=_attach_session_id(content, session_id))

            # Inline title provided; normalize prompt and thread goal_id into metadata.
            try:
                mdx = getattr(payload, "metadata", None)
                mdx = dict(mdx) if isinstance(mdx, dict) else {}
                mdx["goal_id"] = active_goal_id
                payload.metadata = mdx  # type: ignore[assignment]
            except Exception:
                pass
            try:
                payload.message = f"Kreiraj task: {inline_title}"  # type: ignore[attr-defined]
            except Exception:
                pass
            prompt = f"Kreiraj task: {inline_title}"

        # ------------------------------------------------------------
        # CANON: write intent -> always route to notion_ops (proposal-only)
        # - ARMED must NOT block proposal generation; it only gates execution.
        # - CEO advisor remains advisory/read-only and must not swallow write intents.
        # ------------------------------------------------------------
        try:
            from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415

            detected_intent = NotionKeywordMapper.detect_intent(prompt or "")
        except Exception:
            detected_intent = None

        write_intent_kw = detected_intent in {
            "create_goal",
            "create_task",
            "create_project",
            "batch_request",
        }
        write_intent = bool(write_intent_kw or _looks_like_write_intent(prompt))

        if write_intent:
            try:
                from services.notion_ops_agent import notion_ops_agent  # noqa: PLC0415

                # Ensure the agent sees the correct session_id.
                try:
                    payload.session_id = session_id  # type: ignore[attr-defined]
                except Exception:
                    pass

                # Force proposal-mode semantics for notion_ops in /api/chat.
                mdw = getattr(payload, "metadata", None)
                mdw = dict(mdw) if isinstance(mdw, dict) else {}
                mdw.setdefault("session_id", session_id)
                mdw.setdefault("initiator", "ceo_chat")
                # /api/chat is canonical read-only (proposal-only). Execution happens via /api/execute.
                mdw["read_only"] = True
                payload.metadata = mdw  # type: ignore[assignment]

                # Hint the router/agent selection for downstream traces.
                try:
                    payload.preferred_agent_id = "notion_ops"  # type: ignore[attr-defined]
                except Exception:
                    pass

                out = await notion_ops_agent(payload, ctx={"memory": mem_snapshot})

                pcs = getattr(out, "proposed_commands", None)
                normalized = _normalize_proposed_commands(pcs)

                actionable = [pc for pc in normalized if _is_actionable(pc)]
                if actionable:
                    for pc in actionable:
                        _finalize_actionable(pc)

                pcs_out: List[Dict[str, Any]] = []
                for pc in actionable or normalized:
                    d = (
                        pc.model_dump(by_alias=False)
                        if hasattr(pc, "model_dump")
                        else pc.dict(by_alias=False)
                    )
                    if isinstance(d, dict):
                        pcs_out.append(_ensure_payload_summary_contract(d))

                # Hard guarantee: write intent must always produce an approval proposal.
                if not pcs_out:
                    fallback = _build_approval_wrapper(
                        prompt,
                        reason="Approval required (write intent; routed to notion_ops).",
                    )
                    pcs_out = [
                        _ensure_payload_summary_contract(
                            _pc_to_dict(fallback, prompt=prompt)
                        )
                    ]

                _persist_pending_proposal(
                    proposal_key, [] if pending_declined else pcs_out
                )

                tr0 = getattr(out, "trace", None)
                tr0 = tr0 if isinstance(tr0, dict) else {}
                tr0.setdefault("phase6_notion_ops_gate", {})
                tr0["phase6_notion_ops_gate"] = {
                    "armed": bool(armed),
                    "session_id_present": bool(session_id),
                    "canon": "write_intent_routes_to_notion_ops",
                    "detected_intent": detected_intent,
                }

                content: Dict[str, Any] = {
                    "text": getattr(out, "text", "") or "",
                    "proposed_commands": pcs_out,
                    "agent_id": getattr(out, "agent_id", None) or "notion_ops",
                    "read_only": True,
                    "notion_ops": {
                        "armed": bool(armed),
                        "armed_at": st.get("armed_at") if armed else None,
                        "session_id": session_id,
                        "armed_state": st,
                    },
                }

                grounding_nops = _grounding_bundle(
                    prompt=prompt,
                    knowledge_snapshot=ks_for_gp,
                    memory_snapshot=mem_snapshot,
                    legacy_trace=tr0,
                    agent_id=getattr(out, "agent_id", None),
                )

                if debug_on:
                    tr0["memory_provider"] = memory_provider
                    tr0["memory_items_count"] = memory_items_count
                    tr0["memory_error"] = memory_error
                    content["trace"] = tr0
                    content.update(kb)
                    content.update(grounding_nops)
                else:
                    minimal_trace = _minimal_trace_intent(tr0)
                    if minimal_trace:
                        content["trace"] = minimal_trace

                content = await _attach_preview_if_requested(
                    content,
                    prompt=prompt,
                    request=request,
                    payload=payload,
                    session_id=session_id,
                )

                content = _attach_and_log_audit(
                    content,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    agent_id=content.get("agent_id"),
                    snapshot=getattr(payload, "snapshot", None),
                    trace=tr0,
                    grounding=grounding_nops,
                    debug_on=bool(debug_on),
                    exit_path="ceo_chat.write_intent.notion_ops",
                    targeted_reads=targeted_reads_info,
                )

                return JSONResponse(content=_attach_session_id(content, session_id))
            except Exception:
                # Fail-soft: fall back to existing advisor routing.
                pass

        # Phase 1: Deterministic show/list goals+tasks path (no LLM).
        # If snapshot is ready and has goals or tasks, return summary directly.
        # Phase 1: Deterministic show/list goals+tasks path (no LLM).
        # If snapshot is ready and has goals or tasks, return summary directly.
        # Exception: bypass for explicit “show all tasks” / “upcoming tasks” so the
        # SSOT task query engine can render full/upcoming modes.
        if _is_show_goals_tasks_intent(prompt):
            try:

                def _norm_bhs_ascii(text: str) -> str:
                    t = (text or "").strip().lower()
                    return (
                        t.replace("č", "c")
                        .replace("ć", "c")
                        .replace("š", "s")
                        .replace("đ", "dj")
                        .replace("ž", "z")
                    )

                t0 = _norm_bhs_ascii(prompt)
                has_task = bool(
                    re.search(r"(?i)\b(task|taskovi|zadat|zadaci|zadatke)\b", t0)
                )
                wants_full = bool(
                    re.search(
                        r"(?i)\b(pokazi\s+sve|prikazi\s+sve|izlistaj\s+sve|kompletno|all)\b",
                        t0,
                    )
                )
                wants_upcoming = bool(
                    re.search(
                        r"(?i)\b(sl(j|j)e(de|d)e(c|ce)|naredn|upcoming)\b",
                        t0,
                    )
                )

                bypass_for_task_mode = bool(has_task and (wants_full or wants_upcoming))

                if not bypass_for_task_mode:
                    _snap_det = ks_for_gp if isinstance(ks_for_gp, dict) else {}
                    if bool(_snap_det.get("ready") is True):
                        _pl_det = (
                            _snap_det.get("payload")
                            if isinstance(_snap_det.get("payload"), dict)
                            else _snap_det
                        )
                        _pl_det = _pl_det if isinstance(_pl_det, dict) else {}
                        _goals_det = (
                            _pl_det.get("goals")
                            if isinstance(_pl_det.get("goals"), list)
                            else []
                        )
                        _tasks_det = (
                            _pl_det.get("tasks")
                            if isinstance(_pl_det.get("tasks"), list)
                            else []
                        )
                        if (
                            isinstance(_goals_det, list)
                            and isinstance(_tasks_det, list)
                            and (_goals_det or _tasks_det)
                        ):
                            _det_text = _render_snapshot_summary(_goals_det, _tasks_det)
                        _det_tr = {
                            "intent": "show_goals_tasks",
                            "exit_path": "deterministic_ssot",
                        }
                        _det_grounding = _grounding_bundle(
                            prompt=prompt,
                            knowledge_snapshot=ks_for_gp,
                            memory_snapshot=mem_snapshot,
                            legacy_trace=_det_tr,
                            agent_id="ceo_advisor",
                        )
                        _det_content: Dict[str, Any] = {
                            "text": _det_text,
                            "proposed_commands": [],
                            "agent_id": "ceo_advisor",
                            "read_only": True,
                            "notion_ops": {
                                "armed": False,
                                "armed_at": None,
                                "session_id": session_id,
                                "armed_state": {},
                            },
                        }
                        if debug_on:
                            _det_content["trace"] = _det_tr
                            _det_content.update(kb)
                            _det_content.update(_det_grounding)
                        _det_content = _attach_and_log_audit(
                            _det_content,
                            session_id=session_id,
                            conversation_id=conversation_id,
                            agent_id="ceo_advisor",
                            snapshot=ks_for_gp,
                            trace=_det_tr,
                            grounding=_det_grounding,
                            debug_on=bool(debug_on),
                            exit_path="ceo_chat.deterministic_ssot.show_goals_tasks",
                            targeted_reads=targeted_reads_info,
                        )

                        # Persist bounded multi-turn context even on deterministic exits.
                        try:
                            if (
                                isinstance(conversation_id, str)
                                and conversation_id.strip()
                            ):
                                ConversationStateStore.append_turn(
                                    conversation_id=conversation_id.strip(),
                                    user_text=prompt or "",
                                    assistant_text=_det_text or "",
                                )
                        except Exception:
                            pass

                        # Persist goal titles for follow-up grounding (no guessing).
                        try:
                            if (
                                isinstance(conversation_id, str)
                                and conversation_id.strip()
                            ):

                                def _pick_goal_title(it: Any) -> str:
                                    if not isinstance(it, dict):
                                        return ""
                                    f = (
                                        it.get("fields")
                                        if isinstance(it.get("fields"), dict)
                                        else {}
                                    )
                                    for k in ("title", "name"):
                                        v = it.get(k)
                                        if isinstance(v, str) and v.strip():
                                            return v.strip()
                                    for k in ("title", "name"):
                                        v = f.get(k)
                                        if isinstance(v, str) and v.strip():
                                            return v.strip()
                                    return ""

                                goal_titles = [
                                    _pick_goal_title(g)
                                    for g in (_goals_det or [])
                                    if isinstance(g, dict)
                                ]
                                goal_titles = [
                                    t
                                    for t in goal_titles
                                    if isinstance(t, str) and t.strip()
                                ]
                                updates: Dict[str, Any] = {
                                    "last_shown_goal_titles": goal_titles[:10],
                                    "last_shown_goal_titles_at": float(time.time()),
                                }
                                if len(goal_titles) == 1:
                                    updates.update(
                                        {
                                            "last_referenced_goal_title": goal_titles[
                                                0
                                            ],
                                            "last_referenced_goal_source": "auto_singleton_show_list",
                                            "last_referenced_goal_at": float(
                                                time.time()
                                            ),
                                        }
                                    )

                                    # Canonical: if the singleton goal has a stable ID, persist it.
                                    try:
                                        g0 = (
                                            (
                                                _goals_det[0]
                                                if isinstance(_goals_det, list)
                                                else None
                                            )
                                            if len(_goals_det or []) == 1
                                            else None
                                        )
                                        if isinstance(g0, dict):
                                            gid = None
                                            for k in ("id", "notion_id", "notionId"):
                                                v = g0.get(k)
                                                if isinstance(v, str) and v.strip():
                                                    gid = v.strip()
                                                    break
                                            if isinstance(gid, str) and gid.strip():
                                                updates["last_referenced_goal_id"] = (
                                                    gid.strip()
                                                )
                                    except Exception:
                                        pass
                                ConversationStateStore.update_meta(
                                    conversation_id=conversation_id.strip(),
                                    updates=updates,
                                )
                        except Exception:
                            pass

                        return JSONResponse(
                            content=_attach_session_id(_det_content, session_id)
                        )
            except Exception:
                pass

        # Phase 0x: Deterministic multi-intent handler (no LLM).
        # Covers compound questions that ask, in one message:
        # - what is the top goal
        # - who owns it
        # - which tasks are linked to it
        # Must return ONE answer in a fixed format and must NOT ask follow-ups.
        try:
            _snap_mi = ks_for_gp if isinstance(ks_for_gp, dict) else {}
            if bool(_snap_mi.get("ready") is True):
                t0_mi = _norm_bhs_ascii(prompt)

                wants_top = bool(_is_top_goal_intent(prompt))
                wants_owner = bool(
                    re.search(
                        r"(?i)\b(ko|who)\b.*\b(odgovor|zaduzen|zaduzen|owner|vlasnik|radi|assigned)\w*\b",
                        t0_mi,
                    )
                )
                wants_tasks = bool(
                    re.search(r"(?i)\b(task|taskovi|zadat|zadac)\w*\b", t0_mi)
                )
                is_compound = bool(wants_top and wants_owner and wants_tasks)

                if is_compound:
                    view = _compute_ceo_view(_snap_mi)
                    top3 = view.get("goals_top3") if isinstance(view, dict) else None
                    top3 = top3 if isinstance(top3, list) else []

                    goal_title = ""
                    goal_id = ""
                    if top3 and isinstance(top3[0], dict):
                        g0 = top3[0]
                        goal_title = (g0.get("title") or "").strip()
                        goal_id = (g0.get("id") or "").strip()

                    if goal_title:
                        goals = _snapshot_goals_list(_snap_mi)
                        tasks = _snapshot_tasks_list(_snap_mi)

                        chosen_goal: Optional[Dict[str, Any]] = None
                        if isinstance(goal_id, str) and goal_id.strip():
                            for g in goals:
                                if not isinstance(g, dict):
                                    continue
                                if (g.get("id") or "").strip() == goal_id.strip():
                                    chosen_goal = g
                                    break

                        if chosen_goal is None:
                            goal_norm = _norm_bhs_ascii(goal_title)
                            for g in goals:
                                if not isinstance(g, dict):
                                    continue
                                f = (
                                    g.get("fields")
                                    if isinstance(g.get("fields"), dict)
                                    else {}
                                )
                                title = _pick_str(
                                    g.get("title")
                                    or g.get("name")
                                    or f.get("title")
                                    or f.get("name")
                                )
                                if goal_norm and _norm_bhs_ascii(title) == goal_norm:
                                    chosen_goal = g
                                    break

                        goal_title_out = goal_title
                        goal_ids: List[str] = []
                        if isinstance(chosen_goal, dict):
                            f = (
                                chosen_goal.get("fields")
                                if isinstance(chosen_goal.get("fields"), dict)
                                else {}
                            )
                            goal_title_out = _pick_str(
                                chosen_goal.get("title")
                                or chosen_goal.get("name")
                                or f.get("title")
                                or f.get("name")
                            )
                            for k in ("id", "notion_id", "notionId"):
                                v = chosen_goal.get(k)
                                if isinstance(v, str) and v.strip():
                                    goal_ids.append(v.strip())

                        goal_id_set = set([x for x in goal_ids if x])

                        def _norm_people(xs: List[str]) -> List[str]:
                            seen = set()
                            out: List[str] = []
                            for x in xs:
                                k = (x or "").strip()
                                if not k:
                                    continue
                                kk = k.lower()
                                if kk in seen:
                                    continue
                                seen.add(kk)
                                out.append(k)
                            return out

                        owners: List[str] = []
                        if isinstance(chosen_goal, dict):
                            f = (
                                chosen_goal.get("fields")
                                if isinstance(chosen_goal.get("fields"), dict)
                                else {}
                            )
                            v_owner = (
                                f.get("owner")
                                or f.get("owners")
                                or f.get("assigned_to")
                                or f.get("assigned")
                            )
                            if isinstance(v_owner, str) and v_owner.strip():
                                owners = [v_owner.strip()]
                            elif isinstance(v_owner, list):
                                owners = [
                                    x.strip()
                                    for x in v_owner
                                    if isinstance(x, str) and x.strip()
                                ]

                            # Best-effort support for properties multi_select shape.
                            if not owners and isinstance(
                                chosen_goal.get("properties"), dict
                            ):
                                props = chosen_goal.get("properties")
                                for key in (
                                    "Assigned To",
                                    "Owner",
                                    "Owners",
                                    "owner",
                                    "owners",
                                    "assigned_to",
                                ):
                                    cand = props.get(key)
                                    if not isinstance(cand, dict):
                                        continue
                                    t = cand.get("type")
                                    if isinstance(t, str) and t.strip().lower() in {
                                        "multi_select",
                                        "select",
                                    }:
                                        vv = cand.get("value")
                                        if isinstance(vv, str) and vv.strip():
                                            owners = [vv.strip()]
                                            break
                                        if isinstance(vv, list):
                                            owners = [
                                                x.strip()
                                                for x in vv
                                                if isinstance(x, str) and x.strip()
                                            ]
                                            break

                        owners = _norm_people(owners)
                        owners_out = (
                            ", ".join(owners) if owners else "(nije definisano)"
                        )

                        linked_titles: List[str] = []
                        if goal_id_set:
                            for t in tasks:
                                if not isinstance(t, dict):
                                    continue
                                tf = (
                                    t.get("fields")
                                    if isinstance(t.get("fields"), dict)
                                    else {}
                                )
                                refs = (
                                    t.get("goal_ids")
                                    or t.get("goalIds")
                                    or t.get("goal_id")
                                    or t.get("goal")
                                    or tf.get("goal_ids")
                                    or tf.get("goalIds")
                                    or tf.get("goal_id")
                                    or tf.get("goal")
                                    or []
                                )
                                if isinstance(refs, str) and refs.strip():
                                    refs = [refs.strip()]
                                if not isinstance(refs, list):
                                    refs = []
                                refs_norm = [
                                    r.strip()
                                    for r in refs
                                    if isinstance(r, str) and r.strip()
                                ]
                                if not any(r in goal_id_set for r in refs_norm):
                                    continue

                                nm = _pick_str(
                                    t.get("title")
                                    or t.get("name")
                                    or tf.get("title")
                                    or tf.get("name")
                                )
                                if nm:
                                    linked_titles.append(nm)

                        linked_titles = linked_titles[:30]
                        if linked_titles:
                            tasks_out = "\n".join(f"- {x}" for x in linked_titles)
                        else:
                            tasks_out = "(nema povezanih zadataka)"

                        tasks_sentence = (
                            "Trenutno nema zadataka vezanih za ovaj cilj."
                            if tasks_out == "(nema povezanih zadataka)"
                            else f"Zadaci vezani za ovaj cilj:\n{tasks_out}"
                        )
                        txt_out = (
                            f'Glavni cilj je "{goal_title_out}".\n\n'
                            f"Za njega su odgovorni: {owners_out}.\n\n"
                            f"{tasks_sentence}"
                        ).strip()

                        # Persist bounded multi-turn context even on deterministic exits.
                        try:
                            if (
                                isinstance(conversation_id, str)
                                and conversation_id.strip()
                            ):
                                ConversationStateStore.append_turn(
                                    conversation_id=conversation_id.strip(),
                                    user_text=prompt or "",
                                    assistant_text=txt_out or "",
                                )
                        except Exception:
                            pass

                        # Keep follow-ups consistent with the existing top-goal path.
                        try:
                            if (
                                isinstance(conversation_id, str)
                                and conversation_id.strip()
                                and isinstance(goal_title_out, str)
                                and goal_title_out.strip()
                            ):
                                updates = {
                                    "last_referenced_goal_title": goal_title_out.strip(),
                                    "last_referenced_goal_title_norm": _norm_bhs_ascii(
                                        goal_title_out
                                    ),
                                    "last_referenced_goal_source": "deterministic_multi_intent_top_goal",
                                    "last_referenced_goal_at": float(time.time()),
                                    "last_shown_goal_titles": [goal_title_out.strip()],
                                    "last_shown_goal_titles_at": float(time.time()),
                                }
                                if goal_ids:
                                    updates["last_referenced_goal_id"] = goal_ids[0]
                                ConversationStateStore.update_meta(
                                    conversation_id=conversation_id.strip(),
                                    updates=updates,
                                )
                        except Exception:
                            pass

                        _det_tr_mi = {
                            "intent": "multi_intent_goal_summary",
                            "exit_path": "deterministic_ssot.multi_intent_goal_summary",
                            "goal_title": goal_title_out,
                            "goal_ids": list(goal_id_set)[:3],
                            "linked_tasks_count": int(len(linked_titles)),
                        }
                        _det_grounding_mi = _grounding_bundle(
                            prompt=prompt,
                            knowledge_snapshot=ks_for_gp,
                            memory_snapshot=mem_snapshot,
                            legacy_trace=_det_tr_mi,
                            agent_id="ceo_advisor",
                        )
                        _det_content_mi: Dict[str, Any] = {
                            "text": txt_out,
                            "proposed_commands": [],
                            "agent_id": "ceo_advisor",
                            "read_only": True,
                            "notion_ops": {
                                "armed": False,
                                "armed_at": None,
                                "session_id": session_id,
                                "armed_state": {},
                            },
                        }
                        if debug_on:
                            _det_content_mi["trace"] = _det_tr_mi
                            _det_content_mi.update(kb)
                            _det_content_mi.update(_det_grounding_mi)

                        _det_content_mi = _attach_and_log_audit(
                            _det_content_mi,
                            session_id=session_id,
                            conversation_id=conversation_id,
                            agent_id="ceo_advisor",
                            snapshot=ks_for_gp,
                            trace=_det_tr_mi,
                            grounding=_det_grounding_mi,
                            debug_on=bool(debug_on),
                            exit_path="ceo_chat.deterministic_ssot.multi_intent_goal_summary",
                            targeted_reads=targeted_reads_info,
                        )
                        return JSONResponse(
                            content=_attach_session_id(_det_content_mi, session_id)
                        )
        except Exception:
            pass

        # Phase 1a: Deterministic "Najbitniji cilj" (top goal) path (no LLM).
        # HARD RULES:
        # - strictly snapshot-derived (no guessing)
        # - must persist last_referenced_goal_title so follow-ups work
        if _is_top_goal_intent(prompt):
            try:
                _snap_top = ks_for_gp if isinstance(ks_for_gp, dict) else {}
                if bool(_snap_top.get("ready") is True):
                    view = _compute_ceo_view(_snap_top)
                    top3 = view.get("goals_top3") if isinstance(view, dict) else None
                    top3 = top3 if isinstance(top3, list) else []

                    goal_title = ""
                    status = "-"
                    due = "-"
                    goal_id = ""

                    if top3 and isinstance(top3[0], dict):
                        g0 = top3[0]
                        goal_title = (g0.get("title") or "").strip()
                        status = (g0.get("status") or "-").strip() or "-"
                        due = (g0.get("due") or "-").strip() or "-"
                        goal_id = (g0.get("id") or "").strip()

                    if goal_title:
                        txt_out = (
                            f'Glavni cilj trenutno je "{goal_title}".\n'
                            f"Status: {status} | Rok: {due}"
                        ).strip()
                    else:
                        txt_out = "U snapshotu nema ciljeva, pa ne mogu odrediti najbitniji cilj."

                    # Persist bounded multi-turn context even on deterministic exits.
                    try:
                        if isinstance(conversation_id, str) and conversation_id.strip():
                            ConversationStateStore.append_turn(
                                conversation_id=conversation_id.strip(),
                                user_text=prompt or "",
                                assistant_text=txt_out or "",
                            )
                    except Exception:
                        pass

                    # Persist last referenced goal title for follow-ups.
                    try:
                        if (
                            isinstance(conversation_id, str)
                            and conversation_id.strip()
                            and isinstance(goal_title, str)
                            and goal_title.strip()
                        ):
                            ConversationStateStore.update_meta(
                                conversation_id=conversation_id.strip(),
                                updates={
                                    "last_referenced_goal_title": goal_title.strip(),
                                    "last_referenced_goal_title_norm": _norm_bhs_ascii(
                                        goal_title
                                    ),
                                    "last_referenced_goal_source": "deterministic_top_goal",
                                    "last_referenced_goal_at": float(time.time()),
                                    "last_shown_goal_titles": [goal_title.strip()],
                                    "last_shown_goal_titles_at": float(time.time()),
                                    **(
                                        {"last_referenced_goal_id": goal_id.strip()}
                                        if isinstance(goal_id, str) and goal_id.strip()
                                        else {}
                                    ),
                                },
                            )
                    except Exception:
                        pass

                    _det_tr_top = {
                        "intent": "top_goal",
                        "exit_path": "deterministic_ssot_top_goal",
                        "goal_title": goal_title,
                        "criteria": (
                            view.get("goals_top3_criteria")
                            if isinstance(view, dict)
                            else None
                        ),
                    }
                    _det_grounding_top = _grounding_bundle(
                        prompt=prompt,
                        knowledge_snapshot=ks_for_gp,
                        memory_snapshot=mem_snapshot,
                        legacy_trace=_det_tr_top,
                        agent_id="ceo_advisor",
                    )
                    _det_content_top: Dict[str, Any] = {
                        "text": txt_out,
                        "proposed_commands": [],
                        "agent_id": "ceo_advisor",
                        "read_only": True,
                        "notion_ops": {
                            "armed": False,
                            "armed_at": None,
                            "session_id": session_id,
                            "armed_state": {},
                        },
                    }
                    if debug_on:
                        _det_content_top["trace"] = _det_tr_top
                        _det_content_top.update(kb)
                        _det_content_top.update(_det_grounding_top)

                    _det_content_top = _attach_and_log_audit(
                        _det_content_top,
                        session_id=session_id,
                        conversation_id=conversation_id,
                        agent_id="ceo_advisor",
                        snapshot=ks_for_gp,
                        trace=_det_tr_top,
                        grounding=_det_grounding_top,
                        debug_on=bool(debug_on),
                        exit_path="ceo_chat.deterministic_ssot.top_goal",
                        targeted_reads=targeted_reads_info,
                    )
                    return JSONResponse(
                        content=_attach_session_id(_det_content_top, session_id)
                    )
            except Exception:
                pass

        # Phase 1a.1: Deterministic + HYBRID "Zašto je (ovaj/taj/...) cilj glavni?" path.
        # Requirements:
        # - strictly snapshot-derived signals first (status/due/priority)
        # - optional short, clearly-labeled reasoning when signals are insufficient
        # - must honor canonical active goal context: explicit ref -> last_referenced_goal_id -> fallback
        # - do not break existing top-goal/ownership/tasks output contracts
        try:
            t0_why_main = _norm_bhs_ascii(prompt)
            is_why_main_goal_q = bool(
                re.search(r"(?i)\b(zasto|zašto)\b", t0_why_main)
                and re.search(r"(?i)\b(glavni|najbitniji)\b", t0_why_main)
                and re.search(r"(?i)\b(cilj|goal)\w*\b", t0_why_main)
            )
            if is_why_main_goal_q:
                _snap_why = ks_for_gp if isinstance(ks_for_gp, dict) else {}
                if bool(_snap_why.get("ready") is True):
                    # Load canonical conversation context.
                    last_goal_id = ""
                    last_goal_title = ""
                    try:
                        if isinstance(conversation_id, str) and conversation_id.strip():
                            meta = ConversationStateStore.get_meta(
                                conversation_id=conversation_id.strip()
                            )
                            if isinstance(meta, dict):
                                v_id = meta.get("last_referenced_goal_id")
                                if isinstance(v_id, str) and v_id.strip():
                                    last_goal_id = v_id.strip()
                                v = meta.get("last_referenced_goal_title")
                                if isinstance(v, str) and v.strip():
                                    last_goal_title = v.strip()
                    except Exception:
                        last_goal_id = ""
                        last_goal_title = ""

                    # Optional explicit goal reference in the same message.
                    explicit_goal_ref = ""
                    try:
                        # Prefer "Zašto je cilj <TITLE> glavni" (explicit title).
                        m_title = re.search(
                            r"(?i)\b(?:zasto|zašto)\b\s+je\s+\b(?:cilj|goal)\w*\b\s+(.+?)\s+\b(glavni|najbitniji)\b",
                            prompt or "",
                        )
                        if m_title:
                            raw = (m_title.group(1) or "").strip()
                            raw = raw.strip(" \t\r\n\"'.,;:!?-\u2013\u2014")
                            raw = re.split(r"[\.!?]\s+", raw, maxsplit=1)[0].strip()
                            rn = _norm_bhs_ascii(raw)
                            if rn and not re.search(
                                r"(?i)\b(ovaj|ovom|ovog|ovome|ovo|taj|tom|tog|tome|koji\s+smo\s+spomenuli|koji\s+smo\s+pomenuli|koji\s+smo\s+spominjali|o\s+kojem\s+pricamo|o\s+c(e|)mu\s+pricamo)\b",
                                rn,
                            ):
                                explicit_goal_ref = raw
                        if not explicit_goal_ref:
                            # Generic "cilj: <TITLE>" / "cilj <TITLE>" extraction.
                            m_exp = re.search(
                                r'(?i)\b(?:cilj(?:u|a)?|goal)\w*\b\s*[:\-\u2013\u2014]?\s*["\u201c\u201d\']?([^\n\r\?\"]+)',
                                prompt or "",
                            )
                            if m_exp:
                                raw2 = (m_exp.group(1) or "").strip()
                                raw2 = raw2.strip(" \t\r\n\"'.,;:!?-\u2013\u2014")
                                raw2 = re.split(r"[\.!?]\s+", raw2, maxsplit=1)[
                                    0
                                ].strip()
                                rn2 = _norm_bhs_ascii(raw2)
                                if rn2 and not re.search(
                                    r"(?i)\b(glavni|najbitniji|ovaj|ovom|ovog|ovome|ovo|taj|tom|tog|tome|koji\s+smo\s+spomenuli|koji\s+smo\s+pomenuli|koji\s+smo\s+spominjali|o\s+kojem\s+pricamo|o\s+c(e|)mu\s+pricamo)\b",
                                    rn2,
                                ):
                                    explicit_goal_ref = raw2
                    except Exception:
                        explicit_goal_ref = ""

                    goals = _snapshot_goals_list(_snap_why)
                    chosen_goal: Optional[Dict[str, Any]] = None

                    # Resolution order: explicit ref -> last_referenced_goal_id -> title fallback.
                    if explicit_goal_ref:
                        ref_norm = _norm_bhs_ascii(explicit_goal_ref)
                        if ref_norm:
                            for g in goals:
                                if not isinstance(g, dict):
                                    continue
                                f = (
                                    g.get("fields")
                                    if isinstance(g.get("fields"), dict)
                                    else {}
                                )
                                title = _pick_str(
                                    g.get("title")
                                    or g.get("name")
                                    or f.get("title")
                                    or f.get("name")
                                )
                                if ref_norm == _norm_bhs_ascii(title):
                                    chosen_goal = g
                                    break
                        if chosen_goal is None and ref_norm:
                            for g in goals:
                                if not isinstance(g, dict):
                                    continue
                                f = (
                                    g.get("fields")
                                    if isinstance(g.get("fields"), dict)
                                    else {}
                                )
                                title = _pick_str(
                                    g.get("title")
                                    or g.get("name")
                                    or f.get("title")
                                    or f.get("name")
                                )
                                if ref_norm in _norm_bhs_ascii(title):
                                    chosen_goal = g
                                    break

                    if chosen_goal is None and last_goal_id:
                        for g in goals:
                            if not isinstance(g, dict):
                                continue
                            gid = (g.get("id") or "").strip()
                            if gid and gid == last_goal_id:
                                chosen_goal = g
                                break

                    if chosen_goal is None and last_goal_title:
                        last_goal_norm = _norm_bhs_ascii(last_goal_title)
                        if last_goal_norm:
                            for g in goals:
                                if not isinstance(g, dict):
                                    continue
                                f = (
                                    g.get("fields")
                                    if isinstance(g.get("fields"), dict)
                                    else {}
                                )
                                title = _pick_str(
                                    g.get("title")
                                    or g.get("name")
                                    or f.get("title")
                                    or f.get("name")
                                )
                                if _norm_bhs_ascii(title) == last_goal_norm:
                                    chosen_goal = g
                                    break
                        if chosen_goal is None and last_goal_norm:
                            for g in goals:
                                if not isinstance(g, dict):
                                    continue
                                f = (
                                    g.get("fields")
                                    if isinstance(g.get("fields"), dict)
                                    else {}
                                )
                                title = _pick_str(
                                    g.get("title")
                                    or g.get("name")
                                    or f.get("title")
                                    or f.get("name")
                                )
                                if last_goal_norm in _norm_bhs_ascii(title):
                                    chosen_goal = g
                                    break

                    if chosen_goal is None:
                        # Keep existing fallback behavior if we cannot resolve the goal.
                        pass
                    else:
                        f = (
                            chosen_goal.get("fields")
                            if isinstance(chosen_goal.get("fields"), dict)
                            else {}
                        )
                        goal_title_out = _pick_str(
                            chosen_goal.get("title")
                            or chosen_goal.get("name")
                            or f.get("title")
                            or f.get("name")
                        )
                        goal_id_out = (chosen_goal.get("id") or "").strip()

                        status_out = _pick_str(
                            f.get("status") or chosen_goal.get("status")
                        )

                        due_out = ""
                        due_v = f.get("due") if isinstance(f, dict) else None
                        if isinstance(due_v, dict):
                            due_out = _pick_str(
                                due_v.get("start")
                                or due_v.get("date")
                                or due_v.get("end")
                            )
                        elif isinstance(due_v, str):
                            due_out = due_v.strip()
                        if not due_out:
                            due_out = _pick_str(
                                f.get("rok") or f.get("due_date") or f.get("deadline")
                            )

                        priority_out = ""
                        for k in ("priority", "prioritet", "prio"):
                            if k in f:
                                pv = f.get(k)
                                if isinstance(pv, str) and pv.strip():
                                    priority_out = pv.strip()
                                    break
                                if isinstance(pv, (int, float)):
                                    priority_out = str(pv)
                                    break

                        # Trace helpers (do not affect output logic).
                        signals: List[str] = []
                        if status_out:
                            signals.append("status")
                        if due_out:
                            signals.append("due")
                        if priority_out:
                            signals.append("priority")
                        has_enough_signals = bool(signals)

                        # Natural CEO-style phrasing (no bullets/headers). Use only deterministic fields.
                        if goal_title_out and status_out and due_out:
                            txt_out = (
                                f'Glavni cilj je "{goal_title_out}" jer je trenutno {status_out.lower()} i ima rok {due_out}. '
                                "To znači da zahtijeva prioritet i fokus u ovom trenutku."
                            ).strip()
                        elif goal_title_out and status_out:
                            txt_out = (
                                f'Glavni cilj je "{goal_title_out}" jer je trenutno {status_out.lower()}. '
                                "To znači da zahtijeva prioritet i fokus u ovom trenutku."
                            ).strip()
                        elif goal_title_out and due_out:
                            txt_out = (
                                f'Glavni cilj je "{goal_title_out}" jer ima rok {due_out}. '
                                "To znači da zahtijeva prioritet i fokus u ovom trenutku."
                            ).strip()
                        elif goal_title_out:
                            txt_out = (
                                f'Glavni cilj je "{goal_title_out}". '
                                "U snapshotu nemam dovoljno podataka (status/rok/prioritet) da objasnim zašto je glavni."
                            ).strip()
                        else:
                            txt_out = "U snapshotu nemam dovoljno podataka da objasnim zašto je cilj glavni."

                        # Persist bounded multi-turn context even on deterministic exits.
                        try:
                            if (
                                isinstance(conversation_id, str)
                                and conversation_id.strip()
                            ):
                                ConversationStateStore.append_turn(
                                    conversation_id=conversation_id.strip(),
                                    user_text=prompt or "",
                                    assistant_text=txt_out or "",
                                )
                        except Exception:
                            pass

                        # Refresh active goal context for subsequent follow-ups.
                        try:
                            if (
                                isinstance(conversation_id, str)
                                and conversation_id.strip()
                                and isinstance(goal_title_out, str)
                                and goal_title_out.strip()
                            ):
                                updates = {
                                    "last_referenced_goal_title": goal_title_out.strip(),
                                    "last_referenced_goal_title_norm": _norm_bhs_ascii(
                                        goal_title_out
                                    ),
                                    "last_referenced_goal_source": "deterministic_why_main_goal_hybrid",
                                    "last_referenced_goal_at": float(time.time()),
                                }
                                if isinstance(goal_id_out, str) and goal_id_out.strip():
                                    updates["last_referenced_goal_id"] = (
                                        goal_id_out.strip()
                                    )
                                ConversationStateStore.update_meta(
                                    conversation_id=conversation_id.strip(),
                                    updates=updates,
                                )
                        except Exception:
                            pass

                        _det_tr_why = {
                            "intent": "why_main_goal",
                            "exit_path": "deterministic_ssot.why_main_goal_hybrid",
                            "goal_title": goal_title_out,
                            "goal_id": goal_id_out,
                            "signals_count": int(len(signals)),
                            "mode": "deterministic" if has_enough_signals else "hybrid",
                        }
                        _det_grounding_why = _grounding_bundle(
                            prompt=prompt,
                            knowledge_snapshot=ks_for_gp,
                            memory_snapshot=mem_snapshot,
                            legacy_trace=_det_tr_why,
                            agent_id="ceo_advisor",
                        )
                        _det_content_why: Dict[str, Any] = {
                            "text": txt_out,
                            "proposed_commands": [],
                            "agent_id": "ceo_advisor",
                            "read_only": True,
                            "notion_ops": {
                                "armed": False,
                                "armed_at": None,
                                "session_id": session_id,
                                "armed_state": {},
                            },
                        }
                        if debug_on:
                            _det_content_why["trace"] = _det_tr_why
                            _det_content_why.update(kb)
                            _det_content_why.update(_det_grounding_why)

                        _det_content_why = _attach_and_log_audit(
                            _det_content_why,
                            session_id=session_id,
                            conversation_id=conversation_id,
                            agent_id="ceo_advisor",
                            snapshot=ks_for_gp,
                            trace=_det_tr_why,
                            grounding=_det_grounding_why,
                            debug_on=bool(debug_on),
                            exit_path="ceo_chat.deterministic_ssot.why_main_goal_hybrid",
                            targeted_reads=targeted_reads_info,
                        )
                        return JSONResponse(
                            content=_attach_session_id(_det_content_why, session_id)
                        )
        except Exception:
            pass

        # Phase 1b: Deterministic SSOT task query interception (no LLM).
        # Covers task questions beyond show/list, e.g. "Da li imamo zadatke za danas?".
        # Must be pre-routing: do not call agents when we can answer from SSOT snapshot.
        try:
            from services.ssot_task_query_engine import (  # noqa: PLC0415
                classify_task_query,
                compute_task_stats,
                render_task_query_answer,
                render_tasks_phase_a_answer,
                run_task_query,
            )

            from services.ceo_tasks_phase_a import (  # noqa: PLC0415
                classify_tasks_phase_a,
            )

            _snap_q = ks_for_gp if isinstance(ks_for_gp, dict) else {}
            if bool(_snap_q.get("ready") is True):
                # Goal-scoped task queries must be handled deterministically here
                # (and must NOT be hijacked by global Phase A task stats).
                try:
                    t0_goal_tasks = _norm_bhs_ascii(prompt)
                    has_task_token = bool(
                        re.search(
                            r"(?i)\b(task|taskovi|zadat|zadac)\w*\b", t0_goal_tasks
                        )
                    )
                    has_goal_token = bool(
                        re.search(r"(?i)\b(cilj|goal)\w*\b", t0_goal_tasks)
                    )
                    is_followup_goal = bool(
                        re.search(
                            r"(?i)\b(ovaj|ovom|ovog|ovome|ovo|taj|tom|tog|tome|ovim)\b.*\b(cilj|goal)\w*\b",
                            t0_goal_tasks,
                        )
                    )
                    if not is_followup_goal:
                        is_followup_goal = bool(
                            re.search(
                                r"(?i)\b(o\s+kojem\s+pricamo|o\s+c(e|)mu\s+pricamo)\b",
                                t0_goal_tasks,
                            )
                            or re.search(
                                r"(?i)\b(koji\s+smo\s+spomenuli|koji\s+smo\s+pomenuli|koji\s+smo\s+spominjali)\b",
                                t0_goal_tasks,
                            )
                        )
                    is_goal_scoped_task_query = bool(
                        has_task_token and (has_goal_token or is_followup_goal)
                    )

                    if is_goal_scoped_task_query:
                        # Resolve goal using canonical active goal context.
                        last_goal_id = ""
                        last_goal_title = ""
                        try:
                            if (
                                isinstance(conversation_id, str)
                                and conversation_id.strip()
                            ):
                                meta = ConversationStateStore.get_meta(
                                    conversation_id=conversation_id.strip()
                                )
                                if isinstance(meta, dict):
                                    v_id = meta.get("last_referenced_goal_id")
                                    if isinstance(v_id, str) and v_id.strip():
                                        last_goal_id = v_id.strip()
                                    v = meta.get("last_referenced_goal_title")
                                    if isinstance(v, str) and v.strip():
                                        last_goal_title = v.strip()
                        except Exception:
                            last_goal_id = ""
                            last_goal_title = ""

                        # Optional explicit goal reference in the same message.
                        explicit_goal_ref = ""
                        try:
                            m_exp = re.search(
                                r'(?i)\b(?:cilj(?:u|a)?|goal)\w*\b\s*[:\-\u2013\u2014]?\s*["\u201c\u201d\']?([^\n\r\?\"]+)',
                                prompt or "",
                            )
                            if m_exp:
                                raw = (m_exp.group(1) or "").strip()
                                raw = raw.strip(" \t\r\n\"'.,;:!?-")
                                raw = re.split(r"[\.!?]\s+", raw, maxsplit=1)[0].strip()
                                rn = _norm_bhs_ascii(raw)
                                if rn and not re.search(
                                    r"(?i)\b(ovaj|ovom|ovog|ovome|ovo|taj|tom|tog|tome|koji\s+smo\s+spomenuli|koji\s+smo\s+pomenuli|koji\s+smo\s+spominjali|o\s+kojem\s+pricamo|o\s+c(e|)mu\s+pricamo)\b",
                                    rn,
                                ):
                                    explicit_goal_ref = raw
                        except Exception:
                            explicit_goal_ref = ""

                        goals = _snapshot_goals_list(_snap_q)
                        tasks = _snapshot_tasks_list(_snap_q)

                        chosen_goal: Optional[Dict[str, Any]] = None
                        # Resolution order: explicit ref -> last_referenced_goal_id -> title fallback.
                        if explicit_goal_ref:
                            ref_norm = _norm_bhs_ascii(explicit_goal_ref)
                            for g in goals:
                                if not isinstance(g, dict):
                                    continue
                                f = (
                                    g.get("fields")
                                    if isinstance(g.get("fields"), dict)
                                    else {}
                                )
                                title = _pick_str(
                                    g.get("title")
                                    or g.get("name")
                                    or f.get("title")
                                    or f.get("name")
                                )
                                if ref_norm and ref_norm == _norm_bhs_ascii(title):
                                    chosen_goal = g
                                    break
                            if chosen_goal is None and ref_norm:
                                for g in goals:
                                    if not isinstance(g, dict):
                                        continue
                                    f = (
                                        g.get("fields")
                                        if isinstance(g.get("fields"), dict)
                                        else {}
                                    )
                                    title = _pick_str(
                                        g.get("title")
                                        or g.get("name")
                                        or f.get("title")
                                        or f.get("name")
                                    )
                                    if ref_norm in _norm_bhs_ascii(title):
                                        chosen_goal = g
                                        break

                        if chosen_goal is None and last_goal_id:
                            for g in goals:
                                if not isinstance(g, dict):
                                    continue
                                gid = (g.get("id") or "").strip()
                                if gid and gid == last_goal_id:
                                    chosen_goal = g
                                    break

                        if chosen_goal is None and last_goal_title:
                            last_goal_norm = _norm_bhs_ascii(last_goal_title)
                            if last_goal_norm:
                                for g in goals:
                                    if not isinstance(g, dict):
                                        continue
                                    f = (
                                        g.get("fields")
                                        if isinstance(g.get("fields"), dict)
                                        else {}
                                    )
                                    title = _pick_str(
                                        g.get("title")
                                        or g.get("name")
                                        or f.get("title")
                                        or f.get("name")
                                    )
                                    if _norm_bhs_ascii(title) == last_goal_norm:
                                        chosen_goal = g
                                        break

                                if chosen_goal is None:
                                    for g in goals:
                                        if not isinstance(g, dict):
                                            continue
                                        f = (
                                            g.get("fields")
                                            if isinstance(g.get("fields"), dict)
                                            else {}
                                        )
                                        title = _pick_str(
                                            g.get("title")
                                            or g.get("name")
                                            or f.get("title")
                                            or f.get("name")
                                        )
                                        if (
                                            last_goal_norm
                                            and last_goal_norm in _norm_bhs_ascii(title)
                                        ):
                                            chosen_goal = g
                                            break

                        if chosen_goal is not None:
                            goal_ids: List[str] = []
                            for k in ("id", "notion_id", "notionId"):
                                v = chosen_goal.get(k)
                                if isinstance(v, str) and v.strip():
                                    goal_ids.append(v.strip())
                            goal_id_set = set(goal_ids)

                            linked: List[Dict[str, Any]] = []
                            if goal_id_set:
                                for t in tasks:
                                    tf = (
                                        t.get("fields")
                                        if isinstance(t.get("fields"), dict)
                                        else {}
                                    )
                                    refs = (
                                        t.get("goal_ids")
                                        or t.get("goalIds")
                                        or t.get("goal_id")
                                        or t.get("goal")
                                        or tf.get("goal_ids")
                                        or tf.get("goalIds")
                                        or tf.get("goal_id")
                                        or tf.get("goal")
                                        or []
                                    )
                                    if isinstance(refs, str) and refs.strip():
                                        refs = [refs.strip()]
                                    if not isinstance(refs, list):
                                        refs = []
                                    refs_norm = [
                                        r.strip()
                                        for r in refs
                                        if isinstance(r, str) and r.strip()
                                    ]
                                    if any(r in goal_id_set for r in refs_norm):
                                        linked.append(t)

                            # Compute active tasks count using the same engine logic as Phase A.
                            active_count = 0
                            try:
                                from services.ssot_task_query_engine import (  # noqa: PLC0415
                                    compute_task_stats as _compute_task_stats,
                                )

                                payload0 = (
                                    _snap_q.get("payload")
                                    if isinstance(_snap_q.get("payload"), dict)
                                    else {}
                                )
                                dash0 = (
                                    payload0.get("dashboard")
                                    if isinstance(payload0.get("dashboard"), dict)
                                    else {}
                                )
                                payload2 = dict(payload0)
                                payload2["dashboard"] = dict(dash0)
                                payload2["tasks"] = linked
                                payload2["dashboard"]["tasks"] = []
                                snap2 = {"ready": True, "payload": payload2}
                                st2 = _compute_task_stats(snap2)
                                active_count = int(st2.get("active_count") or 0)
                            except Exception:
                                active_count = 0

                            total_count = len(linked)
                            wants_active = bool(
                                re.search(r"(?i)\b(aktivn)\w*\b", t0_goal_tasks)
                            )
                            wants_list = bool(
                                re.search(
                                    r"(?i)\b(koji|koje|povezan|povezani|navedi|izlistaj|lista|prikazi|pokazi|poka(z|z)i)\b",
                                    t0_goal_tasks,
                                )
                            )

                            goal_title_out = _pick_str(
                                chosen_goal.get("title")
                                or chosen_goal.get("name")
                                or (
                                    chosen_goal.get("fields", {}).get("title")
                                    if isinstance(chosen_goal.get("fields"), dict)
                                    else None
                                )
                                or (
                                    chosen_goal.get("fields", {}).get("name")
                                    if isinstance(chosen_goal.get("fields"), dict)
                                    else None
                                )
                            )

                            if wants_list:
                                titles: List[str] = []
                                for t in linked[:30]:
                                    tf = (
                                        t.get("fields")
                                        if isinstance(t.get("fields"), dict)
                                        else {}
                                    )
                                    nm = _pick_str(
                                        t.get("title")
                                        or t.get("name")
                                        or tf.get("title")
                                        or tf.get("name")
                                    )
                                    if nm:
                                        titles.append(nm)
                                if titles:
                                    txt_out = (
                                        f'Zadaci vezani za cilj "{goal_title_out}":\n'
                                        + "\n".join(f"- {x}" for x in titles)
                                    )
                                else:
                                    txt_out = f'Trenutno nema zadataka vezanih za cilj "{goal_title_out}".'
                            else:
                                # YES/NO style question.
                                if wants_active:
                                    ans = "Da." if active_count > 0 else "Ne."
                                    txt_out = f'{ans} Trenutno imamo {active_count} aktivnih zadataka vezanih za cilj "{goal_title_out}".'
                                else:
                                    ans = "Da." if total_count > 0 else "Ne."
                                    txt_out = f'{ans} Trenutno imamo {total_count} zadataka vezanih za cilj "{goal_title_out}".'

                            _det_tr_goal_tasks = {
                                "intent": "ssot_goal_scoped_tasks",
                                "exit_path": "deterministic_ssot.goal_scoped_tasks",
                                "goal_title": goal_title_out,
                                "goal_ids": goal_ids[:3],
                                "total_count": int(total_count),
                                "active_count": int(active_count),
                            }
                            _det_grounding_goal_tasks = _grounding_bundle(
                                prompt=prompt,
                                knowledge_snapshot=ks_for_gp,
                                memory_snapshot=mem_snapshot,
                                legacy_trace=_det_tr_goal_tasks,
                                agent_id="ceo_advisor",
                            )
                            _det_content_goal_tasks: Dict[str, Any] = {
                                "text": (txt_out or "").strip(),
                                "proposed_commands": [],
                                "agent_id": "ceo_advisor",
                                "read_only": True,
                                "notion_ops": {
                                    "armed": False,
                                    "armed_at": None,
                                    "session_id": session_id,
                                    "armed_state": {},
                                },
                            }
                            if debug_on:
                                _det_content_goal_tasks["trace"] = _det_tr_goal_tasks
                                _det_content_goal_tasks.update(kb)
                                _det_content_goal_tasks.update(
                                    _det_grounding_goal_tasks
                                )

                            _det_content_goal_tasks = _attach_and_log_audit(
                                _det_content_goal_tasks,
                                session_id=session_id,
                                conversation_id=conversation_id,
                                agent_id="ceo_advisor",
                                snapshot=ks_for_gp,
                                trace=_det_tr_goal_tasks,
                                grounding=_det_grounding_goal_tasks,
                                debug_on=bool(debug_on),
                                exit_path="ceo_chat.deterministic_ssot.goal_scoped_tasks",
                                targeted_reads=targeted_reads_info,
                            )
                            return JSONResponse(
                                content=_attach_session_id(
                                    _det_content_goal_tasks, session_id
                                )
                            )
                except Exception:
                    pass

                md_lang = (
                    payload.metadata
                    if isinstance(getattr(payload, "metadata", None), dict)
                    else {}
                )
                out_lang = str(
                    md_lang.get("ui_output_lang") or md_lang.get("output_lang") or ""
                ).strip()

                phase_a_spec = classify_tasks_phase_a(prompt)
                if phase_a_spec and phase_a_spec.question_type in {
                    "YES_NO",
                    "COUNT",
                    "STATUS",
                }:
                    stats = compute_task_stats(_snap_q)
                    txt_out = render_tasks_phase_a_answer(
                        spec=phase_a_spec,
                        stats=stats,
                        output_lang=out_lang or None,
                    )

                    _det_tr_pa = {
                        "intent": "ssot_task_phase_a",
                        "question_type": phase_a_spec.question_type,
                        "active_only": bool(phase_a_spec.active_only),
                        "exit_path": "deterministic_ssot.task_phase_a",
                        "stats": {
                            "total_count": stats.get("total_count"),
                            "active_count": stats.get("active_count"),
                        },
                    }
                    _det_grounding_pa = _grounding_bundle(
                        prompt=prompt,
                        knowledge_snapshot=ks_for_gp,
                        memory_snapshot=mem_snapshot,
                        legacy_trace=_det_tr_pa,
                        agent_id="ceo_advisor",
                    )
                    _det_content_pa: Dict[str, Any] = {
                        "text": txt_out,
                        "proposed_commands": [],
                        "agent_id": "ceo_advisor",
                        "read_only": True,
                        "notion_ops": {
                            "armed": False,
                            "armed_at": None,
                            "session_id": session_id,
                            "armed_state": {},
                        },
                    }
                    if debug_on:
                        _det_content_pa["trace"] = _det_tr_pa
                        _det_content_pa.update(kb)
                        _det_content_pa.update(_det_grounding_pa)

                    _det_content_pa = _attach_and_log_audit(
                        _det_content_pa,
                        session_id=session_id,
                        conversation_id=conversation_id,
                        agent_id="ceo_advisor",
                        snapshot=ks_for_gp,
                        trace=_det_tr_pa,
                        grounding=_det_grounding_pa,
                        debug_on=bool(debug_on),
                        exit_path="ceo_chat.deterministic_ssot.task_phase_a",
                        targeted_reads=targeted_reads_info,
                    )
                    return JSONResponse(
                        content=_attach_session_id(_det_content_pa, session_id)
                    )

                qtype = classify_task_query(prompt)

                # Guard: avoid hijacking non-task deliverable prompts that merely
                # mention a deadline like "Rok: sutra".
                # This can become order-dependent when other tests or sessions
                # have populated a ready snapshot with tasks.
                try:
                    t0_guard = _norm_bhs_ascii(prompt)
                    has_task_token = bool(
                        re.search(r"(?i)\b(task|taskovi|zadat|zadac)\w*\b", t0_guard)
                    )
                    has_query_cue = bool(
                        re.search(
                            r"(?i)(\?|\b(da\s+li|imamo|koji|koje|sta|shta|prikazi|pokazi|poka(z|z)i|navedi|izlistaj|lista)\b)",
                            t0_guard,
                        )
                    )
                    looks_like_deadline = bool(
                        re.search(
                            r"(?i)\b(rok|deadline|due)\b\s*[:\-]?\s*\b(sutra|tomorrow)\b",
                            t0_guard,
                        )
                    )
                    if (
                        looks_like_deadline
                        and (qtype == "tomorrow")
                        and not (has_task_token or has_query_cue)
                    ):
                        qtype = "none"
                except Exception:
                    pass
                if qtype in {
                    "all",
                    "today",
                    "tomorrow",
                    "overdue",
                    "by_status",
                    "by_priority",
                    "default",
                }:
                    res = run_task_query(snapshot=_snap_q, user_message=prompt)

                    def _norm_bhs_ascii(text: str) -> str:
                        t = (text or "").strip().lower()
                        return (
                            t.replace("č", "c")
                            .replace("ć", "c")
                            .replace("š", "s")
                            .replace("đ", "dj")
                            .replace("ž", "z")
                        )

                    t0 = _norm_bhs_ascii(prompt)
                    wants_full = bool(
                        re.search(
                            r"(?i)\b(pokazi\s+sve|poka(z|z)i\s+sve|izlistaj\s+sve|kompletno|all)\b",
                            t0,
                        )
                        and re.search(
                            r"(?i)\b(task|taskovi|zadat|zadaci|zadatke)\b", t0
                        )
                    )

                    wants_upcoming = bool(
                        re.search(
                            r"(?i)\b(sl(j|j)e(de|d)e(c|ce)|naredn|upcoming)\b",
                            t0,
                        )
                        and re.search(
                            r"(?i)\b(task|taskovi|zadat|zadaci|zadatke)\b", t0
                        )
                    )

                    render_mode = "compact"
                    if wants_full:
                        render_mode = "full"
                    elif wants_upcoming:
                        render_mode = "upcoming"

                    txt_out = render_task_query_answer(
                        res,
                        debug=False,
                        render_mode=render_mode,
                        output_lang=out_lang or None,
                    )
                    _det_tr2 = {
                        "intent": "ssot_task_query",
                        "query_type": res.query_type,
                        "exit_path": "deterministic_ssot_task_query",
                        "stats": res.stats,
                    }
                    _det_grounding2 = _grounding_bundle(
                        prompt=prompt,
                        knowledge_snapshot=ks_for_gp,
                        memory_snapshot=mem_snapshot,
                        legacy_trace=_det_tr2,
                        agent_id="ceo_advisor",
                    )
                    _det_content2: Dict[str, Any] = {
                        "text": txt_out,
                        "proposed_commands": [],
                        "agent_id": "ceo_advisor",
                        "read_only": True,
                        "notion_ops": {
                            "armed": False,
                            "armed_at": None,
                            "session_id": session_id,
                            "armed_state": {},
                        },
                    }
                    if debug_on:
                        _det_content2["trace"] = _det_tr2
                        _det_content2.update(kb)
                        _det_content2.update(_det_grounding2)

                    _det_content2 = _attach_and_log_audit(
                        _det_content2,
                        session_id=session_id,
                        conversation_id=conversation_id,
                        agent_id="ceo_advisor",
                        snapshot=ks_for_gp,
                        trace=_det_tr2,
                        grounding=_det_grounding2,
                        debug_on=bool(debug_on),
                        exit_path="ceo_chat.deterministic_ssot.task_query",
                        targeted_reads=targeted_reads_info,
                    )
                    return JSONResponse(
                        content=_attach_session_id(_det_content2, session_id)
                    )
        except Exception:
            # Fail-soft: never block normal chat routing.
            pass

        # Phase 1c: Deterministic goal ownership lookup (no LLM).
        # Covers questions like: "Ko radi na cilju X?", "Ko je owner cilja X?".
        # HARD RULES:
        # - must be strictly snapshot-derived (no guessing)
        # - must be pre-routing (avoid LLM contradictions)
        try:
            _snap_g = ks_for_gp if isinstance(ks_for_gp, dict) else {}
            if bool(_snap_g.get("ready") is True):
                t0 = _norm_bhs_ascii(prompt)

                def _extract_goal_title_from_goal_line(user_text: str) -> str:
                    # UI format examples:
                    #   "2) Preseli se u EU za 30 dana. | Active | 2026-04-03"
                    #   "2) Title | Status | Due"
                    m = re.search(
                        r"(?m)^\s*\d+\)\s*([^\n\r\|]+?)\s*\|\s*[^\n\r\|]*\|\s*[^\n\r]*$",
                        user_text or "",
                    )
                    if not m:
                        return ""
                    raw = (m.group(1) or "").strip()
                    raw = raw.strip(" \t\r\n\"'.,;:!?-")
                    return raw

                def _is_followup_goal_reference(norm_text: str) -> bool:
                    t = norm_text or ""
                    if not t:
                        return False
                    if re.search(
                        r"(?i)\b(o\s+kojem\s+pricamo|o\s+c(e|)mu\s+pricamo)\b", t
                    ):
                        return True
                    # English follow-up references (voice users often mix EN/BHS):
                    # - "that goal", "this goal", "the goal"
                    # - "the goal we mentioned/discussed/talked about"
                    if re.search(r"(?i)\b(this|that|the|same)\b\s+\bgoal\w*\b", t):
                        return True
                    if re.search(
                        r"(?i)\bgoal\w*\b.*\b(we\s+(mentioned|discussed|talked\s+about)|from\s+before|earlier|above)\b",
                        t,
                    ):
                        return True
                    if re.search(
                        r"(?i)\b(koji\s+smo\s+spomenuli|koji\s+smo\s+pomenuli|koji\s+smo\s+spominjali)\b",
                        t,
                    ):
                        return True
                    if re.search(
                        r"(?i)\b(ovaj|ovom|ovog|ovome|ovo|taj|tom|tog|tome)\b.*\b(cilj|goal)\w*\b",
                        t,
                    ):
                        return True
                    return False

                is_ownership_question = bool(
                    re.search(
                        r"(?i)\b(ko|who)\b.*\b(radi|work|owner|vlasnik|odgovor|zaduzen|assigned)\w*\b",
                        t0,
                    )
                )
                has_goal_token = bool(re.search(r"(?i)\b(cilj|goal)\w*\b", t0))
                goal_line_title = _extract_goal_title_from_goal_line(prompt)
                is_followup_ref = _is_followup_goal_reference(t0)
                is_goal_q = bool(
                    is_ownership_question
                    and (has_goal_token or goal_line_title or is_followup_ref)
                )

                def _extract_goal_ref(user_text: str) -> str:
                    m = re.search(
                        r'(?i)\b(?:cilj(?:u|a)?|goal)\w*\b\s*[:\-\u2013\u2014]?\s*["\u201c\u201d\']?([^\n\r\?\"]+)',
                        user_text or "",
                    )
                    if not m:
                        # Also support cases where the goal title appears before the "cilj/goal" token.
                        # Examples:
                        # - "Ko je odgovoran za Preseli se u EU za 30 dana cilj?"
                        # - "Ko je zaduzen za Preseli se u EU za 30 dana cilj?"
                        # Keep this strictly deterministic: extract the candidate title chunk only.
                        m2 = re.search(
                            r'(?i)\b(?:za|o|na)\b\s*["\u201c\u201d\']?([^\n\r\?\"]+?)\s*["\u201c\u201d\']?\s+\b(?:cilj(?:u|a)?|goal)\w*\b',
                            user_text or "",
                        )
                        if m2:
                            raw2 = (m2.group(1) or "").strip()
                            raw2 = raw2.strip(" \t\r\n\"'.,;:!?-")
                            raw2 = raw2.replace("\\", " ")
                            raw2 = re.split(r"[\.!?]\s+", raw2, maxsplit=1)[0].strip()
                            raw2 = raw2.strip(" \t\r\n\"'.,;:!?")

                            rn2 = _norm_bhs_ascii(raw2)
                            if _is_followup_goal_reference(rn2):
                                return ""
                            if rn2.strip() in {
                                "ovaj",
                                "ovom",
                                "ovog",
                                "ovome",
                                "ovo",
                                "taj",
                                "tom",
                                "tog",
                                "tome",
                                "koji",
                                "kojem",
                                "kojim",
                                "koju",
                                "koje",
                            }:
                                return ""
                            if re.search(
                                r"(?i)\b(ko\s+radi|kome\s+je|ko\s+je|who\s+is|assigned\s+to|owner)\b",
                                rn2,
                            ):
                                return ""
                            if raw2:
                                return raw2

                        # Also accept a bare goal line pasted without "cilj" keyword.
                        return _extract_goal_title_from_goal_line(user_text or "")
                    raw = (m.group(1) or "").strip()
                    raw = raw.lstrip(" \t\r\n\"'.,;:!?-\u2013\u2014")
                    raw = raw.replace("\\", " ")
                    # If user wrote multiple sentences, keep only the first clause.
                    raw = re.split(r"[\.!?]\s+", raw, maxsplit=1)[0].strip()
                    raw = raw.strip(" \t\r\n\"'.,;:!?")

                    # If the extracted chunk is actually just the user's question or a
                    # follow-up phrase, treat it as no explicit goal ref.
                    rn = _norm_bhs_ascii(raw)
                    if _is_followup_goal_reference(rn):
                        return ""
                    if re.search(
                        r"(?i)\b(ko\s+radi|kome\s+je|ko\s+je|who\s+is|assigned\s+to|owner)\b",
                        rn,
                    ):
                        return ""
                    if not raw:
                        return ""
                    # If user pasted the whole UI line after "cilj", normalize it to just title.
                    if "|" in raw and re.search(r"(?m)^\s*\d+\)\s*.+\|", raw):
                        title2 = _extract_goal_title_from_goal_line(raw)
                        if title2:
                            return title2
                    return raw

                def _load_last_referenced_goal_title(
                    *, conversation_id: Optional[str]
                ) -> str:
                    if not (
                        isinstance(conversation_id, str) and conversation_id.strip()
                    ):
                        return ""
                    try:
                        meta = ConversationStateStore.get_meta(
                            conversation_id=conversation_id.strip()
                        )
                    except Exception:
                        return ""
                    if not isinstance(meta, dict):
                        return ""
                    v = meta.get("last_referenced_goal_title")
                    return v.strip() if isinstance(v, str) and v.strip() else ""

                def _load_last_referenced_goal_id(
                    *, conversation_id: Optional[str]
                ) -> str:
                    if not (
                        isinstance(conversation_id, str) and conversation_id.strip()
                    ):
                        return ""
                    try:
                        meta = ConversationStateStore.get_meta(
                            conversation_id=conversation_id.strip()
                        )
                    except Exception:
                        return ""
                    if not isinstance(meta, dict):
                        return ""
                    v = meta.get("last_referenced_goal_id")
                    return v.strip() if isinstance(v, str) and v.strip() else ""

                def _extract_single_goal_title_from_summary(
                    *, conversation_id: Optional[str]
                ) -> str:
                    # Last-resort: parse from persisted assistant text (ConversationStateStore summary).
                    if not (
                        isinstance(conversation_id, str) and conversation_id.strip()
                    ):
                        return ""
                    try:
                        s = ConversationStateStore.get_summary(
                            conversation_id=conversation_id.strip()
                        )
                        summary_txt = s.summary_text
                    except Exception:
                        return ""
                    if not isinstance(summary_txt, str) or not summary_txt.strip():
                        return ""
                    # Search goal line format in the summary; if exactly one, use it.
                    titles = re.findall(
                        r"(?m)^\s*\d+\)\s*([^\n\r\|]+?)\s*\|\s*[^\n\r\|]*\|\s*[^\n\r]*$",
                        summary_txt,
                    )
                    titles = [
                        (t or "").strip().strip(" \t\r\n\"'.,;:!?-")
                        for t in titles
                        if isinstance(t, str)
                    ]
                    titles = [t for t in titles if t]
                    if len(titles) == 1:
                        return titles[0]
                    return ""

                def _people_list(v: Any) -> List[str]:
                    if v is None:
                        return []
                    if isinstance(v, str):
                        s = v.strip()
                        return [s] if s else []
                    if isinstance(v, list):
                        out: List[str] = []
                        for it in v:
                            if isinstance(it, str) and it.strip():
                                out.append(it.strip())
                        return out
                    return []

                def _simplify_prop_key(s: Any) -> str:
                    if not isinstance(s, str):
                        return ""
                    txt = s.strip().lower().replace("_", " ")
                    if not txt:
                        return ""
                    txt = "".join(
                        ch if (ch.isalnum() or ch.isspace()) else " " for ch in txt
                    )
                    txt = re.sub(r"\s+", " ", txt).strip()
                    return txt

                def _people_from_properties(
                    item: Dict[str, Any], prop_names: List[str]
                ) -> List[str]:
                    """Fallback: read people-like values from snapshot item['properties'].

                    Supports the sanitized export from NotionService.build_knowledge_snapshot:
                      properties = {"Assigned To": {"type": "people", "value": ["a@x"]}}
                    """
                    props = item.get("properties")
                    if not isinstance(props, dict) or not props:
                        return []

                    props_map: Dict[str, Any] = {}
                    for k, v in props.items():
                        if not isinstance(k, str) or not k.strip():
                            continue
                        k0 = k.strip().lower()
                        if k0 not in props_map:
                            props_map[k0] = v
                        k1 = _simplify_prop_key(k)
                        if k1 and k1 not in props_map:
                            props_map[k1] = v

                    for nm in prop_names:
                        nm0 = (nm or "").strip()
                        if not nm0:
                            continue
                        key0 = nm0.lower()
                        key1 = _simplify_prop_key(nm0)
                        cand = props_map.get(key0)
                        if cand is None and key1:
                            cand = props_map.get(key1)
                        if cand is None:
                            continue

                        # Sanitized export: {"type": "people", "value": [...]}
                        if isinstance(cand, dict):
                            t = cand.get("type")
                            if isinstance(t, str) and t.strip().lower() == "people":
                                v = cand.get("value")
                                if isinstance(v, list):
                                    return _people_list(v)
                                if isinstance(v, str):
                                    return _people_list(v)

                            # Some workspaces store "Assigned To" as multi_select (tags).
                            # Treat it as a people-like list when explicitly requested via prop_names.
                            if isinstance(t, str) and t.strip().lower() in {
                                "multi_select",
                                "select",
                            }:
                                v = cand.get("value")
                                if isinstance(v, list) or isinstance(v, str):
                                    return _people_list(v)
                                # Best-effort support for a raw Notion-like shape.
                                if t.strip().lower() == "multi_select" and isinstance(
                                    cand.get("multi_select"), list
                                ):
                                    out3: List[str] = []
                                    for it in cand.get("multi_select")[:50]:
                                        if isinstance(it, dict):
                                            nm = it.get("name")
                                            if isinstance(nm, str) and nm.strip():
                                                out3.append(nm.strip())
                                    return _people_list(out3)
                            # Best-effort support if a raw Notion-like payload leaks through.
                            if cand.get("type") == "people" and isinstance(
                                cand.get("people"), list
                            ):
                                ppl = cand.get("people")
                                out2: List[str] = []
                                for p in ppl:
                                    if isinstance(p, dict):
                                        email = (
                                            p.get("person", {}).get("email")
                                            if isinstance(p.get("person"), dict)
                                            else None
                                        )
                                        if isinstance(email, str) and email.strip():
                                            out2.append(email.strip())
                                            continue
                                        name = p.get("name")
                                        if isinstance(name, str) and name.strip():
                                            out2.append(name.strip())
                                return _norm_people(out2)

                        # Some callers may store the list directly.
                        if isinstance(cand, list) or isinstance(cand, str):
                            return _people_list(cand)

                    return []

                def _norm_people(xs: List[str]) -> List[str]:
                    seen = set()
                    out: List[str] = []
                    for x in xs:
                        k = (x or "").strip()
                        if not k:
                            continue
                        kk = k.lower()
                        if kk in seen:
                            continue
                        seen.add(kk)
                        out.append(k)
                    return out

                if is_goal_q:
                    goal_ref = _extract_goal_ref(prompt)
                    goal_id_ref = ""
                    if (
                        is_followup_ref
                        and isinstance(goal_ref, str)
                        and goal_ref.strip()
                    ):
                        grn = _norm_bhs_ascii(goal_ref)
                        if re.fullmatch(
                            r"(?i)(ovaj|ovom|ovog|ovome|ovo|taj|tom|tog|tome|koji\s+smo\s+spomenuli|koji\s+smo\s+pomenuli|koji\s+smo\s+spominjali)",
                            grn.strip(),
                        ):
                            goal_ref = ""
                    if not goal_ref and goal_line_title:
                        goal_ref = goal_line_title
                    # Canonical: if no explicit goal_ref is present, always try the
                    # active goal context ID before asking for a title.
                    if not goal_ref:
                        goal_id_ref = _load_last_referenced_goal_id(
                            conversation_id=conversation_id
                        )
                    if not goal_ref and is_followup_ref:
                        goal_ref = _load_last_referenced_goal_title(
                            conversation_id=conversation_id
                        )
                    if not goal_ref and is_followup_ref:
                        goal_ref = _extract_single_goal_title_from_summary(
                            conversation_id=conversation_id
                        )
                    if goal_ref or goal_id_ref:
                        goals = _snapshot_goals_list(_snap_g)
                        tasks = _snapshot_tasks_list(_snap_g)

                        # If we have a canonical ID reference, prefer an exact ID match.
                        chosen = None
                        if isinstance(goal_id_ref, str) and goal_id_ref.strip():
                            for g in goals:
                                if not isinstance(g, dict):
                                    continue
                                if (g.get("id") or "").strip() == goal_id_ref.strip():
                                    chosen = g
                                    break

                        if chosen is not None:
                            candidates = [chosen]
                            goal_ref_norm = ""
                        else:
                            goal_ref_norm = _norm_bhs_ascii(goal_ref)
                            candidates: List[Dict[str, Any]] = []
                            for g in goals:
                                f = (
                                    g.get("fields")
                                    if isinstance(g.get("fields"), dict)
                                    else {}
                                )
                                title = _pick_str(
                                    g.get("title")
                                    or g.get("name")
                                    or f.get("title")
                                    or f.get("name")
                                )
                                if goal_ref_norm and goal_ref_norm in _norm_bhs_ascii(
                                    title
                                ):
                                    candidates.append(g)

                        if len(candidates) == 1:
                            chosen = candidates[0]
                        elif len(candidates) > 1:
                            # Prefer exact match, else deterministic first-by-title.
                            exact = []
                            for g in candidates:
                                f = (
                                    g.get("fields")
                                    if isinstance(g.get("fields"), dict)
                                    else {}
                                )
                                title = _pick_str(
                                    g.get("title")
                                    or g.get("name")
                                    or f.get("title")
                                    or f.get("name")
                                )
                                if _norm_bhs_ascii(title) == goal_ref_norm:
                                    exact.append(g)
                            if len(exact) == 1:
                                chosen = exact[0]
                            else:
                                candidates_sorted = sorted(
                                    candidates,
                                    key=lambda g: _norm_bhs_ascii(
                                        _pick_str(
                                            g.get("title")
                                            or g.get("name")
                                            or (
                                                g.get("fields", {}).get("title")
                                                if isinstance(g.get("fields"), dict)
                                                else None
                                            )
                                            or (
                                                g.get("fields", {}).get("name")
                                                if isinstance(g.get("fields"), dict)
                                                else None
                                            )
                                        )
                                    ),
                                )
                                chosen = (
                                    candidates_sorted[0] if candidates_sorted else None
                                )

                        if chosen is None:
                            txt_out = (
                                f"Nisam našao cilj '{goal_ref}' u snapshotu. "
                                "Ako naziv nije tačan, pošalji tačan title cilja iz Goals DB."
                            )
                        else:
                            f = (
                                chosen.get("fields")
                                if isinstance(chosen.get("fields"), dict)
                                else {}
                            )
                            goal_title = _pick_str(
                                chosen.get("title")
                                or chosen.get("name")
                                or f.get("title")
                                or f.get("name")
                            )

                            goal_ids: List[str] = []
                            for k in ("id", "notion_id", "notionId"):
                                v = chosen.get(k)
                                if isinstance(v, str) and v.strip():
                                    goal_ids.append(v.strip())

                            goal_id_set = set(goal_ids)

                            owners_goal = _norm_people(
                                _people_list(
                                    f.get("owner")
                                    or f.get("Owner")
                                    or f.get("assigned_to")
                                    or f.get("Assigned To")
                                    or chosen.get("owner")
                                    or chosen.get("assigned_to")
                                )
                            )

                            if not owners_goal:
                                owners_goal = _norm_people(
                                    _people_from_properties(
                                        chosen,
                                        [
                                            "Assigned To",
                                            "Assigned",
                                            "Assignee",
                                            "Owner",
                                            "assigned_to",
                                            "owner",
                                        ],
                                    )
                                )

                            linked_task_people: List[str] = []
                            linked_tasks = 0
                            for t in tasks:
                                if not goal_id_set:
                                    # Without a stable goal id, we can't safely join tasks -> goal.
                                    break
                                tf = (
                                    t.get("fields")
                                    if isinstance(t.get("fields"), dict)
                                    else {}
                                )
                                refs = (
                                    t.get("goal_ids")
                                    or t.get("goalIds")
                                    or t.get("goal_id")
                                    or t.get("goal")
                                    or tf.get("goal_ids")
                                    or tf.get("goalIds")
                                    or tf.get("goal_id")
                                    or tf.get("goal")
                                    or []
                                )
                                if isinstance(refs, str) and refs.strip():
                                    refs = [refs.strip()]
                                if not isinstance(refs, list):
                                    refs = []
                                refs_norm = [
                                    r.strip()
                                    for r in refs
                                    if isinstance(r, str) and r.strip()
                                ]
                                if not any(r in goal_id_set for r in refs_norm):
                                    continue
                                linked_tasks += 1
                                ppl_task = _people_list(
                                    tf.get("assigned_to")
                                    or tf.get("Assigned To")
                                    or tf.get("owner")
                                    or tf.get("Owner")
                                    or t.get("assigned_to")
                                    or t.get("owner")
                                )
                                if not ppl_task:
                                    ppl_task = _people_from_properties(
                                        t,
                                        [
                                            "Assigned To",
                                            "Assigned",
                                            "Assignee",
                                            "Owner",
                                            "assigned_to",
                                        ],
                                    )
                                linked_task_people.extend(ppl_task)

                            owners_tasks = _norm_people(linked_task_people)

                            # Persist the resolved goal as the latest referenced goal.
                            try:
                                if (
                                    isinstance(conversation_id, str)
                                    and conversation_id.strip()
                                    and isinstance(goal_title, str)
                                    and goal_title.strip()
                                ):
                                    updates: Dict[str, Any] = {
                                        "last_referenced_goal_title": goal_title.strip(),
                                        "last_referenced_goal_title_norm": _norm_bhs_ascii(
                                            goal_title
                                        ),
                                        "last_referenced_goal_source": "deterministic_goal_ownership",
                                        "last_referenced_goal_at": float(time.time()),
                                    }
                                    if goal_ids:
                                        # Canonical reference (single) + back-compat list.
                                        if (
                                            isinstance(goal_ids[0], str)
                                            and goal_ids[0].strip()
                                        ):
                                            updates["last_referenced_goal_id"] = (
                                                goal_ids[0].strip()
                                            )
                                        updates["last_referenced_goal_ids"] = goal_ids[
                                            :3
                                        ]
                                    ConversationStateStore.update_meta(
                                        conversation_id=conversation_id.strip(),
                                        updates=updates,
                                    )
                            except Exception:
                                pass

                            if owners_goal:
                                txt_out = (
                                    f"Za cilj \"{goal_title}\" su odgovorni: {', '.join(owners_goal)}."
                                ).strip()

                                if owners_tasks:
                                    owners_tasks_extra = [
                                        o
                                        for o in owners_tasks
                                        if isinstance(o, str)
                                        and o.strip()
                                        and o not in owners_goal
                                    ]
                                    if owners_tasks_extra:
                                        txt_out = (
                                            txt_out
                                            + f" Na povezanim zadacima su zaduženi: {', '.join(owners_tasks_extra)}."
                                        )
                            elif owners_tasks:
                                txt_out = (
                                    f"Za cilj \"{goal_title}\" su navedeni kao zaduženi na povezanim zadacima: {', '.join(owners_tasks)}."
                                ).strip()
                            else:
                                txt_out = (
                                    f'Za cilj "{goal_title}" u snapshotu nema owner/assigned_to niti zaduženih na povezanim zadacima.'
                                ).strip()

                        # Persist bounded multi-turn context even on deterministic exits.
                        try:
                            if (
                                isinstance(conversation_id, str)
                                and conversation_id.strip()
                            ):
                                ConversationStateStore.append_turn(
                                    conversation_id=conversation_id.strip(),
                                    user_text=prompt or "",
                                    assistant_text=txt_out or "",
                                )
                        except Exception:
                            pass

                        _det_tr3 = {
                            "intent": "goal_ownership_lookup",
                            "exit_path": "deterministic_snapshot_goal_ownership",
                            "goal_ref": goal_ref,
                        }
                        _det_grounding3 = _grounding_bundle(
                            prompt=prompt,
                            knowledge_snapshot=ks_for_gp,
                            memory_snapshot=mem_snapshot,
                            legacy_trace=_det_tr3,
                            agent_id="ceo_advisor",
                        )
                        _det_content3: Dict[str, Any] = {
                            "text": txt_out,
                            "proposed_commands": [],
                            "agent_id": "ceo_advisor",
                            "read_only": True,
                            "notion_ops": {
                                "armed": False,
                                "armed_at": None,
                                "session_id": session_id,
                                "armed_state": {},
                            },
                        }
                        if debug_on:
                            _det_content3["trace"] = _det_tr3
                            _det_content3.update(kb)
                            _det_content3.update(_det_grounding3)

                        _det_content3 = _attach_and_log_audit(
                            _det_content3,
                            session_id=session_id,
                            conversation_id=conversation_id,
                            agent_id="ceo_advisor",
                            snapshot=ks_for_gp,
                            trace=_det_tr3,
                            grounding=_det_grounding3,
                            debug_on=bool(debug_on),
                            exit_path="ceo_chat.deterministic_ssot.goal_ownership",
                            targeted_reads=targeted_reads_info,
                        )
                        return JSONResponse(
                            content=_attach_session_id(_det_content3, session_id)
                        )
                    else:
                        # If intent matches but goal reference is missing, keep behavior predictable.
                        # Ask for the exact goal title rather than letting the LLM guess.
                        if is_followup_ref:
                            txt_out = (
                                'Ne mogu pouzdano odrediti na koji cilj misliš ("ovaj/taj cilj"). '
                                "Pošalji tačan title cilja ili kopiraj cijeli red iz liste (npr. '2) Title | Status | Due')."
                            )
                        else:
                            txt_out = "Za koji cilj? Pošalji naziv cilja (npr. 'Ko radi na cilju: Rast prihoda Q1')."

                        # Persist bounded multi-turn context even on deterministic exits.
                        try:
                            if (
                                isinstance(conversation_id, str)
                                and conversation_id.strip()
                            ):
                                ConversationStateStore.append_turn(
                                    conversation_id=conversation_id.strip(),
                                    user_text=prompt or "",
                                    assistant_text=txt_out or "",
                                )
                        except Exception:
                            pass
                        _det_tr3b = {
                            "intent": "goal_ownership_lookup",
                            "exit_path": "deterministic_snapshot_goal_ownership",
                            "goal_ref": None,
                        }
                        _det_grounding3b = _grounding_bundle(
                            prompt=prompt,
                            knowledge_snapshot=ks_for_gp,
                            memory_snapshot=mem_snapshot,
                            legacy_trace=_det_tr3b,
                            agent_id="ceo_advisor",
                        )
                        _det_content3b: Dict[str, Any] = {
                            "text": txt_out,
                            "proposed_commands": [],
                            "agent_id": "ceo_advisor",
                            "read_only": True,
                            "notion_ops": {
                                "armed": False,
                                "armed_at": None,
                                "session_id": session_id,
                                "armed_state": {},
                            },
                        }
                        if debug_on:
                            _det_content3b["trace"] = _det_tr3b
                            _det_content3b.update(kb)
                            _det_content3b.update(_det_grounding3b)
                        _det_content3b = _attach_and_log_audit(
                            _det_content3b,
                            session_id=session_id,
                            conversation_id=conversation_id,
                            agent_id="ceo_advisor",
                            snapshot=ks_for_gp,
                            trace=_det_tr3b,
                            grounding=_det_grounding3b,
                            debug_on=bool(debug_on),
                            exit_path="ceo_chat.deterministic_ssot.goal_ownership",
                            targeted_reads=targeted_reads_info,
                        )
                        return JSONResponse(
                            content=_attach_session_id(_det_content3b, session_id)
                        )
        except Exception:
            pass

        # Build a first grounding pack early so the agent can cite KB ids deterministically.
        pre_grounding = _grounding_bundle(
            prompt=prompt,
            knowledge_snapshot=ks_for_gp,
            memory_snapshot=mem_snapshot,
            legacy_trace=None,
            agent_id="ceo_advisor",
        )
        gp_for_agent = (
            pre_grounding.get("grounding_pack")
            if isinstance(pre_grounding, dict)
            else None
        )
        gp_for_agent = gp_for_agent if isinstance(gp_for_agent, dict) else {}

        # Ensure grounding pack notion_snapshot matches the snapshot the agent received.
        try:
            snap_for_agent = getattr(payload, "snapshot", None)
            if isinstance(snap_for_agent, dict):
                gp_for_agent["notion_snapshot"] = snap_for_agent
        except Exception:
            pass

        # Phase 2: Inject CEO_VIEW into grounding pack so build_ceo_instructions
        # can render it even when notion_snapshot is budget_exceeded/redacted.
        try:
            _snap_cv = ks_for_gp if isinstance(ks_for_gp, dict) else {}
            if bool(_snap_cv.get("ready") is True):
                gp_for_agent["ceo_view"] = _compute_ceo_view(_snap_cv)
        except Exception:
            pass

        # Call advisor agent
        try:
            # Allow callers to provide additional agent context via metadata.agent_ctx.
            md0 = getattr(payload, "metadata", None)
            ctx_extra = md0.get("agent_ctx") if isinstance(md0, dict) else None

            # Router-provided SSOT context (must not be dropped).
            router_ctx: Dict[str, Any] = {
                "memory": mem_snapshot,
                "grounding_pack": gp_for_agent,
                # Parity with /api/ceo/command: provide notion snapshot explicitly.
                "notion_snapshot": getattr(payload, "snapshot", None)
                if isinstance(getattr(payload, "snapshot", None), dict)
                else {},
                "snapshot": getattr(payload, "snapshot", None)
                if isinstance(getattr(payload, "snapshot", None), dict)
                else {},
                "conversation_id": conversation_id,
                "conversation_state": conv_summary,
            }

            # Explicitly propagate conversation meta + canonical goal reference.
            try:
                conv_meta: Dict[str, Any] = {}
                if isinstance(conversation_id, str) and conversation_id.strip():
                    meta0 = ConversationStateStore.get_meta(
                        conversation_id=conversation_id.strip()
                    )
                    if isinstance(meta0, dict):
                        conv_meta = dict(meta0)
                router_ctx["conversation_meta"] = conv_meta
                v = conv_meta.get("last_referenced_goal_id")
                if isinstance(v, str) and v.strip():
                    router_ctx["last_referenced_goal_id"] = v.strip()
            except Exception:
                router_ctx["conversation_meta"] = {}

            # Deep-merge metadata.agent_ctx with router_ctx so nested objects aren't overwritten/dropped.
            ctx_for_agent: Dict[str, Any] = (
                dict(ctx_extra) if isinstance(ctx_extra, dict) else {}
            )
            _deep_merge_dicts(ctx_for_agent, router_ctx)

            # Also persist into metadata.agent_ctx for route parity / traceability.
            if isinstance(md0, dict):
                md0.setdefault(
                    "snapshot_source", "KnowledgeSnapshotService.get_snapshot"
                )
                md0.setdefault("agent_ctx", {})
                if isinstance(md0.get("agent_ctx"), dict):
                    _deep_merge_dicts(
                        md0["agent_ctx"],
                        {
                            "notion_snapshot": router_ctx.get("notion_snapshot"),
                            "grounding_pack": gp_for_agent,
                        },
                    )
                payload.metadata = md0  # type: ignore[assignment]

            out = None

            # If an AgentRouterService instance is injected, use it for the default path
            # while forcing ceo_advisor to preserve existing behavior.
            try:
                import inspect  # noqa: PLC0415

                can_route = agent_router is not None and callable(
                    getattr(agent_router, "route", None)
                )

                if can_route:
                    try:
                        # Build a cloned AgentInput for routing so we can attach full ctx
                        # without mutating the original payload (avoids logging surprises).
                        dumped = None
                        try:
                            dumped = payload.model_dump()  # type: ignore[attr-defined]
                        except Exception:
                            dumped = payload.dict()  # type: ignore[attr-defined]

                        dumped = dumped if isinstance(dumped, dict) else {}
                        md_r = dumped.get("metadata")
                        md_r = md_r if isinstance(md_r, dict) else {}
                        md_r = dict(md_r)

                        agent_ctx_r = md_r.get("agent_ctx")
                        agent_ctx_r = (
                            agent_ctx_r if isinstance(agent_ctx_r, dict) else {}
                        )
                        agent_ctx_r = dict(agent_ctx_r)
                        _deep_merge_dicts(agent_ctx_r, router_ctx)
                        md_r["agent_ctx"] = agent_ctx_r

                        dumped["metadata"] = md_r
                        dumped["preferred_agent_id"] = "ceo_advisor"
                        payload_for_router = AgentInput(**dumped)

                    except Exception:
                        # Best-effort fallback: mutate the existing payload in-memory.
                        payload_for_router = payload
                        try:
                            payload_for_router.preferred_agent_id = "ceo_advisor"  # type: ignore[attr-defined]
                        except Exception:
                            pass

                        md_r = getattr(payload_for_router, "metadata", None)
                        md_r = md_r if isinstance(md_r, dict) else {}
                        md_r = dict(md_r)
                        agent_ctx_r = md_r.get("agent_ctx")
                        agent_ctx_r = (
                            agent_ctx_r if isinstance(agent_ctx_r, dict) else {}
                        )
                        agent_ctx_r = dict(agent_ctx_r)
                        _deep_merge_dicts(agent_ctx_r, router_ctx)
                        md_r["agent_ctx"] = agent_ctx_r
                        payload_for_router.metadata = md_r  # type: ignore[assignment]

                    routed = agent_router.route(payload_for_router)
                    if inspect.isawaitable(routed):
                        out = await routed
                    else:
                        out = routed

                else:
                    out = await create_ceo_advisor_agent(
                        payload,
                        ctx_for_agent,
                    )
            except LLMNotConfiguredError:
                raise
            except Exception:
                out = await create_ceo_advisor_agent(
                    payload,
                    ctx_for_agent,
                )

            # Ensure /api/chat always returns trace.snapshot + used_sources, even when
            # include_debug is off (minimal trace mode).
            try:
                snap_for_trace = getattr(payload, "snapshot", None)
                snap_for_trace = (
                    snap_for_trace if isinstance(snap_for_trace, dict) else {}
                )

                tr0 = out.trace if hasattr(out, "trace") else {}
                tr0 = tr0 if isinstance(tr0, dict) else {}
                out.trace = _ensure_trace_snapshot_and_sources(
                    tr0,
                    grounding_pack=gp_for_agent,
                    snapshot=snap_for_trace,
                )
            except Exception:
                pass
        except LLMNotConfiguredError as e:
            return JSONResponse(
                status_code=500,
                content=_attach_session_id(
                    _attach_and_log_audit(
                        {
                            "text": str(e),
                            "proposed_commands": [],
                            "agent_id": "ceo_advisor",
                            "read_only": True,
                            "trace": {
                                "intent": "error",
                                "exit_reason": "error.llm_not_configured",
                            },
                            "error": {
                                "code": "error.llm_not_configured",
                                "message": str(e),
                            },
                        },
                        session_id=session_id,
                        conversation_id=conversation_id,
                        agent_id="ceo_advisor",
                        snapshot=getattr(payload, "snapshot", None),
                        trace={
                            "intent": "error",
                            "exit_reason": "error.llm_not_configured",
                        },
                        grounding={},
                        debug_on=bool(debug_on),
                        exit_path="ceo_chat.error.llm_not_configured",
                        targeted_reads=targeted_reads_info,
                    ),
                    session_id,
                ),
            )

        # Persist bounded multi-turn context (never log content).
        try:
            if isinstance(conversation_id, str) and conversation_id.strip():
                ConversationStateStore.append_turn(
                    conversation_id=conversation_id.strip(),
                    user_text=prompt or "",
                    assistant_text=(getattr(out, "text", "") or ""),
                )
        except Exception:
            pass

        legacy_trace = out.trace or {}
        if isinstance(legacy_trace, dict) and isinstance(notion_calls_for_trace, int):
            legacy_trace["notion_calls"] = int(notion_calls_for_trace)
        grounding = _grounding_bundle(
            prompt=prompt,
            knowledge_snapshot=ks_for_gp,
            memory_snapshot=mem_snapshot,
            legacy_trace=legacy_trace if isinstance(legacy_trace, dict) else {},
            agent_id=getattr(out, "agent_id", None),
        )

        # KB TRACE PASSTHROUGH (context -> trace)
        _apply_kb_trace_passthrough_from_context(out.trace, grounding_bundle=grounding)

        pcs = getattr(out, "proposed_commands", None)
        normalized = _normalize_proposed_commands(pcs)
        actionable = [pc for pc in normalized if _is_actionable(pc)]

        # PHASE 6: hard gate when not ARMED
        if not armed:
            # Only gate Notion write proposals when DISARMED.
            has_notion_write = any(
                (
                    getattr(pc, "command", None) == "notion_write"
                    or getattr(pc, "intent", None) == "notion_write"
                )
                for pc in actionable
            )
            if has_notion_write or _looks_like_write_intent(prompt):
                return _blocked_response(
                    out=out,
                    prompt=prompt,
                    session_id=session_id,
                    state=st,
                    why="Write intent detected but Notion Ops is not ARMED.",
                    kb=kb,
                    grounding=grounding,
                    debug_on=debug_on,
                    audit_fn=lambda c: _attach_and_log_audit(
                        c,
                        session_id=session_id,
                        conversation_id=conversation_id,
                        agent_id=getattr(out, "agent_id", None),
                        snapshot=getattr(payload, "snapshot", None),
                        trace=getattr(out, "trace", None),
                        grounding=grounding,
                        debug_on=bool(debug_on),
                        exit_path="ceo_chat.blocked.not_armed",
                        targeted_reads=targeted_reads_info,
                    ),
                )

            # Non-Notion actionable proposals (e.g. delegation) are allowed even
            # when Notion Ops is DISARMED (Notion gate applies to Notion writes).
            actionable_non_notion = [
                pc
                for pc in actionable
                if not (
                    getattr(pc, "command", None) == "notion_write"
                    or getattr(pc, "intent", None) == "notion_write"
                )
            ]
            if actionable_non_notion:
                for pc in actionable_non_notion:
                    _finalize_actionable(pc)

                pcs_out: List[Dict[str, Any]] = []
                for pc in actionable_non_notion:
                    d = (
                        pc.model_dump(by_alias=False)
                        if hasattr(pc, "model_dump")
                        else pc.dict(by_alias=False)
                    )
                    if isinstance(d, dict):
                        pcs_out.append(_ensure_payload_summary_contract(d))

                _persist_pending_proposal(
                    proposal_key, [] if pending_declined else pcs_out
                )

                content = {
                    "text": _apply_post_answer_snapshot_consistency_guard(
                        out.text,
                        snapshot=getattr(payload, "snapshot", None),
                    ),
                    "proposed_commands": pcs_out,
                    "agent_id": out.agent_id,
                    "read_only": True,
                    "notion_ops": {
                        "armed": False,
                        "armed_at": None,
                        "session_id": session_id,
                        "armed_state": st,
                    },
                }
                if debug_on:
                    tr0 = out.trace or {}
                    if not isinstance(tr0, dict):
                        tr0 = {}
                    tr0["memory_provider"] = memory_provider
                    tr0["memory_items_count"] = memory_items_count
                    tr0["memory_error"] = memory_error
                    tr0.setdefault("phase6_notion_ops_gate", {})
                    tr0["phase6_notion_ops_gate"] = {
                        "armed": False,
                        "session_id_present": bool(session_id),
                        "why": "non_notion_actionable_allowed",
                    }
                    content["trace"] = tr0
                    content.update(kb)
                    content.update(grounding)
                else:
                    minimal_trace = _minimal_trace_intent(out.trace)
                    if minimal_trace:
                        content["trace"] = minimal_trace
                content = _attach_and_log_audit(
                    content,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    agent_id=content.get("agent_id"),
                    snapshot=getattr(payload, "snapshot", None),
                    trace=out.trace,
                    grounding=grounding,
                    debug_on=bool(debug_on),
                    exit_path="ceo_chat.disarmed.non_notion_actionable",
                    targeted_reads=targeted_reads_info,
                )
                return JSONResponse(content=_attach_session_id(content, session_id))

            # If the advisor returned non-actionable proposal wrappers (e.g. approval-gated
            # memory/knowledge write proposals), keep them even when Notion Ops is DISARMED.
            # This preserves the enterprise workflow: propose → approve → execute.
            wrappers = [
                pc
                for pc in normalized
                if getattr(pc, "command", None) == PROPOSAL_WRAPPER_INTENT
            ]
            if wrappers:
                pcs_out: List[Dict[str, Any]] = []
                for pc in wrappers:
                    d = _pc_to_dict(pc, prompt=prompt)
                    pcs_out.append(_ensure_payload_summary_contract(d))

                _persist_pending_proposal(
                    proposal_key, [] if pending_declined else pcs_out
                )

                content: Dict[str, Any] = {
                    "text": _apply_post_answer_snapshot_consistency_guard(
                        out.text,
                        snapshot=getattr(payload, "snapshot", None),
                    ),
                    "proposed_commands": pcs_out,
                    "agent_id": out.agent_id,
                    "read_only": True,
                    "notion_ops": {
                        "armed": False,
                        "armed_at": None,
                        "session_id": session_id,
                        "armed_state": st,
                    },
                }
                if debug_on:
                    tr0 = out.trace or {}
                    if not isinstance(tr0, dict):
                        tr0 = {}
                    tr0["memory_provider"] = memory_provider
                    tr0["memory_items_count"] = memory_items_count
                    tr0["memory_error"] = memory_error
                    content["trace"] = tr0
                    content.update(kb)
                    content.update(grounding)
                else:
                    minimal_trace = _minimal_trace_intent(out.trace)
                    if minimal_trace:
                        content["trace"] = minimal_trace
                content = _attach_and_log_audit(
                    content,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    agent_id=content.get("agent_id"),
                    snapshot=getattr(payload, "snapshot", None),
                    trace=out.trace,
                    grounding=grounding,
                    debug_on=bool(debug_on),
                    exit_path="ceo_chat.disarmed.wrapper_proposals",
                    targeted_reads=targeted_reads_info,
                )
                return JSONResponse(content=_attach_session_id(content, session_id))

            content: Dict[str, Any] = {
                "text": _apply_post_answer_snapshot_consistency_guard(
                    out.text,
                    snapshot=getattr(payload, "snapshot", None),
                ),
                "proposed_commands": [],
                "agent_id": out.agent_id,
                "read_only": True,
                "notion_ops": {
                    "armed": False,
                    "armed_at": None,
                    "session_id": session_id,
                    "armed_state": st,
                },
            }
            _persist_pending_proposal(proposal_key, [])
            if debug_on:
                tr0 = out.trace or {}
                if not isinstance(tr0, dict):
                    tr0 = {}
                tr0["memory_provider"] = memory_provider
                tr0["memory_items_count"] = memory_items_count
                tr0["memory_error"] = memory_error
                content["trace"] = tr0
                content.update(kb)
                content.update(grounding)
            else:
                minimal_trace = _minimal_trace_intent(out.trace)
                if minimal_trace:
                    content["trace"] = minimal_trace
            content = _attach_and_log_audit(
                content,
                session_id=session_id,
                conversation_id=conversation_id,
                agent_id=content.get("agent_id"),
                snapshot=getattr(payload, "snapshot", None),
                trace=out.trace,
                grounding=grounding,
                debug_on=bool(debug_on),
                exit_path="ceo_chat.disarmed.no_actionable",
                targeted_reads=targeted_reads_info,
            )
            return JSONResponse(content=_attach_session_id(content, session_id))

        # ARMED: allow actionable, otherwise allow approval-wrapper fallback
        if actionable:
            for pc in actionable:
                _finalize_actionable(pc)

            pcs_out: List[Dict[str, Any]] = []
            for pc in actionable:
                d = (
                    pc.model_dump(by_alias=False)
                    if hasattr(pc, "model_dump")
                    else pc.dict(by_alias=False)
                )
                if isinstance(d, dict):
                    pcs_out.append(_ensure_payload_summary_contract(d))

            _persist_pending_proposal(proposal_key, [] if pending_declined else pcs_out)

            tr = out.trace or {}
            if not isinstance(tr, dict):
                tr = {}
            tr.setdefault("phase6_notion_ops_gate", {})
            tr["phase6_notion_ops_gate"] = {
                "armed": True,
                "session_id_present": bool(session_id),
            }

            text_out = out.text
            if _looks_like_write_intent(prompt):
                text_out = _armed_write_ack(prompt, has_actionable=True)

            text_out = _apply_post_answer_snapshot_consistency_guard(
                text_out,
                snapshot=getattr(payload, "snapshot", None),
            )

            content: Dict[str, Any] = {
                "text": text_out,
                "proposed_commands": pcs_out,
                "agent_id": out.agent_id,
                "read_only": True,
                "notion_ops": {
                    "armed": True,
                    "armed_at": st.get("armed_at"),
                    "session_id": session_id,
                    "armed_state": st,
                },
            }
            if debug_on:
                tr["memory_provider"] = memory_provider
                tr["memory_items_count"] = memory_items_count
                tr["memory_error"] = memory_error
                content["trace"] = tr
                content.update(kb)
                content.update(grounding)
            else:
                minimal_trace = _minimal_trace_intent(tr)
                if minimal_trace:
                    content["trace"] = minimal_trace
            content = _attach_and_log_audit(
                content,
                session_id=session_id,
                conversation_id=conversation_id,
                agent_id=content.get("agent_id"),
                snapshot=getattr(payload, "snapshot", None),
                trace=tr,
                grounding=grounding,
                debug_on=bool(debug_on),
                exit_path="ceo_chat.armed.actionable",
                targeted_reads=targeted_reads_info,
            )
            return JSONResponse(content=_attach_session_id(content, session_id))

        # No actionable → fallback:
        if _looks_like_write_intent(prompt):
            fallback = _build_approval_wrapper(
                prompt,
                reason="Approval required (write intent, but no structured proposal returned).",
            )
        else:
            fallback = None

        out.read_only = True

        tr = out.trace or {}
        if not isinstance(tr, dict):
            tr = {}
        tr.setdefault("phase6_notion_ops_gate", {})
        tr["phase6_notion_ops_gate"] = {
            "armed": True,
            "session_id_present": bool(session_id),
            "fallback": True,
        }

        text_out = out.text
        if _looks_like_write_intent(prompt):
            text_out = _armed_write_ack(prompt, has_actionable=False)

        text_out = _apply_post_answer_snapshot_consistency_guard(
            text_out,
            snapshot=getattr(payload, "snapshot", None),
        )

        content: Dict[str, Any] = {
            "text": text_out,
            "proposed_commands": [
                _ensure_payload_summary_contract(_pc_to_dict(fallback, prompt=prompt))
            ]
            if isinstance(fallback, ProposedCommand)
            else [],
            "agent_id": out.agent_id,
            "read_only": True,
            "notion_ops": {
                "armed": True,
                "armed_at": st.get("armed_at"),
                "session_id": session_id,
                "armed_state": st,
            },
        }

        _persist_pending_proposal(
            proposal_key,
            [] if pending_declined else (content.get("proposed_commands") or []),
        )
        if debug_on:
            tr["memory_provider"] = memory_provider
            tr["memory_items_count"] = memory_items_count
            tr["memory_error"] = memory_error
            content["trace"] = tr
            content.update(kb)
            content.update(grounding)
        else:
            minimal_trace = _minimal_trace_intent(tr)
            if minimal_trace:
                content["trace"] = minimal_trace
        content = _attach_and_log_audit(
            content,
            session_id=session_id,
            conversation_id=conversation_id,
            agent_id=content.get("agent_id"),
            snapshot=getattr(payload, "snapshot", None),
            trace=tr,
            grounding=grounding,
            debug_on=bool(debug_on),
            exit_path="ceo_chat.armed.fallback",
            targeted_reads=targeted_reads_info,
        )
        return JSONResponse(content=_attach_session_id(content, session_id))

    @router.post("/chat/stream")
    async def chat_stream(payload: AgentInput, request: Request):
        """NDJSON streaming wrapper for canonical chat.

        - Feature-flagged via CHAT_STREAMING_ENABLED (default OFF).
        - Does NOT modify /chat behavior; it delegates final response generation to /chat.
        """

        if not _chat_streaming_enabled():
            return JSONResponse(
                status_code=404, content={"error": "chat_streaming_disabled"}
            )

        request_id = uuid.uuid4().hex
        session_id = (
            getattr(payload, "session_id", None)
            if isinstance(getattr(payload, "session_id", None), str)
            else None
        )
        conversation_id = (
            getattr(payload, "conversation_id", None)
            if isinstance(getattr(payload, "conversation_id", None), str)
            else None
        )
        if not conversation_id:
            conversation_id = session_id

        async def _iter_ndjson():
            seq = 0

            def _emit(evt_type: str, data: Dict[str, Any]):
                nonlocal seq
                evt = {
                    "v": 1,
                    "type": evt_type,
                    "seq": seq,
                    "ts": _iso_utc_now(),
                    "request_id": request_id,
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "data": data,
                }
                seq += 1
                return (json.dumps(evt, ensure_ascii=False) + "\n").encode("utf-8")

            yield _emit(
                "meta",
                {
                    "source_endpoint": "/api/chat/stream",
                    "model": None,
                    "agent_id": None,
                    "capabilities": {"text_streaming": True, "final_response": True},
                },
            )

            try:
                final_resp = await chat(payload, request)

                body_bytes = getattr(final_resp, "body", b"")
                if not isinstance(body_bytes, (bytes, bytearray, memoryview)):
                    body_bytes = b""
                if not body_bytes:
                    raise RuntimeError("canonical_chat_empty_body")

                try:
                    body_obj = json.loads(bytes(body_bytes).decode("utf-8"))
                except Exception as exc:
                    raise RuntimeError(f"canonical_chat_non_json_body: {exc}")

                if not isinstance(body_obj, dict):
                    raise RuntimeError("canonical_chat_non_object_body")

                # IMPORTANT: StreamingResponse bypasses the JSON-response middleware
                # that enforces the "no internal template leak" contract.
                # Apply the same sanitizer here to prevent CEO intro / memory
                # boilerplate from ever appearing in stream payloads.
                try:
                    from gateway.gateway_server import (  # type: ignore
                        sanitize_user_visible_answer,
                    )

                    sanitized = sanitize_user_visible_answer(
                        body_obj=body_obj,
                        prompt=str(getattr(payload, "message", "") or ""),
                        session_id=session_id or "",
                        conversation_id=conversation_id or "",
                    )
                    if isinstance(sanitized, dict):
                        body_obj = sanitized

                        # Streaming payloads should not include the leaked internal
                        # template anywhere (even in debug fields) because tests
                        # and downstream clients may inspect raw NDJSON.
                        md = body_obj.get("metadata")
                        if isinstance(md, dict):
                            dbg = md.get("debug")
                            if isinstance(dbg, dict) and "internal_system_text" in dbg:
                                dbg.pop("internal_system_text", None)
                                if not dbg:
                                    md.pop("debug", None)
                                body_obj["metadata"] = md
                except Exception:
                    # Fail-safe: if sanitizer import or logic fails, do not block streaming.
                    pass

                text_out = str(body_obj.get("text") or "")
                for part in _chunk_text(text_out):
                    if part:
                        yield _emit("assistant.delta", {"delta_text": part})

                yield _emit(
                    "assistant.final",
                    {
                        "text": text_out,
                        "response": body_obj,
                    },
                )
                yield _emit("done", {"ok": True, "reason": "completed"})

            except Exception as exc:
                yield _emit(
                    "error",
                    {
                        "code": "internal_error",
                        "message": str(exc),
                        "retryable": False,
                        "http_status": 500,
                    },
                )
                yield _emit("done", {"ok": False, "reason": "error"})

        return StreamingResponse(
            _iter_ndjson(),
            status_code=200,
            media_type="application/x-ndjson",
            headers={
                "Content-Type": "application/x-ndjson; charset=utf-8",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return router
