from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi.testclient import TestClient

# Ensure repo root is importable when running as a script from tools/.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _offline_stub_contract(*, objective: str) -> Dict[str, Any]:
    return {
        "agent": "revenue_growth_operator",
        "task_id": None,
        "objective": objective,
        "context_ref": {
            "lead_id": None,
            "account_id": None,
            "meeting_id": None,
            "campaign_id": None,
        },
        "work_done": [
            {
                "type": "email_draft",
                "title": "Follow-up email draft",
                "content": "Hello — following up on our last conversation...",
                "meta": {"offline_stub": True},
            }
        ],
        "next_steps": [
            {"action": "Confirm target persona", "owner": "ceo_advisor", "due": None}
        ],
        "recommendations_to_ceo": [
            {
                "decision_needed": True,
                "decision": "Which offer angle should we lead with?",
                "options": ["ROI", "speed", "risk-reduction"],
                "recommended_option": "ROI",
                "rationale": "Most universal for cold outreach.",
            }
        ],
        "requests_from_ceo": [],
        "notion_ops_proposal": [],
    }


def _install_offline_stubs(*, mode: str) -> None:
    """Avoid real OpenAI calls while keeping routing/runtime path intact."""

    import services.revenue_growth_operator_agent as rgo
    import services.agent_router.executor_factory as exec_factory

    if mode == "assistants":
        expected = (os.getenv("REVENUE_GROWTH_OPERATOR_ASSISTANT_ID") or "").strip()
        if not expected:
            # Keep offline smoke zero-config.
            expected = "asst_smoke_revenue_growth_operator"
            os.environ["REVENUE_GROWTH_OPERATOR_ASSISTANT_ID"] = expected

        class _DummyExecutor:
            async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
                assert task.get("assistant_id") == expected
                assert task.get("allow_tools") is False
                return _offline_stub_contract(objective=str(task.get("input") or ""))

        # Patch both the agent-local reference and the shared factory.
        rgo.get_executor = lambda purpose: _DummyExecutor()  # type: ignore[assignment]
        exec_factory.get_executor = lambda purpose="agent_router": _DummyExecutor()  # type: ignore[assignment]

    elif mode == "responses":
        # Keep offline smoke zero-config.
        os.environ.setdefault("REVENUE_GROWTH_OPERATOR_MODEL", "gpt-smoke-model")

        import services.agent_router.openai_responses_executor as real_responses

        class _DummyResponsesExecutor:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
                assert task.get("allow_tools") is False
                return _offline_stub_contract(objective=str(task.get("input") or ""))

        # Patch both the agent-local reference and the shared executor module.
        rgo.OpenAIResponsesExecutor = _DummyResponsesExecutor  # type: ignore[assignment]
        real_responses.OpenAIResponsesExecutor = _DummyResponsesExecutor  # type: ignore[assignment]

    else:
        raise ValueError(f"Unsupported OPENAI_API_MODE: {mode}")


def _assert_safe_output(*, response_json: Dict[str, Any]) -> None:
    # No ProposedCommands from this worker.
    pcs = response_json.get("proposed_commands")
    assert isinstance(pcs, list)
    assert pcs == []

    txt = response_json.get("text")
    assert isinstance(txt, str) and txt.strip()

    # Parse check.
    parsed = json.loads(txt)
    assert isinstance(parsed, dict)
    assert parsed.get("agent") == "revenue_growth_operator"

    # Guard against write markers.
    lowered = txt.lower()
    forbidden = ("proposedcommand", "notion_write", "dispatch", "tool_call")
    assert not any(
        f in lowered for f in forbidden
    ), f"forbidden marker in output: {forbidden}"


def _run_case(client: TestClient, *, payload: Dict[str, Any], label: str) -> None:
    r = client.post("/api/adnan-ai/input", json=payload)
    r.raise_for_status()
    body = r.json()

    print("\n===", label, "===")
    print("agent_id=", body.get("agent_id"))
    print("read_only=", body.get("read_only"))
    print("raw AgentOutput.text:")
    print(body.get("text"))

    # Parse OK print.
    try:
        json.loads(body.get("text") or "")
        print("parse_ok=true")
    except Exception as e:  # noqa: BLE001
        print("parse_ok=false error=", str(e))
        raise

    _assert_safe_output(response_json=body)


def main() -> int:
    os.environ.setdefault("TESTING", "1")
    # Do not mutate NOTION_* env vars here: the gateway boot path requires them.

    live = (os.getenv("SMOKE_LIVE_OPENAI") or "").strip() == "1"

    if live:
        mode = (os.getenv("OPENAI_API_MODE") or "assistants").strip().lower()
    else:
        # Offline smoke must be deterministic and must not hit OpenAI.
        mode = (os.getenv("SMOKE_OFFLINE_MODE") or "assistants").strip().lower()
        os.environ["OPENAI_API_MODE"] = mode
        _install_offline_stubs(mode=mode)

    app = _load_app()
    client = TestClient(app)

    # 1) Explicit selection
    _run_case(
        client,
        payload={
            # Must pass COOConversationService gate (ready_for_translation) before
            # the legacy wrapper forwards to AgentRouterService.
            "text": "Pregledaj stanje sistema. Draft sales outreach followup email for a warm lead.",
            "context": {},
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
            "preferred_agent_id": "revenue_growth_operator",
        },
        label="preferred_agent_id=revenue_growth_operator",
    )

    # 2) Keyword routing
    _run_case(
        client,
        payload={
            # Include SYSTEM_QUERY phrase to pass the COO gate, while still
            # containing growth keywords for deterministic keyword routing.
            "text": "Pregledaj stanje sistema. sales outreach followup for pipeline — propose next steps",
            "context": {},
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
        },
        label="keyword_routing",
    )

    print("\nOK: revenue_growth_operator smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
