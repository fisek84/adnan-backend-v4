from __future__ import annotations

import pytest

from services.agent_router.openai_responses_executor import OpenAIResponsesExecutor


def test_responses_executor_ceo_command_requires_instructions():
    ex = OpenAIResponsesExecutor(client=object())

    with pytest.raises(ValueError, match="missing ctx\.instructions"):
        # No instructions in ctx
        import asyncio

        asyncio.run(ex.ceo_command(text="hi", context={}))
