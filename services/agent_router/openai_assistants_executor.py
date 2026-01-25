from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Dict, Optional

from openai import OpenAI

from services.agent_router.executor_errors import (
    ExecutorOutputError,
    ExecutorTimeout,
    ExecutorToolCallAttempt,
)
from services.agent_router.openai_key_diag import get_openai_key_diag


_CODE_FENCE_RE = re.compile(
    r"^```(?:json)?\s*(.*?)\s*```$", flags=re.DOTALL | re.IGNORECASE
)


def _strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    m = _CODE_FENCE_RE.match(t)
    if m:
        return (m.group(1) or "").strip()
    return t


class OpenAIAssistantsExecutor:
    """Assistants API executor wrapper (threads/runs/messages)."""

    def __init__(
        self,
        *,
        poll_interval_s: float = 0.3,
        max_wait_s: float = 60.0,
        client: Optional[Any] = None,
    ) -> None:
        self._poll_interval_s = float(poll_interval_s)
        self._max_wait_s = float(max_wait_s)

        if client is not None:
            self.client = client
            return

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing")
        self.client = OpenAI(api_key=api_key)

        d = get_openai_key_diag()
        logger = __import__("logging").getLogger(__name__)
        logger.info(
            "[OPENAI_KEY_DIAG] present=%s len=%s prefix=%s fp=%s source=%s mode=%s base_url=%s",
            d.get("present"),
            d.get("len"),
            d.get("prefix"),
            d.get("fingerprint"),
            d.get("source"),
            d.get("mode"),
            d.get("base_url"),
        )

    async def _to_thread(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _wait_for_completion(self, *, thread_id: str, run_id: str) -> None:
        start = time.monotonic()
        while True:
            if time.monotonic() - start > self._max_wait_s:
                raise ExecutorTimeout("run timed out")

            run_status = await self._to_thread(
                self.client.beta.threads.runs.retrieve,
                thread_id=thread_id,
                run_id=run_id,
            )
            status = getattr(run_status, "status", None)

            if status == "requires_action":
                raise ExecutorToolCallAttempt(
                    "run attempted tool calls (requires_action)"
                )

            if status == "completed":
                return

            if status in {"failed", "cancelled", "expired"}:
                raise ExecutorOutputError(f"run failed: status={status}")

            await asyncio.sleep(self._poll_interval_s)

    def _parse_json(self, text: str) -> Dict[str, Any]:
        cleaned = _strip_code_fences(text)
        try:
            obj = json.loads(cleaned)
        except Exception as e:  # noqa: BLE001
            raise ExecutorOutputError(f"invalid_json: {e}") from e
        if isinstance(obj, dict):
            return obj
        return {"raw": obj}

    async def _get_latest_assistant_text_json(
        self, *, thread_id: str, limit: int = 10
    ) -> Dict[str, Any]:
        messages = await self._to_thread(
            self.client.beta.threads.messages.list, thread_id=thread_id, limit=limit
        )
        data = getattr(messages, "data", None) or []
        assistant_msgs = [m for m in data if getattr(m, "role", None) == "assistant"]
        if not assistant_msgs:
            raise ExecutorOutputError("no_assistant_message")

        def _created_at(m: Any) -> int:
            ca = getattr(m, "created_at", None)
            return int(ca) if isinstance(ca, int) else 0

        msg = max(assistant_msgs, key=_created_at)
        content = getattr(msg, "content", None)
        if not content:
            raise ExecutorOutputError("empty_assistant_content")

        chunks: list[str] = []
        for part in content:
            text_obj = getattr(part, "text", None)
            value = getattr(text_obj, "value", None) if text_obj else None
            if isinstance(value, str) and value.strip():
                chunks.append(value)
        joined = "\n".join(chunks).strip()
        if not joined:
            raise ExecutorOutputError("empty_assistant_text")

        return self._parse_json(joined)

    async def _get_first_output_json(
        self, *, thread_id: str, limit: int = 1
    ) -> Dict[str, Any]:
        messages = await self._to_thread(
            self.client.beta.threads.messages.list, thread_id=thread_id, limit=limit
        )
        data = getattr(messages, "data", None) or []
        if not data:
            raise ExecutorOutputError("no_messages")

        msg0 = data[0]
        content = getattr(msg0, "content", None)
        if not content:
            raise ExecutorOutputError("empty_message_content")

        block0 = content[0]

        # Handle dict-like blocks and object-like blocks
        btype = getattr(block0, "type", None)
        if btype is None and isinstance(block0, dict):
            btype = block0.get("type")

        if btype != "output_json":
            raise ExecutorOutputError("invalid_agent_response")

        if isinstance(block0, dict):
            js = block0.get("json")
        else:
            js = getattr(block0, "json", None)

        if not isinstance(js, dict):
            raise ExecutorOutputError("output_json_missing_dict")

        return js

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an Assistants API run expecting JSON output.

        Required task keys:
        - assistant_id: str
        - content: str|dict

        Optional:
        - instructions: str
        - temperature: number
        - response_format: dict (passed to runs.create)
        - parse_mode: 'text_json'|'output_json'
        - limit: int (messages.list)
        """
        assistant_id = task.get("assistant_id")
        if not isinstance(assistant_id, str) or not assistant_id.strip():
            raise ValueError("assistant_id is required")

        content = task.get("content")
        if content is None:
            raise ValueError("content is required")

        thread = await self._to_thread(self.client.beta.threads.create)

        await self._to_thread(
            self.client.beta.threads.messages.create,
            thread_id=thread.id,
            role="user",
            content=content,
        )

        run_kwargs: Dict[str, Any] = {
            "thread_id": thread.id,
            "assistant_id": assistant_id,
        }
        if task.get("instructions") is not None:
            run_kwargs["instructions"] = task.get("instructions")
        if task.get("temperature") is not None:
            run_kwargs["temperature"] = task.get("temperature")
        if task.get("response_format") is not None:
            run_kwargs["response_format"] = task.get("response_format")

        try:
            run = await self._to_thread(
                self.client.beta.threads.runs.create, **run_kwargs
            )
        except TypeError:
            # Compatibility fallback
            run = await self._to_thread(
                self.client.beta.threads.runs.create,
                thread_id=thread.id,
                assistant_id=assistant_id,
            )

        await self._wait_for_completion(thread_id=thread.id, run_id=run.id)

        parse_mode = task.get("parse_mode") or "text_json"
        limit = int(task.get("limit") or 10)

        if parse_mode == "output_json":
            return await self._get_first_output_json(thread_id=thread.id, limit=limit)

        return await self._get_latest_assistant_text_json(
            thread_id=thread.id, limit=limit
        )
