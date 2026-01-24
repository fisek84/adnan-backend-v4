from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from openai import OpenAI

from services.agent_router.executor_errors import (
    ExecutorOutputError,
    ExecutorToolCallAttempt,
)


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


def _looks_like_tool_output_item(item: Any) -> bool:
    # Responses API emits structured tool/function call items.
    t = getattr(item, "type", None)
    if isinstance(t, str) and t:
        tl = t.lower()
        if tl in {"function_call", "tool_call"}:
            return True
        if tl.endswith("_call"):
            return True
    return False


class OpenAIResponsesExecutor:
    """OpenAI Responses API executor with strict JSON-only output."""

    def __init__(
        self,
        *,
        model_env: str = "OPENAI_RESPONSES_MODEL",
        default_model: str = "gpt-4.1-mini",
        client: Optional[Any] = None,
    ) -> None:
        self._model_env = model_env
        self._default_model = default_model

        if client is not None:
            self.client = client
            return

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing")
        self.client = OpenAI(api_key=api_key)

    def _model(self) -> str:
        m = (os.getenv(self._model_env) or "").strip()
        return m or self._default_model

    def _extract_output_text(self, resp: Any) -> str:
        out_text = getattr(resp, "output_text", None)
        if isinstance(out_text, str) and out_text.strip():
            return out_text.strip()

        # Fallback: concatenate output text-like chunks
        output = getattr(resp, "output", None) or []
        chunks: list[str] = []
        for item in output:
            if _looks_like_tool_output_item(item):
                continue
            content = getattr(item, "content", None)
            if isinstance(content, list):
                for part in content:
                    ptype = getattr(part, "type", None)
                    if ptype == "output_text":
                        text = getattr(part, "text", None)
                        if isinstance(text, str) and text.strip():
                            chunks.append(text)
        joined = "\n".join(chunks).strip()
        if joined:
            return joined

        raise ExecutorOutputError("Responses API returned no output_text")

    def _parse_json(self, text: str) -> Dict[str, Any]:
        cleaned = _strip_code_fences(text)
        try:
            obj = json.loads(cleaned)
        except Exception as e:  # noqa: BLE001
            raise ExecutorOutputError(f"Invalid JSON from model: {e}") from e
        if isinstance(obj, dict):
            return obj
        return {"raw": obj}

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a JSON-only request.

        Expected task keys (minimal):
        - input: str (user content)
        - instructions: str | None
        - temperature: number | None

        Optional:
        - allow_tools: bool (default False)
        """
        if not isinstance(task, dict):
            raise ValueError("task must be a dict")

        user_input = task.get("input")
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("task.input must be a non-empty string")

        instructions = task.get("instructions")
        if instructions is not None and not isinstance(instructions, str):
            instructions = str(instructions)

        allow_tools = bool(task.get("allow_tools") is True)
        if allow_tools:
            raise ExecutorToolCallAttempt("Tools are not allowed in this executor")

        kwargs: Dict[str, Any] = {
            "model": self._model(),
            "input": user_input,
            # Strict JSON-only output.
            "text": {"format": {"type": "json_object"}},
        }

        if instructions:
            kwargs["instructions"] = instructions

        # Temperature is accepted by responses.create in this SDK.
        if task.get("temperature") is not None:
            kwargs["temperature"] = task.get("temperature")

        # Best-effort: disallow tools explicitly when supported.
        kwargs["tool_choice"] = "none"
        kwargs["tools"] = []

        resp = await __import__("asyncio").to_thread(
            self.client.responses.create, **kwargs
        )

        # Reject any tool/function call output items.
        output = getattr(resp, "output", None) or []
        for item in output:
            if _looks_like_tool_output_item(item):
                raise ExecutorToolCallAttempt(
                    "Responses output contained a tool/function call"
                )

        text = self._extract_output_text(resp)
        return self._parse_json(text)
