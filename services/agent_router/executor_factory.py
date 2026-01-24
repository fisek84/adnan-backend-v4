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

    if purpose == "ceo_advisor":
        # CEO advisor logic lives in OpenAIAssistantExecutor; it internally switches
        # to Responses API when OPENAI_API_MODE=responses.
        return OpenAIAssistantExecutor()

    if mode == "responses":
        return OpenAIResponsesExecutor()

    return OpenAIAssistantsExecutor()
