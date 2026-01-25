from services.agent_router.openai_responses_executor import OpenAIResponsesExecutor


class _Msg:
    def __init__(self, content: str):
        self.content = content
        self.tool_calls = None


class _Choice:
    def __init__(self, content: str):
        self.message = _Msg(content)


class _ChatResp:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, content: str):
        self._content = content
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _ChatResp(self._content)


class _Chat:
    def __init__(self, content: str):
        self.completions = _Completions(content)


class _ClientNoResponses:
    def __init__(self, content: str):
        self.chat = _Chat(content)
        self.responses = None


def test_executor_falls_back_to_chat_completions_when_no_responses_api():
    client = _ClientNoResponses('{"text": "Pariz"}')
    ex = OpenAIResponsesExecutor(client=client)

    out = __import__("asyncio").run(ex.execute({"input": "Q"}))
    assert out == {"text": "Pariz"}

    # OpenAI requires 'json' keyword to be present in messages when using
    # response_format={type: json_object}.
    msgs = client.chat.completions.last_kwargs.get("messages")
    assert isinstance(msgs, list) and msgs
    joined = "\n".join(
        str(m.get("content") or "") for m in msgs if isinstance(m, dict)
    ).lower()
    assert "json" in joined
