# services/ops_planner.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# Keep margin for envelopes / minor growth.
_MAX_OPENAI_CONTENT_CHARS = 220000


# -------------------------------------------------------
# Errors
# -------------------------------------------------------
class OpsPlannerError(RuntimeError):
    pass


class OpsPlannerTimeout(OpsPlannerError):
    pass


class OpsPlannerToolCallAttempt(OpsPlannerError):
    pass


class OpsPlannerInvalidPlan(OpsPlannerError):
    pass


# -------------------------------------------------------
# Contract: EXACT JSON SHAPE REQUIRED
# -------------------------------------------------------
_OPS_PLANNER_SYSTEM_PROMPT = """You are an Ops Planner for Adnan.ai CEO Console.

Context:
- There are two Notion databases in the business: Goals DB and Tasks DB.
- You MUST NOT write to Notion. You only produce a plan JSON (proposal).
- You will be given:
  - the CEO prompt text
  - a snapshot object (current state)

Hard constraints:
- NO TOOL CALLS. NO side effects.
- You MUST output ONLY a single JSON object.
- No markdown fences, no extra text, no explanations outside JSON.

Return EXACTLY this JSON shape (no extra keys):

{
  "goal": {
    "name": string,
    "status": string | null,
    "level": string | null,
    "priority": string | null,
    "deadline": string | null,   // ISO "YYYY-MM-DD"
    "assigned_to": string | null
  },
  "task": {
    "create": boolean,
    "name": string | null,
    "status": string | null,
    "assigned_to": string | null,
    "link_to_goal": boolean
  }
}

Extraction rules:
- Infer a reasonable goal.name from the CEO prompt; do not invent unrelated goals.
- If the CEO prompt clearly requests a task, set task.create=true and fill task fields.
- If the CEO prompt does not request a task, set task.create=false and set task.name/status/assigned_to to null.
- deadline MUST be either null or ISO YYYY-MM-DD (never "tomorrow", never dd.mm.yyyy).
- If information is missing, use null (except task.create/link_to_goal which must be boolean).
"""


def _strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return (m.group(1) or "").strip()
    return t


def _safe_dumps(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw) <= _MAX_OPENAI_CONTENT_CHARS:
        return raw
    return raw[: _MAX_OPENAI_CONTENT_CHARS - 20] + "...(hard_trim)"


def _json_parse_or_raise(text: str) -> Dict[str, Any]:
    cleaned = _strip_code_fences(text)
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise OpsPlannerInvalidPlan(f"LLM returned invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise OpsPlannerInvalidPlan("LLM returned JSON but not an object.")
    return obj


def _is_iso_date(s: str) -> bool:
    # Minimal ISO YYYY-MM-DD check; strict enough for contract.
    if not isinstance(s, str) or len(s) != 10:
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s))


def _validate_plan_or_raise(plan: Dict[str, Any]) -> Dict[str, Any]:
    expected_top = {"goal", "task"}
    if set(plan.keys()) != expected_top:
        raise OpsPlannerInvalidPlan(
            f"Top-level keys must be exactly {sorted(expected_top)}, got {sorted(plan.keys())}"
        )

    goal = plan.get("goal")
    task = plan.get("task")

    if not isinstance(goal, dict):
        raise OpsPlannerInvalidPlan("goal must be an object")
    if not isinstance(task, dict):
        raise OpsPlannerInvalidPlan("task must be an object")

    goal_keys = {"name", "status", "level", "priority", "deadline", "assigned_to"}
    task_keys = {"create", "name", "status", "assigned_to", "link_to_goal"}

    if set(goal.keys()) != goal_keys:
        raise OpsPlannerInvalidPlan(
            f"goal keys must be exactly {sorted(goal_keys)}, got {sorted(goal.keys())}"
        )
    if set(task.keys()) != task_keys:
        raise OpsPlannerInvalidPlan(
            f"task keys must be exactly {sorted(task_keys)}, got {sorted(task.keys())}"
        )

    if not isinstance(goal.get("name"), str) or not goal["name"].strip():
        raise OpsPlannerInvalidPlan("goal.name must be a non-empty string")

    # nullable strings
    for k in ("status", "level", "priority", "assigned_to"):
        v = goal.get(k)
        if v is not None and not isinstance(v, str):
            raise OpsPlannerInvalidPlan(f"goal.{k} must be string or null")

    deadline = goal.get("deadline")
    if deadline is not None:
        if not isinstance(deadline, str) or not _is_iso_date(deadline):
            raise OpsPlannerInvalidPlan("goal.deadline must be null or ISO YYYY-MM-DD")

    if not isinstance(task.get("create"), bool):
        raise OpsPlannerInvalidPlan("task.create must be boolean")
    if not isinstance(task.get("link_to_goal"), bool):
        raise OpsPlannerInvalidPlan("task.link_to_goal must be boolean")

    for k in ("name", "status", "assigned_to"):
        v = task.get(k)
        if v is not None and not isinstance(v, str):
            raise OpsPlannerInvalidPlan(f"task.{k} must be string or null")

    # If create is false, enforce nulls for task fields (minimal safety)
    if task["create"] is False:
        if (
            task.get("name") is not None
            or task.get("status") is not None
            or task.get("assigned_to") is not None
        ):
            raise OpsPlannerInvalidPlan(
                "When task.create=false, task.name/status/assigned_to must be null"
            )

    return plan


class OpsPlanner:
    def __init__(
        self,
        *,
        assistant_id_env: str = "OPS_PLANNER_ASSISTANT_ID",
        fallback_assistant_id_env: str = "CEO_ADVISOR_ASSISTANT_ID",
        poll_interval_s: float = 0.5,
        max_wait_s: float = 60.0,
    ) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise OpsPlannerError("OPENAI_API_KEY is missing")

        self._assistant_id_env = assistant_id_env
        self._fallback_assistant_id_env = fallback_assistant_id_env
        self._poll_interval_s = float(poll_interval_s)
        self._max_wait_s = float(max_wait_s)

        self.client = OpenAI(api_key=api_key)

    def _get_assistant_id_or_raise(self) -> str:
        aid = os.getenv(self._assistant_id_env) or os.getenv(self._fallback_assistant_id_env)
        if not aid:
            raise OpsPlannerError(
                f"Missing assistant id: set {self._assistant_id_env} (or fallback {self._fallback_assistant_id_env})."
            )
        return aid

    async def _to_thread(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _cancel_run_best_effort(self, *, thread_id: str, run_id: str) -> None:
        try:
            await self._to_thread(
                self.client.beta.threads.runs.cancel, thread_id=thread_id, run_id=run_id
            )
        except Exception:
            return

    async def _wait_for_completion(self, *, thread_id: str, run_id: str) -> None:
        start = time.monotonic()

        while True:
            if time.monotonic() - start > self._max_wait_s:
                await self._cancel_run_best_effort(thread_id=thread_id, run_id=run_id)
                raise OpsPlannerTimeout("OpsPlanner run timed out")

            run_status = await self._to_thread(
                self.client.beta.threads.runs.retrieve,
                thread_id=thread_id,
                run_id=run_id,
            )

            status = getattr(run_status, "status", None)

            if status == "requires_action":
                # No tools allowed: hard fail
                await self._cancel_run_best_effort(thread_id=thread_id, run_id=run_id)
                raise OpsPlannerToolCallAttempt("OpsPlanner attempted tool calls (requires_action)")

            if status == "completed":
                return

            if status in {"failed", "cancelled", "expired"}:
                last_error = getattr(run_status, "last_error", None)
                code = getattr(last_error, "code", None) if last_error else None
                msg = getattr(last_error, "message", None) if last_error else None
                raise OpsPlannerError(
                    f"OpsPlanner run failed: status={status} code={code} message={msg}"
                )

            await asyncio.sleep(self._poll_interval_s)

    async def _get_final_text(self, *, thread_id: str) -> str:
        messages = await self._to_thread(self.client.beta.threads.messages.list, thread_id=thread_id)
        data = getattr(messages, "data", None) or []
        assistant_msgs = [m for m in data if getattr(m, "role", None) == "assistant"]
        if not assistant_msgs:
            raise OpsPlannerError("OpsPlanner produced no assistant message")

        def _created_at(m: Any) -> int:
            ca = getattr(m, "created_at", None)
            return int(ca) if isinstance(ca, int) else 0

        msg = max(assistant_msgs, key=_created_at)
        content = getattr(msg, "content", None)
        if not content:
            raise OpsPlannerError("OpsPlanner assistant message has empty content")

        chunks: list[str] = []
        for part in content:
            # Newer SDK: part.type == "text" and part.text.value contains text
            ptype = getattr(part, "type", None)
            if ptype == "text":
                text_obj = getattr(part, "text", None)
                value = getattr(text_obj, "value", None) if text_obj else None
                if isinstance(value, str) and value.strip():
                    chunks.append(value)

        out = "\n".join(chunks).strip()
        if not out:
            raise OpsPlannerError("OpsPlanner produced empty text")
        return out

    async def plan_ai_commands(self, prompt: str, snapshot: Any) -> Dict[str, Any]:
        p = (prompt or "").strip()
        if not p:
            raise ValueError("prompt is required")

        assistant_id = self._get_assistant_id_or_raise()

        envelope = {
            "type": "ops_planner_request",
            "prompt": p,
            "snapshot": snapshot if snapshot is not None else {},
            "constraints": {
                "read_only": True,
                "no_tools": True,
                "no_side_effects": True,
                "return_json_only": True,
                "output_schema_strict": True,
            },
        }

        thread = await self._to_thread(self.client.beta.threads.create)

        await self._to_thread(
            self.client.beta.threads.messages.create,
            thread_id=thread.id,
            role="user",
            content=_safe_dumps(envelope),
        )

        t0 = time.monotonic()

        # NOTE: do NOT set tool_choice="none" (your API rejects it).
        # We enforce no-tools by system prompt + requires_action guard.
        try:
            run = await self._to_thread(
                self.client.beta.threads.runs.create,
                thread_id=thread.id,
                assistant_id=assistant_id,
                instructions=_OPS_PLANNER_SYSTEM_PROMPT,
                response_format={"type": "json_object"},
                temperature=0,
            )
        except TypeError:
            # Compatibility fallback
            run = await self._to_thread(
                self.client.beta.threads.runs.create,
                thread_id=thread.id,
                assistant_id=assistant_id,
            )

        await self._wait_for_completion(thread_id=thread.id, run_id=run.id)

        final_text = await self._get_final_text(thread_id=thread.id)
        parsed = _json_parse_or_raise(final_text)
        parsed = _validate_plan_or_raise(parsed)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info("OpsPlanner completed in %sms (assistant_id=%s)", elapsed_ms, assistant_id)

        return parsed


# -------------------------------------------------------
# Module-level API (used by /api/chat fallback integration)
# -------------------------------------------------------
_OPS_PLANNER_SINGLETON: Optional[OpsPlanner] = None


def _get_ops_planner_best_effort() -> Optional[OpsPlanner]:
    """
    Best-effort singleton init.
    Returns None if env/config missing or init fails.
    """
    global _OPS_PLANNER_SINGLETON
    if _OPS_PLANNER_SINGLETON is not None:
        return _OPS_PLANNER_SINGLETON

    try:
        _OPS_PLANNER_SINGLETON = OpsPlanner()
        return _OPS_PLANNER_SINGLETON
    except Exception:
        logger.exception("OpsPlanner init failed (best-effort).")
        return None


async def plan_ai_commands(prompt: str, snapshot: Any) -> Optional[Dict[str, Any]]:
    """
    Best-effort wrapper:
      - returns valid plan dict on success
      - returns None on fail/exception/invalid output
    """
    planner = _get_ops_planner_best_effort()
    if planner is None:
        return None

    try:
        plan = await planner.plan_ai_commands(prompt=prompt, snapshot=snapshot)
        if isinstance(plan, dict) and "goal" in plan and "task" in plan:
            return plan
        return None
    except Exception:
        logger.exception("OpsPlanner.plan_ai_commands failed (best-effort).")
        return None


async def plan_ai_commands_strict(prompt: str, snapshot: Any) -> Dict[str, Any]:
    """
    Strict variant (raises on failure). Kept for compatibility with any code
    that expects exceptions rather than None.
    """
    planner = _get_ops_planner_best_effort()
    if planner is None:
        raise OpsPlannerError("OpsPlanner is not available (init failed)")
    return await planner.plan_ai_commands(prompt=prompt, snapshot=snapshot)


async def plan_ai_commands_safe(prompt: str, snapshot: Any) -> Optional[Dict[str, Any]]:
    """
    Backwards-compatible safe alias (returns None on failure).
    """
    return await plan_ai_commands(prompt, snapshot)
