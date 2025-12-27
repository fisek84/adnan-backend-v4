# services/agent_router/openai_assistant_executor.py
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

from ext.notion.client import perform_notion_action
from services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)

# OpenAI Assistants API hard limit: 256000 chars
# Keep a safety margin for envelopes / minor growth.
_MAX_OPENAI_CONTENT_CHARS = 240000

# Defensive trimming limits for snapshot compaction
_MAX_LIST_ITEMS = 30
_MAX_TEXT_CHARS = 1200


# -------------------------------------------------------------------
# CEO ADVISORY OUTPUT CONTRACT (KANONSKI / STABILAN) - DASHBOARD MODE
# -------------------------------------------------------------------
_CEO_ADVISORY_RUN_INSTRUCTIONS = """You are the CEO Advisor in a READ-ONLY mode.

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

Text formatting rules:
- text MUST start with the line: GOALS (top 3)
- text MUST include both sections: GOALS (top 3) and TASKS (top 5)
- Each item line MUST follow: <name/title> | <status> | <priority>
- Do NOT include any other prose outside these sections in text.
- Do NOT embed JSON in the 'text' field.

If there are fewer than 3 goals or 5 tasks in the snapshot, list what exists and add a line:
NEMA DOVOLJNO PODATAKA U SNAPSHOT-U
"""


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

    If enforce_dashboard_text=True:
      - try to extract/force GOALS/TASKS block into 'text' when possible
      - set trace['format_fallback']=True when we couldn't produce block
    Else:
      - do NOT force GOALS/TASKS; keep assistant's normal text/summary
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

    return parsed


def _is_dashboard_query(user_text: str) -> bool:
    """
    Lightweight heuristic: only enforce GOALS/TASKS contract for dashboard/listing queries.
    """
    t = (user_text or "").lower()
    if not t:
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
        "najvažn",
        "najhitnij",
        "snapshot",
        "status",
        "prioritet",
        "priority",
    ]

    return any(k in t for k in keywords)


class OpenAIAssistantExecutor:
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
                if not allow_tools:
                    await self._cancel_run_best_effort(
                        thread_id=thread_id, run_id=run_id
                    )
                    raise RuntimeError(
                        "Tool calls are not allowed for CEO advisory (read-only)"
                    )

                required_action = getattr(run_status, "required_action", None)
                submit = (
                    getattr(required_action, "submit_tool_outputs", None)
                    if required_action
                    else None
                )
                tool_calls = getattr(submit, "tool_calls", None) if submit else None

                if not tool_calls:
                    raise RuntimeError(
                        "Assistant requires_action but has no tool calls"
                    )

                tool_outputs = []
                for call in tool_calls:
                    fn = getattr(call, "function", None)
                    fn_name = getattr(fn, "name", None) if fn else None
                    fn_args = getattr(fn, "arguments", None) if fn else None

                    if fn_name != "perform_notion_action":
                        raise RuntimeError(f"Unsupported tool call: {fn_name}")

                    try:
                        args = json.loads(fn_args or "{}")
                    except Exception as e:
                        raise RuntimeError(f"Invalid tool arguments JSON: {e}") from e

                    if not isinstance(args, dict):
                        raise RuntimeError("Tool arguments must be a JSON object")

                    result = await self._to_thread(perform_notion_action, **args)

                    tool_outputs.append(
                        {
                            "tool_call_id": call.id,
                            "output": json.dumps(
                                result, ensure_ascii=False, default=_json_default
                            ),
                        }
                    )

                await self._to_thread(
                    self.client.beta.threads.runs.submit_tool_outputs,
                    thread_id=thread_id,
                    run_id=run_id,
                    tool_outputs=tool_outputs,
                )

            elif status == "completed":
                return

            elif status in {"failed", "cancelled", "expired"}:
                raise RuntimeError(f"Assistant run failed with status: {status}")

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

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task, dict):
            raise ValueError("Agent task must be a dict")

        command = task.get("command")
        payload = task.get("payload")

        if not isinstance(command, str) or not command.strip():
            raise ValueError("Agent task requires 'command' (str)")
        if not isinstance(payload, dict):
            raise ValueError("Agent task requires 'payload' (dict)")

        executor = task.get("executor") or task.get("agent") or task.get("role")
        if executor and str(executor).lower() in {"ceo_advisor", "ceo", "advisor"}:
            raise RuntimeError(
                "CEO advisory cannot run execute() (side-effects forbidden)"
            )

        assistant_id = self._get_execution_assistant_id_or_raise()
        thread = await self._to_thread(self.client.beta.threads.create)

        execution_contract = {
            "type": "agent_execution",
            "command": command.strip(),
            "payload": payload,
        }
        content, shrink_trace = _safe_dumps_for_openai(execution_contract)

        await self._to_thread(
            self.client.beta.threads.messages.create,
            thread_id=thread.id,
            role="user",
            content=content,
        )

        run = await self._to_thread(
            self.client.beta.threads.runs.create,
            thread_id=thread.id,
            assistant_id=assistant_id,
        )

        await self._wait_for_run_completion(
            thread_id=thread.id, run_id=run.id, allow_tools=True
        )

        final_text = await self._get_final_assistant_message_text(thread_id=thread.id)
        parsed = self._safe_json_parse(final_text)

        return {
            "agent": assistant_id,
            "result": parsed,
            "trace": {
                "thread_id": thread.id,
                "run_id": run.id,
                "shrink_trace": shrink_trace,
            },
        }

    async def ceo_command(
        self, *, text: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        t = (text or "").strip()
        if not t:
            raise ValueError("text is required")
        if not isinstance(context, dict):
            context = {}

        assistant_id = self._get_advisory_assistant_id()
        if not assistant_id:
            return {
                "summary": "LLM executor nije konfigurisan (nema Assistant ID).",
                "text": "LLM executor nije konfigurisan (nema Assistant ID).",
                "questions": [
                    "Postavi Assistant ID (CEO_ADVISOR_ASSISTANT_ID ili NOTION_OPS_ASSISTANT_ID)."
                ],
                "plan": ["Konfiguriši LLM executor i ponovi CEO Command."],
                "options": [],
                "proposed_commands": [],
                "trace": {"llm": "not_configured"},
            }

        enforce_dashboard_text = _is_dashboard_query(t)

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

        # IMPORTANT:
        # - We keep read-only/no-tools in the contract payload always.
        # - But we ONLY enforce GOALS/TASKS formatting (instructions) for dashboard/listing queries.
        run_instructions = (
            _CEO_ADVISORY_RUN_INSTRUCTIONS if enforce_dashboard_text else None
        )

        run = await self._to_thread(
            self.client.beta.threads.runs.create,
            thread_id=thread.id,
            assistant_id=assistant_id,
            instructions=run_instructions,
        )

        t0 = time.monotonic()
        try:
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
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return {
                "summary": "CEO advisory nije mogao sigurno završiti (read-only guard).",
                "text": "CEO advisory nije mogao sigurno završiti (read-only guard).",
                "questions": [
                    "Da li želiš da preformulišem upit kao čisti READ zahtjev bez tool poziva?"
                ],
                "plan": [
                    "Provjeri da li CEO Advisor Assistant ima instrukcije da nikad ne traži tool pozive.",
                    "Ako je upit write-intent, koristi approval pipeline (proposed_commands) umjesto direktnog izvršenja.",
                ],
                "options": [],
                "proposed_commands": [],
                "trace": {
                    "assistant_id": assistant_id,
                    "thread_id": getattr(thread, "id", None),
                    "run_id": getattr(run, "id", None),
                    "read_only_guard": True,
                    "no_tools_guard": True,
                    "error": repr(exc),
                    "elapsed_ms": elapsed_ms,
                    "shrink_trace": shrink_trace,
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
        parsed["trace"] = trace

        # Hard guarantee: always return 'text' and 'summary'
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
