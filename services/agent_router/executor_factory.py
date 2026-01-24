from __future__ import annotations

import os
from typing import Literal, Union

from services.agent_router.openai_assistant_executor import OpenAIAssistantExecutor
from services.agent_router.openai_assistants_executor import OpenAIAssistantsExecutor
from services.agent_router.openai_responses_executor import OpenAIResponsesExecutor

OpenAIAPIMode = Literal["assistants", "responses"]
ExecutorPurpose = Literal["agent_router", "ops_planner", "ceo_advisor"]


def _read_api_mode() -> OpenAIAPIMode:
    raw = (os.getenv("OPENAI_API_MODE") or "assistants").strip().lower()
    if raw == "responses":
        return "responses"
    return "assistants"


def get_executor(
    *, purpose: ExecutorPurpose
) -> Union[OpenAIAssistantExecutor, OpenAIAssistantsExecutor, OpenAIResponsesExecutor]:
    """Factory for OpenAI executor implementations.

    Feature flag:
    - OPENAI_API_MODE=assistants|responses
    - default: assistants
    """
    mode = _read_api_mode()

    # Deterministic test mode for CEO advisor: avoid real OpenAI calls.
    # This still exercises LLM gating + response plumbing.
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if (
        purpose == "ceo_advisor"
        and "PYTEST_CURRENT_TEST" in os.environ
        and api_key.startswith("sk-test")
    ):

        class _DummyCeoAdvisorExecutor:
            async def ceo_command(self, text, context):
                return {"text": "(test) ok", "proposed_commands": []}

        return _DummyCeoAdvisorExecutor()

    # CEO advisor should respect OPENAI_API_MODE too.
    # - If responses: use Responses executor
    # - Else: keep legacy assistant executor for CEO advisor
    if purpose == "ceo_advisor":
        if mode == "responses":
            return OpenAIResponsesExecutor()
        return OpenAIAssistantExecutor()

    if mode == "responses":
        return OpenAIResponsesExecutor()

    return OpenAIAssistantsExecutor()
