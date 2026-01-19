from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from openai import OpenAI

from services.ceo_alignment_engine import CEOAlignmentEngine  # <-- already present
from services.identity_loader import load_ceo_identity_pack
from services.knowledge_service import KnowledgeService
from services.world_state_engine import WorldStateEngine  # <-- already present

# OPTION C (Behaviour router) - best-effort import (FAIL-SOFT, enterprise)
try:
    from services.ceo_behavior_router import CEOBehaviorRouter  # type: ignore
except Exception:  # noqa: BLE001
    CEOBehaviorRouter = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# OpenAI Assistants API hard limit: 256000 chars
# Keep a safety margin for envelopes / minor growth.
_MAX_OPENAI_CONTENT_CHARS = 240000

# Defensive trimming limits for snapshot compaction
_MAX_LIST_ITEMS = 30
_MAX_TEXT_CHARS = 1200


class ReadOnlyToolCallAttempt(RuntimeError):
    """Raised when a run attempts tool calls in read-only / no-tools mode."""


# -------------------------------------------------------------------
# CEO ADVISORY OUTPUT CONTRACT (KANONSKI / STABILAN)
# -------------------------------------------------------------------
_CEO_ADVISORY_JSON_ONLY_INSTRUCTIONS = """You are the CEO Advisor in a READ-ONLY mode.

Hard constraints:
- NO TOOL CALLS. NO side effects. Use only the provided snapshot/context.
- You MUST return a single JSON object as the assistant's final message. No markdown fences.
- The JSON MUST have exactly these keys:
  summary (string),
  text (string),
  questions (array of strings),
  plan (array of strings),
  options (array of strings),
  proposed_commands (array of objects),
  trace (object).

Rules:
- proposed_commands MUST be an array. If none, return [].
- Do NOT include any extra keys beyond the schema.
"""

_CEO_ADVISORY_DASHBOARD_JSON_INSTRUCTIONS = """You are the CEO Advisor in a READ-ONLY mode.

Hard constraints:
- NO TOOL CALLS. NO side effects. Use only the provided snapshot/context.
- You MUST return a single JSON object as the assistant's final message. No markdown fences.
- The JSON MUST have exactly these keys:
  summary (string),
  text (string),
  questions (array of strings),
  plan (array of strings),
  options (array of strings),
  proposed_commands (array of objects),
  trace (object).

Text formatting rules (DASHBOARD MODE):
- text MUST start with the line: GOALS (top 3)
- text MUST include both sections: GOALS (top 3) and TASKS (top 5)
- Each item line MUST follow: <name/title> | <status> | <priority>
- Do NOT include any other prose outside these sections in text.
- Do NOT embed JSON in the 'text' field.
- proposed_commands MUST be an array. If none, return [].

If there are fewer than 3 goals or 5 tasks in the snapshot, list what exists and add a line:
NEMA DOVOLJNO PODATAKA U SNAPSHOT-U
"""


# -------------------------------------------------------------------
# OPTION C (BEHAVIOUR OVERLAY) Ă˘â‚¬â€ť ENTERPRISE, DETERMINISTIC, FAIL-SOFT
# -------------------------------------------------------------------
_BEHAVIOUR_MODE_SUFFIX: Dict[str, str] = {
    # Minimal output when everything is aligned and no action is required.
    # IMPORTANT: runtime enforcement exists for SILENT (see _apply_silent_runtime_enforcement).
    "silent": """Behaviour mode: SILENT.
Rules:
- If there is NO immediate critical risk explicitly stated in alignment_snapshot.law_compliance
  (system_integrity == False OR risk_level in {"high","critical"}):
  - summary MUST be "".
  - text MUST be "".
  - questions MUST be [].
  - plan MUST be [].
  - options MUST be [].
  - proposed_commands MUST be [].
- If there IS immediate critical risk (as above), output ONLY:
  - summary: 1 line risk label
  - text: max 2 lines immediate actions
  - questions/plan/options empty, proposed_commands []
""",
    # Monitoring posture: short, no speculation.
    "monitor": """Behaviour mode: MONITOR.
Rules:
- Provide at most 2 observations derived from the snapshot/context.
- Provide at most 1 monitoring suggestion derived from the snapshot/context.
- No speculative plans. No invented facts.
- proposed_commands MUST be [] unless alignment_snapshot explicitly requires action.
""",
    # Normal advisory: structured tradeoffs; still read-only.
    "advisory": """Behaviour mode: ADVISORY.
Rules:
- Provide up to 3 options with tradeoffs grounded in the provided context.
- Ask clarifying questions only if required to resolve an explicit missing field.
""",
    # Executive: decisive, one primary recommendation.
    "executive": """Behaviour mode: EXECUTIVE.
Rules:
- Recommend ONE primary course of action grounded in snapshot/context.
- Provide at most 2 backup options.
- Keep it concise; avoid long essays.
""",
    # Red alert: system integrity takes precedence.
    "red_alert": """Behaviour mode: RED_ALERT.
Rules:
- Lead with the integrity/risk issue and the required CEO action.
- Ignore non-critical user request parts if they conflict with system integrity.
- Keep it short, non-negotiable, and grounded in the provided context.
""",
}


def _compose_run_instructions(base: str, behaviour_mode: Optional[str]) -> str:
    """
    Deterministic instruction overlay.
    - Never changes JSON schema contract.
    - Only adds behaviour constraints.
    """
    mode = (behaviour_mode or "").strip().lower()
    suffix = _BEHAVIOUR_MODE_SUFFIX.get(mode, "")
    if not suffix.strip():
        return base
    return base.rstrip() + "\n\n" + suffix.strip() + "\n"


def _extract_behaviour_mode_from_context(context: Dict[str, Any]) -> tuple[str, str]:
    """
    Deterministic (per requirement):
    1) context.identity_pack.behaviour_mode
    2) context.metadata.behaviour_mode
    3) default: advisory

    Returns: (mode, source) where source in {"identity_pack","metadata","default"}.
    """
    behaviour_mode = "advisory"
    source = "default"

    ip = context.get("identity_pack")
    if isinstance(ip, dict):
        v = ip.get("behaviour_mode")
        if isinstance(v, str) and v.strip():
            behaviour_mode = v.strip()
            source = "identity_pack"

    if source == "default":
        md = context.get("metadata")
        if isinstance(md, dict):
            v = md.get("behaviour_mode")
            if isinstance(v, str) and v.strip():
                behaviour_mode = v.strip()
                source = "metadata"

    mode = behaviour_mode.strip().lower() or "advisory"
    if mode not in _BEHAVIOUR_MODE_SUFFIX:
        mode = "advisory"
        source = "default"
    return mode, source


def _is_critical_risk_from_alignment(alignment_snapshot: Any) -> bool:
    """
    Deterministic: critical risk only if explicitly stated in known keys:
      alignment_snapshot.law_compliance.system_integrity == False OR
      alignment_snapshot.law_compliance.risk_level in {"high","critical"} (case-insensitive)
    """
    if not isinstance(alignment_snapshot, dict):
        return False
    lc = (
        alignment_snapshot.get("law_compliance")
        if isinstance(alignment_snapshot.get("law_compliance"), dict)
        else {}
    )

    system_integrity = lc.get("system_integrity")
    if system_integrity is False:
        return True

    risk_level = lc.get("risk_level")
    if isinstance(risk_level, str) and risk_level.strip().lower() in {
        "high",
        "critical",
    }:
        return True

    return False


def _apply_silent_runtime_enforcement(
    parsed: Dict[str, Any], *, critical_risk: bool
) -> Dict[str, Any]:
    """
    Hard deterministic enforcement for SILENT mode:
    - If NOT critical risk => blank output + empty arrays (regardless of LLM compliance).
    - If critical risk => do not modify (LLM output allowed within constraints).
    """
    if critical_risk:
        return parsed

    parsed["summary"] = ""
    parsed["text"] = ""
    parsed["questions"] = []
    parsed["plan"] = []
    parsed["options"] = []
    parsed["proposed_commands"] = []
    return parsed


def _derive_behaviour_mode_fallback(alignment_snapshot: Any) -> Optional[str]:
    """
    Enterprise fallback if CEOBehaviorRouter module is not available.
    Uses only keys that are ALREADY referenced in this file (no new schema assumptions).
    """
    if not isinstance(alignment_snapshot, dict):
        return None

    sa = (
        alignment_snapshot.get("strategic_alignment")
        if isinstance(alignment_snapshot.get("strategic_alignment"), dict)
        else {}
    )
    lc = (
        alignment_snapshot.get("law_compliance")
        if isinstance(alignment_snapshot.get("law_compliance"), dict)
        else {}
    )
    ca = (
        alignment_snapshot.get("ceo_action_required")
        if isinstance(alignment_snapshot.get("ceo_action_required"), dict)
        else {}
    )

    requires_action = ca.get("requires_action")
    system_integrity = lc.get("system_integrity")
    risk_level = lc.get("risk_level")
    overall_status = sa.get("overall_status")

    # If integrity is explicitly compromised Ă˘â€ â€™ red_alert
    if system_integrity is False:
        return "red_alert"

    # High risk can also justify red_alert if explicitly stated as string.
    if isinstance(risk_level, str) and risk_level.strip().lower() in {
        "high",
        "critical",
    }:
        return "red_alert"

    # If action is explicitly required Ă˘â€ â€™ executive
    if requires_action is True:
        return "executive"

    # If alignment explicitly says misaligned/weak Ă˘â€ â€™ advisory
    if isinstance(overall_status, str) and overall_status.strip().lower() in {
        "misaligned",
        "weak",
        "warning",
        "at_risk",
    }:
        return "advisory"

    # Default aligned no-action posture: monitor (safe default)
    if requires_action is False:
        return "monitor"

    return None


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _trim_text(s: Any, limit: int = _MAX_TEXT_CHARS) -> Any:
    if not isinstance(s, str):
        return s
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 12)] + "...(trimmed)"


def _compact_snapshot(snapshot: Any) -> Any:
    """
    Reduce snapshot size deterministically:
    - keep only high-signal fields for LLM
    - drop heavy keys: properties / types / raw blobs
    - cap list lengths and trim long strings
    """
    if snapshot is None:
        return None

    if isinstance(snapshot, str):
        return _trim_text(snapshot)

    if isinstance(snapshot, (int, float, bool)):
        return snapshot

    if isinstance(snapshot, list):
        return [_compact_snapshot(x) for x in snapshot[:_MAX_LIST_ITEMS]]

    if not isinstance(snapshot, dict):
        return _trim_text(str(snapshot))

    DROP_KEYS = {
        "properties",
        "properties_types",
        "raw",
        "raw_pages",
        "raw_page",
        "page_raw",
        "content_raw",
        "blocks_raw",
    }

    out: Dict[str, Any] = {}
    for k, v in snapshot.items():
        if k in DROP_KEYS:
            continue

        # dashboard is usually heavy; keep compact structure
        if k == "dashboard" and isinstance(v, dict):
            dash: Dict[str, Any] = {}
            goals = v.get("goals")
            tasks = v.get("tasks")
            meta = v.get("metadata") or v.get("meta")

            def _slim_item(it: Any) -> Any:
                if not isinstance(it, dict):
                    return _compact_snapshot(it)

                keep = {
                    "id",
                    "title",
                    "name",
                    "status",
                    "priority",
                    "due_date",
                    "deadline",
                    "lead",
                    "project",
                    "goal",
                    "goals",
                    "task_id",
                    "order",
                    "properties_text",
                }
                slim: Dict[str, Any] = {}
                for kk in keep:
                    if kk in it:
                        slim[kk] = _compact_snapshot(it.get(kk))
                return slim

            if isinstance(goals, list):
                dash["goals"] = [_slim_item(g) for g in goals[:_MAX_LIST_ITEMS]]
            if isinstance(tasks, list):
                dash["tasks"] = [_slim_item(t) for t in tasks[:_MAX_LIST_ITEMS]]
            if isinstance(meta, dict):
                dash["metadata"] = _compact_snapshot(meta)

            out["dashboard"] = dash
            continue

        out[k] = _compact_snapshot(v)

    # final trim strings at top-level
    for kk, vv in list(out.items()):
        out[kk] = _trim_text(vv)

    return out


def _compact_identity_pack(identity_pack: Any) -> Any:
    """
    DeterministiĂ„Ĺ¤ka kompakcija identity pack-a da se sigurno poÄąË‡alje u LLM context.

    Reuse postojeĂ„â€ˇe snapshot kompaktovanje (lista cap + trim), uz dodatno izbacivanje
    heavy/raw kljuĂ„Ĺ¤eva ako se pojave.
    """
    if identity_pack is None:
        return None

    if isinstance(identity_pack, dict):
        DROP_KEYS = {
            "raw",
            "raw_pages",
            "raw_page",
            "page_raw",
            "content_raw",
            "blocks_raw",
        }
        slim = {k: v for k, v in identity_pack.items() if k not in DROP_KEYS}
        return _compact_snapshot(slim)

    return _compact_snapshot(identity_pack)


def _safe_dumps_for_openai(payload: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """
    Always returns content <= _MAX_OPENAI_CONTENT_CHARS.
    Returns (content, shrink_trace).
    """
    raw = json.dumps(payload, ensure_ascii=False, default=_json_default)
    if len(raw) <= _MAX_OPENAI_CONTENT_CHARS:
        return raw, {"shrunk": False, "chars": len(raw)}

    compact_payload = dict(payload)

    # Most payloads have {context:{snapshot:...}} pattern
    ctx = compact_payload.get("context")
    if isinstance(ctx, dict):
        ctx2 = dict(ctx)

        snap = ctx2.get("snapshot")
        if snap is not None:
            ctx2["snapshot"] = _compact_snapshot(snap)

        # compact identity_pack if present
        ip = ctx2.get("identity_pack")
        if ip is not None:
            ctx2["identity_pack"] = _compact_identity_pack(ip)

        # compact world_state_snapshot if present
        ws = ctx2.get("world_state_snapshot")
        if ws is not None:
            ctx2["world_state_snapshot"] = _compact_snapshot(ws)

        # compact alignment_snapshot if present
        al = ctx2.get("alignment_snapshot")
        if al is not None:
            ctx2["alignment_snapshot"] = _compact_snapshot(al)

        compact_payload["context"] = ctx2

    compact = json.dumps(compact_payload, ensure_ascii=False, default=_json_default)
    if len(compact) <= _MAX_OPENAI_CONTENT_CHARS:
        return compact, {
            "shrunk": True,
            "from": len(raw),
            "to": len(compact),
            "strategy": "compact_snapshot",
        }

    trimmed = compact[: _MAX_OPENAI_CONTENT_CHARS - 20] + "...(hard_trim)"
    return trimmed, {
        "shrunk": True,
        "from": len(raw),
        "to": len(trimmed),
        "strategy": "hard_trim",
    }


def _format_identity_knowledge_for_prompt(user_text: str, max_items: int = 6) -> str:
    try:
        ks = KnowledgeService()
        entries = ks.entries()
    except Exception as e:  # noqa: BLE001
        logger.warning("KnowledgeService load failed: %s", e)
        return ""

    text = (user_text or "").lower()

    def score(entry: Dict[str, Any]) -> float:
        s = float(entry.get("priority", 0.0) or 0.0)
        tags = entry.get("tags") or []
        tags_l = [t.lower() for t in tags if isinstance(t, str)]

        for t2 in tags_l:
            if t2 and t2 in text:
                s += 0.5

        if "notion" in text and "notion" in tags_l:
            s += 0.6
        if "approval" in text and "approval" in tags_l:
            s += 0.6
        if "agent" in text and ("agents" in tags_l or "dispatch" in tags_l):
            s += 0.4
        if "policy" in text and ("governance" in tags_l or "safety" in tags_l):
            s += 0.4

        return s

    ranked = sorted(
        [e for e in entries if isinstance(e, dict)], key=score, reverse=True
    )[: max(1, int(max_items))]
    if not ranked:
        return ""

    lines = ["IDENTITY KNOWLEDGE (canonical):"]
    for e in ranked:
        eid = e.get("id", "")
        title = e.get("title", "")
        content = e.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        lines.append(f"- [{eid}] {title}: {_trim_text(content, 600)}")

    return "\n".join(lines).strip()


def _extract_goals_tasks_block(text: str) -> str:
    """
    Extract canonical GOALS/TASKS block from any mixed assistant output.
    If not found or incomplete, return empty string.
    """
    t = (text or "").strip()
    if not t:
        return ""

    m = re.search(r"(^|\n)GOALS\s*\(top\s*3\)\s*\n", t, flags=re.IGNORECASE)
    if not m:
        return ""

    start = m.start() if (m.group(1) == "") else (m.start() + 1)
    block = t[start:].strip()

    if not re.search(r"(^|\n)TASKS\s*\(top\s*5\)\s*\n", block, flags=re.IGNORECASE):
        return ""

    block = re.sub(r"^GOALS\s*\(top\s*3\)", "GOALS (top 3)", block, flags=re.IGNORECASE)
    block = re.sub(
        r"(^|\n)TASKS\s*\(top\s*5\)", r"\1TASKS (top 5)", block, flags=re.IGNORECASE
    )

    return block.strip()


def _pick_text(parsed: Dict[str, Any]) -> str:
    """
    Prefer parsed['text'], fallback to summary/raw.
    """
    if not isinstance(parsed, dict):
        return ""
    for k in ("text", "summary"):
        v = parsed.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    raw = parsed.get("raw")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return ""


def _ensure_contract(
    parsed: Dict[str, Any], *, enforce_dashboard_text: bool
) -> Dict[str, Any]:
    """
    Ensure canonical CEO advisory result:
      summary, text, questions, plan, options, proposed_commands, trace
    """
    if not isinstance(parsed, dict):
        parsed = {"raw": str(parsed)}

    raw = parsed.get("raw")

    # If assistant returned plain text only
    if (
        isinstance(raw, str)
        and raw.strip()
        and ("summary" not in parsed and "text" not in parsed)
    ):
        if enforce_dashboard_text:
            extracted = _extract_goals_tasks_block(raw)
            if extracted:
                parsed = {
                    "summary": "CEO advisor output extracted from raw text (dashboard fallback normalization).",
                    "text": extracted,
                    "questions": [],
                    "plan": [],
                    "options": [],
                    "proposed_commands": [],
                    "trace": {"llm": "raw_text_extracted"},
                }
            else:
                parsed = {
                    "summary": raw.strip(),
                    "text": raw.strip(),
                    "questions": [],
                    "plan": [],
                    "options": [],
                    "proposed_commands": [],
                    "trace": {"llm": "raw_text_mapped"},
                }
        else:
            parsed = {
                "summary": raw.strip(),
                "text": raw.strip(),
                "questions": [],
                "plan": [],
                "options": [],
                "proposed_commands": [],
                "trace": {"llm": "raw_text_mapped"},
            }

    # Ensure keys exist
    if "summary" not in parsed or not isinstance(parsed.get("summary"), str):
        parsed["summary"] = (
            str(raw) if raw is not None else "LLM odgovor nema 'summary'."
        )

    if (
        "text" not in parsed
        or not isinstance(parsed.get("text"), str)
        or not str(parsed.get("text")).strip()
    ):
        parsed["text"] = (parsed.get("summary") or "").strip()

    if not isinstance(parsed.get("questions"), list):
        parsed["questions"] = []
    if not isinstance(parsed.get("plan"), list):
        parsed["plan"] = []
    if not isinstance(parsed.get("options"), list):
        parsed["options"] = []
    if not isinstance(parsed.get("proposed_commands"), list):
        parsed["proposed_commands"] = []
    if not isinstance(parsed.get("trace"), dict):
        parsed["trace"] = {}

    parsed["questions"] = [x for x in parsed["questions"] if isinstance(x, str)]
    parsed["plan"] = [x for x in parsed["plan"] if isinstance(x, str)]
    parsed["options"] = [x for x in parsed["options"] if isinstance(x, str)]

    # Only enforce GOALS/TASKS shape in dashboard mode
    if enforce_dashboard_text:
        extracted2 = _extract_goals_tasks_block(parsed.get("text", ""))
        if extracted2:
            parsed["text"] = extracted2
        else:
            tr = parsed.get("trace") if isinstance(parsed.get("trace"), dict) else {}
            tr["format_fallback"] = True
            parsed["trace"] = tr

    # Hard-shape proposed_commands: list[object]
    pc = parsed.get("proposed_commands")
    if isinstance(pc, list):
        parsed["proposed_commands"] = [x for x in pc if isinstance(x, dict)]
    else:
        parsed["proposed_commands"] = []

    return parsed


def _is_dashboard_query(user_text: str) -> bool:
    """
    Lightweight heuristic: only enforce GOALS/TASKS contract for dashboard/listing queries.
    """
    t = (user_text or "").lower().strip()
    if not t:
        return False

    # IMPORTANT: "create/update" commands must NOT be treated as dashboard/listing queries.
    action_prefixes = (
        "kreiraj",
        "create",
        "napravi",
        "dodaj",
        "update",
        "izmijeni",
        "promijeni",
    )
    if t.startswith(action_prefixes):
        return False

    keywords = [
        "goals",
        "goal",
        "cilj",
        "ciljevi",
        "tasks",
        "task",
        "taskovi",
        "top 3",
        "top3",
        "top 5",
        "top5",
        "najvaÄąÄľn",
        "najhitnij",
        "snapshot",
        "status",
        "prioritet",
        "priority",
        "dashboard",
    ]

    return any(k in t for k in keywords)


def _run_last_error_details(run_status: Any) -> Dict[str, Any]:
    """
    Extract as much useful info as possible from a run object across SDK versions.
    """
    out: Dict[str, Any] = {}

    status = getattr(run_status, "status", None)
    if status is not None:
        out["status"] = status

    last_error = getattr(run_status, "last_error", None)
    if last_error is not None:
        code = getattr(last_error, "code", None)
        msg = getattr(last_error, "message", None)
        out["last_error"] = {
            "code": code if code is not None else None,
            "message": msg
            if isinstance(msg, str)
            else (str(msg) if msg is not None else None),
        }

    incomplete = getattr(run_status, "incomplete_details", None)
    if incomplete is not None:
        reason = getattr(incomplete, "reason", None)
        out["incomplete_details"] = {"reason": reason if reason is not None else None}

    for k in ("id", "assistant_id", "thread_id", "model"):
        v = getattr(run_status, k, None)
        if v is not None:
            out[k] = v

    return out


class OpenAIAssistantExecutor:
    """
    CANON (nakon ustava):
    - Ova klasa sluÄąÄľi kao CEO Advisor (READ-ONLY, bez tool poziva).
    - Legacy execution put (LLM Notion Ops) je onemoguĂ„â€ˇen i hard-blokiran.
    """

    def __init__(
        self,
        *,
        execution_assistant_id_env: str = "NOTION_OPS_ASSISTANT_ID",
        advisory_assistant_id_env: str = "CEO_ADVISOR_ASSISTANT_ID",
        poll_interval_s: float = 0.5,
        max_wait_s: float = 60.0,
    ) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing")

        self._execution_assistant_id_env = execution_assistant_id_env
        self._advisory_assistant_id_env = advisory_assistant_id_env
        self._poll_interval_s = float(poll_interval_s)
        self._max_wait_s = float(max_wait_s)

        self.client = OpenAI(api_key=api_key)

    async def _to_thread(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _get_execution_assistant_id_or_raise(self) -> str:
        assistant_id = os.getenv(self._execution_assistant_id_env)
        if not assistant_id:
            raise RuntimeError(f"{self._execution_assistant_id_env} is missing")
        return assistant_id

    def _get_advisory_assistant_id(self) -> Optional[str]:
        assistant_id = os.getenv(self._advisory_assistant_id_env)
        if assistant_id:
            return assistant_id
        return os.getenv(self._execution_assistant_id_env)

    async def _cancel_run_best_effort(self, *, thread_id: str, run_id: str) -> None:
        try:
            await self._to_thread(
                self.client.beta.threads.runs.cancel, thread_id=thread_id, run_id=run_id
            )
        except Exception:
            return

    async def _wait_for_run_completion(
        self,
        *,
        thread_id: str,
        run_id: str,
        allow_tools: bool,
    ) -> None:
        """
        CANONICAL BEHAVIOR:
        - Tool calls are ALWAYS disallowed in this executor, regardless of allow_tools.
        - If a run enters `requires_action`, we cancel and raise ReadOnlyToolCallAttempt.
        """
        _ = allow_tools  # keep signature compatibility; tools are hard-disabled
        start = time.monotonic()

        while True:
            if time.monotonic() - start > self._max_wait_s:
                await self._cancel_run_best_effort(thread_id=thread_id, run_id=run_id)
                raise RuntimeError("Assistant run timed out")

            run_status = await self._to_thread(
                self.client.beta.threads.runs.retrieve,
                thread_id=thread_id,
                run_id=run_id,
            )

            status = getattr(run_status, "status", None)

            if status == "requires_action":
                required_action = getattr(run_status, "required_action", None)
                submit = (
                    getattr(required_action, "submit_tool_outputs", None)
                    if required_action
                    else None
                )
                tool_calls = getattr(submit, "tool_calls", None) if submit else None

                await self._cancel_run_best_effort(thread_id=thread_id, run_id=run_id)

                names: list[str] = []
                if tool_calls:
                    for call in tool_calls:
                        fn = getattr(call, "function", None)
                        fn_name = getattr(fn, "name", None) if fn else None
                        if fn_name:
                            names.append(str(fn_name))

                raise ReadOnlyToolCallAttempt(
                    f"Run attempted tool calls (hard-blocked): {names or ['(unknown)']}"
                )

            if status == "completed":
                return

            if status in {"failed", "cancelled", "expired"}:
                details = _run_last_error_details(run_status)
                raise RuntimeError(
                    f"Assistant run failed with status: {status}; details={json.dumps(details, ensure_ascii=False)}"
                )

            await asyncio.sleep(self._poll_interval_s)

    async def _get_final_assistant_message_text(self, *, thread_id: str) -> str:
        messages = await self._to_thread(
            self.client.beta.threads.messages.list, thread_id=thread_id
        )
        data = getattr(messages, "data", None) or []
        assistant_messages = [
            m for m in data if getattr(m, "role", None) == "assistant"
        ]

        if not assistant_messages:
            raise RuntimeError("Assistant produced no response")

        def _created_at(msg: Any) -> int:
            ca = getattr(msg, "created_at", None)
            return int(ca) if isinstance(ca, int) else 0

        msg = max(assistant_messages, key=_created_at)

        content = getattr(msg, "content", None)
        if not content:
            raise RuntimeError("Assistant response has empty content")

        chunks: list[str] = []
        for part in content:
            text_obj = getattr(part, "text", None)
            value = getattr(text_obj, "value", None) if text_obj else None
            if isinstance(value, str) and value.strip():
                chunks.append(value)

        value = "\n".join(chunks).strip()
        if not value:
            raise RuntimeError("Assistant produced empty text response")

        return value

    def _strip_code_fences(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            return t
        m = re.match(
            r"^```(?:json)?\s*(.*?)\s*```$", t, flags=re.DOTALL | re.IGNORECASE
        )
        if m:
            return (m.group(1) or "").strip()
        return t

    def _safe_json_parse(self, text: str) -> Dict[str, Any]:
        cleaned = self._strip_code_fences(text)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            return {"raw": parsed}
        except Exception:
            return {"raw": cleaned}

    async def _create_run_best_effort(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        instructions: Optional[str] = None,
        tool_choice: Optional[Any] = None,
    ):
        """
        Compatibility layer for SDK / API shape changes.

        NOTE:
        - Some Assistants API deployments do NOT support tool_choice="none".
          In that case, we OMIT tool_choice entirely and rely on the
          read-only guard (_wait_for_run_completion) to cancel if tools are attempted.
        """
        attempts: list[Dict[str, Any]] = []

        # Normalize tool_choice: omit unsupported "none"
        tc = tool_choice
        if isinstance(tc, str) and tc.strip().lower() == "none":
            tc = None

        # Most strict: instructions + tool_choice (if present)
        kw0: Dict[str, Any] = {"thread_id": thread_id, "assistant_id": assistant_id}
        if instructions is not None:
            kw0["instructions"] = instructions
        if tc is not None:
            kw0["tool_choice"] = tc
        attempts.append(kw0)

        # Drop tool_choice
        kw1 = dict(kw0)
        kw1.pop("tool_choice", None)
        attempts.append(kw1)

        # Drop instructions (in case SDK doesn't accept it)
        kw2 = dict(kw1)
        kw2.pop("instructions", None)
        attempts.append(kw2)

        last_exc: Optional[Exception] = None
        for i, kwargs in enumerate(attempts, start=1):
            try:
                return await self._to_thread(
                    self.client.beta.threads.runs.create, **kwargs
                )
            except TypeError as e:
                last_exc = e
                logger.warning(
                    "runs.create TypeError on attempt %s/%s: %s", i, len(attempts), e
                )
                continue
            except Exception as e:  # noqa: BLE001
                msg = str(e).lower()
                if ("tool_choice" in msg or "instructions" in msg) and (
                    "unknown" in msg
                    or "unrecognized" in msg
                    or "unexpected" in msg
                    or "invalid" in msg
                ):
                    last_exc = e
                    logger.warning(
                        "runs.create param rejected on attempt %s/%s: %s",
                        i,
                        len(attempts),
                        e,
                    )
                    continue
                raise

        if last_exc:
            raise last_exc
        raise RuntimeError("runs.create failed for unknown reasons")

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        LEGACY (ONEMOGUĂ„â€ ENO).
        """
        raise RuntimeError(
            "OpenAIAssistantExecutor.execute je onemoguĂ„â€ˇen: "
            "LLM-based Notion Ops execution path je uklonjen. "
            "Koristi backend Notion Ops Executor / NotionService preko approval flow-a."
        )

    async def ceo_command(
        self, *, text: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        t = (text or "").strip()
        if not t:
            raise ValueError("text is required")
        if not isinstance(context, dict):
            context = {}

        # OPTION C (PRACTICAL COMPLETION):
        # Prefer behaviour_mode explicitly provided by AgentInput-like context.
        input_behaviour_mode, input_behaviour_source = (
            _extract_behaviour_mode_from_context(context)
        )

        assistant_id = self._get_advisory_assistant_id()
        if not assistant_id:
            return {
                "summary": "LLM executor nije konfigurisan (nema Assistant ID).",
                "text": "LLM executor nije konfigurisan (nema Assistant ID).",
                "questions": [
                    "Postavi Assistant ID (CEO_ADVISOR_ASSISTANT_ID ili NOTION_OPS_ASSISTANT_ID)."
                ],
                "plan": ["KonfiguriÄąË‡i LLM executor i ponovi CEO Command."],
                "options": [],
                "proposed_commands": [],
                "trace": {"llm": "not_configured"},
            }

        enforce_dashboard_text = bool(
            ((context or {}).get("metadata") or {}).get("structured_mode")
        )
        thread = await self._to_thread(self.client.beta.threads.create)

        safe_context = dict(context)
        canon = dict(safe_context.get("canon") or {})
        canon["read_only"] = True
        canon["no_tools"] = True
        canon["no_side_effects"] = True
        safe_context["canon"] = canon

        knowledge_block = _format_identity_knowledge_for_prompt(t, max_items=6)
        if knowledge_block:
            safe_context["identity_knowledge"] = knowledge_block

        # FULL IDENTITY PACK injection (OPTION 2: inject only when available == True)
        identity_pack: Any = None
        identity_pack_available = False
        identity_pack_errors_count = 0

        try:
            identity_pack = load_ceo_identity_pack()
        except Exception as e:  # noqa: BLE001
            logger.warning("load_ceo_identity_pack() failed: %s", e)
            identity_pack = None

        if isinstance(identity_pack, dict):
            identity_pack_available = bool(identity_pack.get("available") is True)
            errors = identity_pack.get("errors") or []
            identity_pack_errors_count = len(errors) if isinstance(errors, list) else 0

            if identity_pack_available is True:
                safe_context["identity_pack"] = _compact_identity_pack(identity_pack)

        # SotW snapshot injection (CANON: backend reads Notion, LLM gets snapshot only)
        world_state_snapshot = None
        world_state_trace = None

        try:
            full_snapshot = await WorldStateEngine().abuild_snapshot()

            if isinstance(full_snapshot, dict):
                world_state_trace = full_snapshot.get("trace")

                world_state_snapshot = dict(full_snapshot)
                world_state_snapshot.pop("trace", None)

        except Exception as e:  # noqa: BLE001
            logger.warning("WorldStateEngine.abuild_snapshot() failed: %s", e)
            world_state_snapshot = None
            world_state_trace = None

        if isinstance(world_state_snapshot, dict):
            safe_context["world_state_snapshot"] = world_state_snapshot
        if isinstance(world_state_trace, dict):
            safe_context["world_state_trace"] = world_state_trace

        # ------------------------------------------------------------
        # Alignment snapshot injection (Option A SSOT; deterministic, no LLM, no Notion)
        # ------------------------------------------------------------
        alignment_snapshot = None
        try:
            ip_for_alignment = identity_pack if isinstance(identity_pack, dict) else {}
            ws_for_alignment = (
                world_state_snapshot if isinstance(world_state_snapshot, dict) else {}
            )
            alignment_snapshot = CEOAlignmentEngine().evaluate(
                ip_for_alignment, ws_for_alignment
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("CEOAlignmentEngine.evaluate() failed: %s", e)
            alignment_snapshot = None

        if isinstance(alignment_snapshot, dict):
            safe_context["alignment_snapshot"] = alignment_snapshot

        # ------------------------------------------------------------
        # OPTION C (Behaviour mode selection + Instruction Overlay)
        # ------------------------------------------------------------
        behaviour_router_available = bool(CEOBehaviorRouter is not None)
        behaviour_mode: Optional[str] = None
        behaviour_mode_source: str = "none"
        behaviour_mode_applied: bool = False

        # 0) If mode was provided in input (identity_pack/metadata), it has priority.
        if input_behaviour_source != "default":
            behaviour_mode = input_behaviour_mode
            behaviour_mode_source = input_behaviour_source

        # 1) Otherwise, compute from alignment snapshot (existing behaviour).
        if behaviour_mode is None and isinstance(alignment_snapshot, dict):
            if CEOBehaviorRouter is not None:
                try:
                    # Router API shape is NIJE POZNATO, so we handle both common shapes.
                    router = CEOBehaviorRouter()  # type: ignore[call-arg]
                    if hasattr(router, "select_mode"):
                        behaviour_mode = router.select_mode(alignment_snapshot)  # type: ignore[attr-defined]
                        behaviour_mode_source = "router.select_mode"
                    elif hasattr(CEOBehaviorRouter, "select_mode"):
                        behaviour_mode = CEOBehaviorRouter.select_mode(
                            alignment_snapshot
                        )  # type: ignore[attr-defined]
                        behaviour_mode_source = "CEOBehaviorRouter.select_mode"
                    else:
                        behaviour_mode = None
                        behaviour_mode_source = "router_missing_method"
                except Exception as e:  # noqa: BLE001
                    logger.warning("CEOBehaviorRouter failed: %s", e)
                    behaviour_mode = None
                    behaviour_mode_source = "router_error"

            # Deterministic fallback derived only from known keys
            if not isinstance(behaviour_mode, str) or not behaviour_mode.strip():
                behaviour_mode = _derive_behaviour_mode_fallback(alignment_snapshot)
                if behaviour_mode:
                    behaviour_mode_source = "fallback_derived"

        # 2) Final normalize + validate
        if not isinstance(behaviour_mode, str) or not behaviour_mode.strip():
            behaviour_mode = "advisory"
            behaviour_mode_source = "default"

        behaviour_mode = behaviour_mode.strip().lower()
        if behaviour_mode not in _BEHAVIOUR_MODE_SUFFIX:
            behaviour_mode = "advisory"
            behaviour_mode_source = "default"

        base_instructions = (
            _CEO_ADVISORY_DASHBOARD_JSON_INSTRUCTIONS
            if enforce_dashboard_text
            else _CEO_ADVISORY_JSON_ONLY_INSTRUCTIONS
        )
        run_instructions = _compose_run_instructions(base_instructions, behaviour_mode)
        behaviour_mode_applied = True

        advisory_contract = {
            "type": "ceo_advice",
            "text": t,
            "context": safe_context,
            "constraints": {
                "read_only": True,
                "no_tools": True,
                "no_side_effects": True,
                "return_json": True,
            },
            "run_instructions": run_instructions,
            "output_schema": {
                "summary": "string",
                "text": "string",
                "questions": "list[string]",
                "plan": "list[string]",
                "options": "list[string]",
                "proposed_commands": "list[object]",
                "trace": "object",
            },
        }

        content, shrink_trace = _safe_dumps_for_openai(advisory_contract)

        await self._to_thread(
            self.client.beta.threads.messages.create,
            thread_id=thread.id,
            role="user",
            content=content,
        )

        t0 = time.monotonic()
        run = None
        try:
            run = await self._create_run_best_effort(
                thread_id=thread.id,
                assistant_id=assistant_id,
                instructions=run_instructions,
                tool_choice=None,
            )

            await self._wait_for_run_completion(
                thread_id=thread.id, run_id=run.id, allow_tools=False
            )

            final_text = await self._get_final_assistant_message_text(
                thread_id=thread.id
            )
            parsed = self._safe_json_parse(final_text)
            parsed = _ensure_contract(
                parsed, enforce_dashboard_text=enforce_dashboard_text
            )

            # HARD runtime enforcement for SILENT mode (deterministic).
            if behaviour_mode == "silent":
                critical = _is_critical_risk_from_alignment(alignment_snapshot)
                parsed = _apply_silent_runtime_enforcement(
                    parsed, critical_risk=critical
                )

        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.exception("CEO advisory failed (assistant_id=%s)", assistant_id)

            err_type = exc.__class__.__name__
            err_msg = str(exc)[:2000]
            err_repr = repr(exc)[:2000]

            if isinstance(exc, ReadOnlyToolCallAttempt):
                summary = (
                    "CEO advisory je pokušao tool poziv u read-only modu (blokirano)."
                )
                text_out = (
                    "CEO advisory je pokušao tool poziv u read-only modu, što je zabranjeno.\n"
                    "Provjeri Assistant instrukcije i konfiguraciju; read-only path mora biti bez tool poziva."
                )
            else:
                summary = (
                    f"CEO advisory nije mogao završiti (internal error: {err_type})."
                )
                text_out = (
                    f"CEO advisory nije mogao završiti (internal error: {err_type})."
                )

            if os.getenv("DEBUG_CEO_ADVISOR_ERRORS") == "1":
                text_out = f"{text_out}\n\nDEBUG_ERROR:\n{err_repr}"

            # alignment trace fields (best-effort)
            a_meta: Dict[str, Any] = {}
            if isinstance(alignment_snapshot, dict):
                sa = (
                    alignment_snapshot.get("strategic_alignment")
                    if isinstance(alignment_snapshot.get("strategic_alignment"), dict)
                    else {}
                )
                lc = (
                    alignment_snapshot.get("law_compliance")
                    if isinstance(alignment_snapshot.get("law_compliance"), dict)
                    else {}
                )
                ca = (
                    alignment_snapshot.get("ceo_action_required")
                    if isinstance(alignment_snapshot.get("ceo_action_required"), dict)
                    else {}
                )
                a_meta = {
                    "alignment_version": alignment_snapshot.get("snapshot_version"),
                    "alignment_confidence": alignment_snapshot.get("confidence_level"),
                    "alignment_overall_status": sa.get("overall_status"),
                    "alignment_score": sa.get("alignment_score"),
                    "law_system_integrity": lc.get("system_integrity"),
                    "law_risk_level": lc.get("risk_level"),
                    "alignment_requires_action": ca.get("requires_action"),
                }

            return {
                "summary": summary,
                "text": text_out,
                "questions": [],
                "plan": [],
                "options": [],
                "proposed_commands": [],
                "trace": {
                    "assistant_id": assistant_id,
                    "thread_id": getattr(thread, "id", None),
                    "run_id": getattr(run, "id", None) if run else None,
                    "read_only_guard": True,
                    "no_tools_guard": True,
                    "error_type": err_type,
                    "error_message": err_msg,
                    "error_repr": err_repr,
                    "elapsed_ms": elapsed_ms,
                    "shrink_trace": shrink_trace,
                    "dashboard_contract_enforced": bool(enforce_dashboard_text),
                    "identity_pack_available": bool(identity_pack_available),
                    "identity_pack_errors_count": int(identity_pack_errors_count),
                    "identity_pack_injected": bool("identity_pack" in safe_context),
                    "alignment_injected": bool("alignment_snapshot" in safe_context),
                    **a_meta,
                    "behaviour_router_available": bool(behaviour_router_available),
                    "behaviour_mode": behaviour_mode,
                    "behaviour_mode_source": behaviour_mode_source,
                    "behaviour_mode_applied": bool(behaviour_mode_applied),
                    "behaviour_mode_instructions_len": len(run_instructions)
                    if isinstance(run_instructions, str)
                    else None,
                },
            }

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        trace = parsed.get("trace") if isinstance(parsed.get("trace"), dict) else {}
        trace["assistant_id"] = assistant_id
        trace["thread_id"] = thread.id
        trace["run_id"] = run.id
        trace["read_only_guard"] = True
        trace["no_tools_guard"] = True
        trace["elapsed_ms"] = elapsed_ms
        trace["shrink_trace"] = shrink_trace
        trace["dashboard_contract_enforced"] = bool(enforce_dashboard_text)

        if knowledge_block:
            trace["identity_knowledge_injected"] = True

        trace["identity_pack_available"] = bool(identity_pack_available)
        trace["identity_pack_errors_count"] = int(identity_pack_errors_count)
        if "identity_pack" in safe_context:
            trace["identity_pack_injected"] = True

        if isinstance(alignment_snapshot, dict):
            sa = (
                alignment_snapshot.get("strategic_alignment")
                if isinstance(alignment_snapshot.get("strategic_alignment"), dict)
                else {}
            )
            lc = (
                alignment_snapshot.get("law_compliance")
                if isinstance(alignment_snapshot.get("law_compliance"), dict)
                else {}
            )
            ca = (
                alignment_snapshot.get("ceo_action_required")
                if isinstance(alignment_snapshot.get("ceo_action_required"), dict)
                else {}
            )

            trace["alignment_injected"] = bool("alignment_snapshot" in safe_context)
            trace["alignment_version"] = alignment_snapshot.get("snapshot_version")
            trace["alignment_confidence"] = alignment_snapshot.get("confidence_level")
            trace["alignment_overall_status"] = sa.get("overall_status")
            trace["alignment_score"] = sa.get("alignment_score")
            trace["law_system_integrity"] = lc.get("system_integrity")
            trace["law_risk_level"] = lc.get("risk_level")
            trace["alignment_requires_action"] = ca.get("requires_action")

        trace["behaviour_router_available"] = bool(behaviour_router_available)
        trace["behaviour_mode"] = behaviour_mode
        trace["behaviour_mode_source"] = behaviour_mode_source
        trace["behaviour_mode_applied"] = bool(behaviour_mode_applied)
        trace["behaviour_mode_instructions_len"] = (
            len(run_instructions) if isinstance(run_instructions, str) else None
        )
        trace["behaviour_mode_silent_runtime_enforced"] = bool(
            behaviour_mode == "silent"
        )
        trace["behaviour_mode_silent_critical_risk"] = bool(
            _is_critical_risk_from_alignment(alignment_snapshot)
            if behaviour_mode == "silent"
            else False
        )

        parsed["trace"] = trace

        picked = _pick_text(parsed)
        if (
            picked
            and isinstance(parsed.get("text"), str)
            and not parsed["text"].strip()
        ):
            parsed["text"] = picked
        if (
            picked
            and isinstance(parsed.get("summary"), str)
            and not parsed["summary"].strip()
        ):
            parsed["summary"] = picked

        return parsed
