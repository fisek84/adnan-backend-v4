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

    def _extract_chat_text(self, resp: Any) -> str:
        # Chat Completions style: resp.choices[0].message.content
        choices = getattr(resp, "choices", None) or []
        if not choices:
            raise ExecutorOutputError("Chat Completions returned no choices")
        msg = getattr(choices[0], "message", None)
        if msg is None:
            raise ExecutorOutputError("Chat Completions returned no message")

        # Block tool calls if the SDK supports them.
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            raise ExecutorToolCallAttempt(
                "Chat Completions output contained tool calls"
            )

        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        raise ExecutorOutputError("Chat Completions returned empty content")

    def _parse_json(
        self, text: str, *, force_text_contract: bool = False
    ) -> Dict[str, Any]:
        cleaned = _strip_code_fences(text)
        try:
            obj = json.loads(cleaned)
        except Exception:
            # Fail-soft: output might be plain text.
            return {"text": cleaned}

        if not force_text_contract:
            if isinstance(obj, dict):
                return obj
            return {"raw": obj}

        # CEO advisor contract normalization.
        if isinstance(obj, dict):
            v = obj.get("text")
            if isinstance(v, str) and v.strip():
                return obj

            # If dict has exactly one non-empty string value (e.g. {"answer": "Pariz"}),
            # map it into the contract.
            if len(obj) == 1:
                only_val = next(iter(obj.values()))
                if isinstance(only_val, str) and only_val.strip():
                    return {"text": only_val.strip()}

            return {"text": cleaned}

        return {"text": cleaned}

    async def ceo_command(
        self, text: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Compatibility wrapper (CEO advisor expects executor.ceo_command).
        Delegates to `execute()` which uses Responses API with strict JSON output.
        """
        ctx = context if isinstance(context, dict) else {}

        schema_hint = 'Vrati TAČNO JSON oblika {"text":"..."} (samo taj ključ), bez drugih ključeva.'

        task: Dict[str, Any] = {
            "input": f"{schema_hint}\n\n{text}",
            # Optional knobs (best-effort) — safe even if caller doesn't provide them.
            "instructions": ctx.get("instructions"),
            "temperature": ctx.get("temperature"),
            "allow_tools": bool(ctx.get("allow_tools") is True),
            "ceo_contract": True,
        }
        return await self.execute(task)

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

        # Prefer Responses API when available; fall back to Chat Completions for
        # older SDKs/environments (pre-responses).
        has_responses = bool(
            getattr(self.client, "responses", None)
            and hasattr(getattr(self.client, "responses", None), "create")
        )

        if has_responses:
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
            return self._parse_json(
                text, force_text_contract=bool(task.get("ceo_contract") is True)
            )

        # Fallback: Chat Completions.
        # NOTE: We keep the same JSON-only request and still block tool calls.
        chat = getattr(self.client, "chat", None)
        completions = getattr(chat, "completions", None) if chat is not None else None
        create = (
            getattr(completions, "create", None) if completions is not None else None
        )
        if not callable(create):
            raise ExecutorOutputError(
                "OpenAI client does not support responses.create or chat.completions.create"
            )

        msgs = []
        # OpenAI requires the word 'json' to appear in messages when using
        # response_format={type: json_object}.
        json_rule = "Return only valid json (a single JSON object)."
        if instructions:
            msgs.append(
                {
                    "role": "system",
                    "content": f"{instructions}\n\n{json_rule}",
                }
            )
        else:
            msgs.append({"role": "system", "content": json_rule})
        msgs.append({"role": "user", "content": user_input})

        ck: Dict[str, Any] = {
            "model": self._model(),
            "messages": msgs,
            "response_format": {"type": "json_object"},
        }
        if task.get("temperature") is not None:
            ck["temperature"] = task.get("temperature")

        resp = await __import__("asyncio").to_thread(create, **ck)
        text = self._extract_chat_text(resp)
        return self._parse_json(
            text, force_text_contract=bool(task.get("ceo_contract") is True)
        )
