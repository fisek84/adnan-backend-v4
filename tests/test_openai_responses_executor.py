import asyncio

import pytest

from services.agent_router.executor_errors import ExecutorToolCallAttempt
from services.agent_router.openai_responses_executor import OpenAIResponsesExecutor


class _DummyOutputItem:
    def __init__(self, type_name: str):
        self.type = type_name


class _DummyResponse:
    def __init__(self, *, output_text: str, output=None):
        self.output_text = output_text
        self.output = output or []


class _DummyResponsesAPI:
    def __init__(self, response: _DummyResponse):
        self._response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _DummyClient:
    def __init__(self, responses_api: _DummyResponsesAPI):
        self.responses = responses_api


def test_responses_executor_calls_json_object_and_parses_dict(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    resp = _DummyResponse(output_text='{"ok": true, "value": 123}')
    responses_api = _DummyResponsesAPI(resp)
    client = _DummyClient(responses_api)

    ex = OpenAIResponsesExecutor(client=client)

    out = asyncio.run(ex.execute({"input": '{"x": 1}', "instructions": "Return JSON"}))

    assert out == {"ok": True, "value": 123}

    assert len(responses_api.calls) == 1
    call = responses_api.calls[0]

    assert call["text"]["format"]["type"] == "json_object"
    assert call["tool_choice"] == "none"
    assert call["tools"] == []


def test_responses_executor_rejects_tool_calls(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    resp = _DummyResponse(
        output_text='{"ok": true}',
        output=[_DummyOutputItem("function_call")],
    )
    responses_api = _DummyResponsesAPI(resp)
    client = _DummyClient(responses_api)

    ex = OpenAIResponsesExecutor(client=client)

    with pytest.raises(ExecutorToolCallAttempt):
        asyncio.run(ex.execute({"input": '{"x": 1}', "instructions": "Return JSON"}))
