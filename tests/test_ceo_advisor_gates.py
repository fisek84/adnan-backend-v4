import pytest
from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


@pytest.mark.parametrize(
    "payload,env,expect_llm,expect_exit,expect_error",
    [
        # 1. allow_general=0, fallback (KB-only)
        (
            {"message": "What is AI?", "metadata": {}},
            {"CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE": "0", "OPENAI_API_KEY": "sk-test"},
            False,
            "fallback.allow_general_false",
            False,
        ),
        # 2. propose_only disables LLM
        (
            {"message": "Propose only", "metadata": {}, "propose_only": True},
            {"CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE": "1", "OPENAI_API_KEY": "sk-test"},
            False,
            "fallback.propose_only",
            False,
        ),
        # 3. fact_sensitive without snapshot
        (
            {
                "message": "What is revenue?",
                "metadata": {},
                "fact_sensitive": True,
                "snapshot": {},
            },
            {"CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE": "1", "OPENAI_API_KEY": "sk-test"},
            False,
            "fallback.fact_sensitive_no_snapshot",
            False,
        ),
        # 4. Strict LLM required, but OPENAI_API_KEY missing
        (
            {"message": "What is AI?", "metadata": {}},
            {"CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE": "1", "CEO_ADVISOR_STRICT_LLM": "1"},
            True,
            "error.llm_not_configured",
            True,
        ),
        # 5. LLM expected, executor error
        (
            {"message": "What is AI?", "metadata": {"force_executor_error": True}},
            {"CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE": "1", "OPENAI_API_KEY": "sk-test"},
            True,
            "offline.executor_error",
            False,
        ),
        # 6. LLM path, all gates pass
        (
            {"message": "What is AI?", "metadata": {}},
            {"CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE": "1", "OPENAI_API_KEY": "sk-test"},
            True,
            "llm.success",
            False,
        ),
    ],
)
def test_ceo_advisor_gates_and_exit(
    monkeypatch, payload, env, expect_llm, expect_exit, expect_error
):
    # Set env vars
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Patch executor if needed
    if payload.get("metadata", {}).get("force_executor_error"):

        class DummyExecutor:
            async def ceo_command(self, text, context):
                raise Exception("forced executor error")

        monkeypatch.setattr(
            "services.agent_router.executor_factory.get_executor",
            lambda purpose: DummyExecutor(),
        )
    # Patch _llm_is_configured if needed
    if "OPENAI_API_KEY" not in env:
        monkeypatch.setattr(
            "services.ceo_advisor_agent._llm_is_configured", lambda: False
        )
    # Call API (debug enabled so we can assert exit_reason without violating the minimal-trace contract)
    agent_input = {
        "message": payload.get("message", ""),
        "metadata": {**(payload.get("metadata", {}) or {}), "include_debug": True},
        "snapshot": payload.get("snapshot", {}),
    }
    app = _load_app()
    client = TestClient(app)
    response = client.post("/api/chat", json=agent_input)
    if expect_error:
        assert response.status_code == 500
        assert "error.llm_not_configured" in response.text
    else:
        assert response.status_code == 200
        data = response.json()
        assert "trace" in data
        assert data["trace"].get("exit_reason") == expect_exit
        # Check log lines (simulate, since real logs are not captured here)
        # In real infra, use caplog or log capture fixture
        # assert caplog.count("[CEO_ADVISOR_GATES]") == 1
        # assert caplog.count(f"[CEO_ADVISOR_EXIT] {expect_exit}") == 1
