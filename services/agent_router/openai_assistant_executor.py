# services/agent_router/openai_assistant_executor.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional

from openai import OpenAI

from ext.notion.client import perform_notion_action

logger = logging.getLogger(__name__)


class OpenAIAssistantExecutor:
    """
    OPENAI ASSISTANT EXECUTION ADAPTER — KANONSKI

    CANON:
    - Ovaj adapter se koristi za agent execution (sa tool pozivima) I za CEO advisory (READ-only).
    - CEO advisory NIKAD ne smije izvršiti tool poziv / side-effect.
      Ako Assistant zatraži tool u ceo_command, to se smatra policy violation i tretira se kao error/fallback.
    - Agent execute: ili izvrši ili baci exception (nema "failure dict").
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

        # NOTE: OpenAI client je sync; u async flow-u pozive šaljemo kroz asyncio.to_thread.
        self.client = OpenAI(api_key=api_key)

    # ============================================================
    # INTERNALS (sync OpenAI calls wrapped for async)
    # ============================================================

    async def _to_thread(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _get_execution_assistant_id_or_raise(self) -> str:
        assistant_id = os.getenv(self._execution_assistant_id_env)
        if not assistant_id:
            raise RuntimeError(f"{self._execution_assistant_id_env} is missing")
        return assistant_id

    def _get_advisory_assistant_id(self) -> Optional[str]:
        # Prefer dedicated advisory assistant, fallback to execution assistant id if present.
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
                # Best-effort cancel (ne smijemo visiti beskonačno)
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
                    # CEO advisory path: tool calls are forbidden
                    await self._cancel_run_best_effort(thread_id=thread_id, run_id=run_id)
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
                    raise RuntimeError("Assistant requires_action but has no tool calls")

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

                    # NOTE: ext.notion.client.perform_notion_action je sync.
                    result = await self._to_thread(perform_notion_action, **args)

                    tool_outputs.append(
                        {
                            "tool_call_id": call.id,
                            "output": json.dumps(result, ensure_ascii=False),
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
        assistant_messages = [m for m in data if getattr(m, "role", None) == "assistant"]

        if not assistant_messages:
            raise RuntimeError("Assistant produced no response")

        # Be deterministic: pick newest assistant message by created_at if present.
        def _created_at(msg: Any) -> int:
            ca = getattr(msg, "created_at", None)
            return int(ca) if isinstance(ca, int) else 0

        msg = max(assistant_messages, key=_created_at)

        content = getattr(msg, "content", None)
        if not content:
            raise RuntimeError("Assistant response has empty content")

        # SDK content is a list; concatenate all text chunks for robustness.
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
        """
        Assistants sometimes wrap JSON in ```json ... ``` fences.
        We strip one outer fence layer if present.
        """
        t = (text or "").strip()
        if not t:
            return t

        # Match ```json\n...\n``` OR ```\n...\n```
        m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, flags=re.DOTALL | re.IGNORECASE)
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

    def _normalize_ceo_advisory_payload(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hardening layer for CEO advisory:
        - If assistant returns plain text (or non-schema JSON), map it into the expected schema.
        - Always return: summary/questions/plan/options/proposed_commands/trace as stable types.
        """
        raw = parsed.get("raw")

        # 1) Plain text -> summary
        if isinstance(raw, str) and raw.strip():
            parsed = {
                "summary": raw.strip(),
                "questions": [],
                "plan": [],
                "options": [],
                "proposed_commands": [],
                "trace": {"llm": "raw_text_mapped"},
            }

        # 2) Ensure summary exists
        if "summary" not in parsed:
            if raw is not None:
                parsed["summary"] = str(raw)
            else:
                parsed["summary"] = (
                    "LLM odgovor nije imao 'summary' polje (fallback normalization)."
                )

        # 3) Stabilize list fields
        if not isinstance(parsed.get("questions"), list):
            parsed["questions"] = []
        if not isinstance(parsed.get("plan"), list):
            parsed["plan"] = []
        if not isinstance(parsed.get("options"), list):
            parsed["options"] = []
        if not isinstance(parsed.get("proposed_commands"), list):
            parsed["proposed_commands"] = []

        # 4) Ensure trace dict
        if not isinstance(parsed.get("trace"), dict):
            parsed["trace"] = {}

        # 5) Ensure list elements are strings (defensive)
        parsed["questions"] = [x for x in parsed["questions"] if isinstance(x, str)]
        parsed["plan"] = [x for x in parsed["plan"] if isinstance(x, str)]
        parsed["options"] = [x for x in parsed["options"] if isinstance(x, str)]

        return parsed

    # ============================================================
    # EXECUTION (WRITE PATH) — used by orchestrator/agent layer
    # ============================================================

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        EXECUTION PATH (side-effects allowed, tool calls allowed).
        Expected task:
          {
            "command": "<string>",
            "payload": { ... }
          }
        """
        if not isinstance(task, dict):
            raise ValueError("Agent task must be a dict")

        command = task.get("command")
        payload = task.get("payload")

        if not isinstance(command, str) or not command.strip():
            raise ValueError("Agent task requires 'command' (str)")
        if not isinstance(payload, dict):
            raise ValueError("Agent task requires 'payload' (dict)")

        assistant_id = self._get_execution_assistant_id_or_raise()

        thread = await self._to_thread(self.client.beta.threads.create)

        execution_contract = {
            "type": "agent_execution",
            "command": command.strip(),
            "payload": payload,
        }

        await self._to_thread(
            self.client.beta.threads.messages.create,
            thread_id=thread.id,
            role="user",
            content=json.dumps(execution_contract, ensure_ascii=False),
        )

        run = await self._to_thread(
            self.client.beta.threads.runs.create,
            thread_id=thread.id,
            assistant_id=assistant_id,
        )

        await self._wait_for_run_completion(
            thread_id=thread.id,
            run_id=run.id,
            allow_tools=True,
        )

        final_text = await self._get_final_assistant_message_text(thread_id=thread.id)
        parsed = self._safe_json_parse(final_text)

        return {
            "agent": assistant_id,
            "result": parsed,
            "trace": {"thread_id": thread.id, "run_id": run.id},
        }

    # ============================================================
    # CEO ADVISORY (READ-ONLY) — used by CEO Console
    # ============================================================

    async def ceo_command(self, *, text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        READ-ONLY advisory path.
        - No tools / no side-effects.
        - If assistant requests_action (tool call), we fail fast (policy violation).

        Expected return shape (dict):
          {
            "summary": str,
            "questions": [str],
            "plan": [str],
            "options": [str],
            "proposed_commands": [ ... optional ... ],
            "trace": { ... }
          }
        """
        t = (text or "").strip()
        if not t:
            raise ValueError("text is required")

        if not isinstance(context, dict):
            context = {}

        assistant_id = self._get_advisory_assistant_id()
        if not assistant_id:
            # If no assistant id exists at all, return deterministic fallback instead of raising.
            return {
                "summary": "LLM executor nije konfigurisan (nema Assistant ID).",
                "questions": [
                    "Postavi Assistant ID (CEO_ADVISOR_ASSISTANT_ID ili NOTION_OPS_ASSISTANT_ID)."
                ],
                "plan": ["Konfiguriši LLM executor i ponovi CEO Command."],
                "options": [],
                "proposed_commands": [],
                "trace": {"llm": "not_configured"},
            }

        thread = await self._to_thread(self.client.beta.threads.create)

        # Force canon constraints into contract, regardless of caller input
        safe_context = dict(context)
        canon = dict(safe_context.get("canon") or {})
        canon["read_only"] = True
        canon["no_tools"] = True
        canon["no_side_effects"] = True
        safe_context["canon"] = canon

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
                "questions": "list[string]",
                "plan": "list[string]",
                "options": "list[string]",
                "proposed_commands": "list[object]",
                "trace": "object",
            },
        }

        await self._to_thread(
            self.client.beta.threads.messages.create,
            thread_id=thread.id,
            role="user",
            content=json.dumps(advisory_contract, ensure_ascii=False),
        )

        run = await self._to_thread(
            self.client.beta.threads.runs.create,
            thread_id=thread.id,
            assistant_id=assistant_id,
        )

        t0 = time.monotonic()
        await self._wait_for_run_completion(
            thread_id=thread.id,
            run_id=run.id,
            allow_tools=False,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        final_text = await self._get_final_assistant_message_text(thread_id=thread.id)
        parsed = self._safe_json_parse(final_text)

        # Normalize plain text / non-schema to expected schema
        parsed = self._normalize_ceo_advisory_payload(parsed)

        # Ensure minimum stable fields + trace guard
        trace = parsed.get("trace") if isinstance(parsed.get("trace"), dict) else {}
        trace["assistant_id"] = assistant_id
        trace["thread_id"] = thread.id
        trace["run_id"] = run.id
        trace["read_only_guard"] = True
        trace["no_tools_guard"] = True
        trace["elapsed_ms"] = elapsed_ms
        parsed["trace"] = trace

        return parsed
