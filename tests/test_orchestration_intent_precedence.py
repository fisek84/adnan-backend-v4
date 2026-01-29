from __future__ import annotations

import asyncio
import json

from models.agent_contract import AgentInput, AgentOutput
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService


def test_classify_intent_deliverable_requires_explicit_request_verbs():
    from services.intent_precedence import classify_intent

    # Pasted content that merely mentions deliverable words must NOT trigger deliverable intent.
    pasted = (
        "DRAFT:\n\n"
        "Email sekvence:\n- Email 1: ...\n- Email 2: ...\n\n"
        "Poruke (follow-up):\n- Poruka 1 ...\n"
    )
    assert classify_intent(pasted) != "deliverable"

    # Explicit request must still trigger deliverable intent.
    explicit = "Napiši 3 follow-up poruke i 2 emaila za leadove."
    assert classify_intent(explicit) == "deliverable"


def _mk_router() -> AgentRouterService:
    reg = AgentRegistryService()
    reg.load_from_agents_json("config/agents.json", clear=True)
    return AgentRouterService(reg)


def test_deliverable_tasks_empty_routes_to_revenue_growth_operator(monkeypatch):
    """SSOT A: deliverable intent must short-circuit to revenue_growth_operator.

    Also asserts audit trace selected_by==intent_precedence_guard.
    """

    async def _fake_growth_agent(_agent_in, _ctx):  # noqa: ANN001
        payload = {
            "agent": "revenue_growth_operator",
            "task_id": "t1",
            "objective": _agent_in.message,
            "context_ref": {
                "lead_id": None,
                "account_id": None,
                "meeting_id": None,
                "campaign_id": None,
            },
            "work_done": [],
            "next_steps": [],
            "recommendations_to_ceo": [],
            "requests_from_ceo": [],
            "notion_ops_proposal": [],
        }
        return AgentOutput(
            text=json.dumps(payload, ensure_ascii=False),
            proposed_commands=[],
            agent_id="revenue_growth_operator",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "services.revenue_growth_operator_agent.revenue_growth_operator_agent",
        _fake_growth_agent,
    )

    router = _mk_router()

    out = asyncio.run(
        router.route(
            AgentInput(
                message="Pripremi 3 follow-up poruke + 2 emaila za leadove.",
                snapshot={"payload": {"tasks": []}},
                metadata={"include_debug": True},
            )
        )
    )

    assert out.agent_id == "revenue_growth_operator"

    tr = out.trace or {}
    assert isinstance(tr, dict)
    assert tr.get("selected_by") == "intent_precedence_guard"
    assert tr.get("selected_agent_id") == "revenue_growth_operator"

    txt = out.text or ""
    assert "TASKS snapshot is empty" not in txt
    assert "weekly" not in txt.lower()


def test_deliverable_ignore_tasks_snapshot_still_routes_to_growth_operator(monkeypatch):
    async def _fake_growth_agent(_agent_in, _ctx):  # noqa: ANN001
        return AgentOutput(
            text=json.dumps({"agent": "revenue_growth_operator"}, ensure_ascii=False),
            proposed_commands=[],
            agent_id="revenue_growth_operator",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "services.revenue_growth_operator_agent.revenue_growth_operator_agent",
        _fake_growth_agent,
    )

    router = _mk_router()

    out = asyncio.run(
        router.route(
            AgentInput(
                message="Ignore tasks snapshot. Napiši cold outreach sequence (3 poruke).",
                snapshot={"payload": {"tasks": []}},
                metadata={"include_debug": True},
            )
        )
    )

    assert out.agent_id == "revenue_growth_operator"
    tr = out.trace or {}
    assert tr.get("selected_by") == "intent_precedence_guard"


def test_weekly_request_tasks_empty_uses_ceo_weekly_flow_no_growth_delegation(
    monkeypatch, tmp_path
):
    """SSOT C: weekly flow only on explicit weekly phrases.

    For explicit weekly request + tasks=[], CEO Advisor may use its deterministic weekly/priorities flow.
    Must NOT route/delegate to revenue_growth_operator.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):
        raise AssertionError(
            "executor must not be called for weekly empty-tasks fallback"
        )

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    from services.ceo_advisor_agent import create_ceo_advisor_agent

    out = asyncio.run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Daj mi 3 prioriteta i sedmični plan: šta da radim ove sedmice?",
                snapshot={
                    "payload": {
                        "tasks": [],
                        "projects": [
                            {
                                "id": "p1",
                                "title": "Project Alpha",
                                "last_edited_time": "2026-01-01T00:00:00Z",
                            }
                        ],
                        "goals": [
                            {
                                "id": "g1",
                                "title": "Goal Beta",
                                "last_edited_time": "2026-01-02T00:00:00Z",
                            }
                        ],
                    }
                },
                metadata={"include_debug": True},
                agent_id="ceo_advisor",
                preferred_agent_id="ceo_advisor",
            ),
            ctx={},
        )
    )

    assert out.agent_id == "ceo_advisor"
    assert "TASKS snapshot" in (out.text or "")

    tr = out.trace or {}
    assert isinstance(tr, dict)
    assert tr.get("intent") in {"empty_tasks_fallback_priorities", "weekly"}


def test_non_weekly_request_tasks_empty_does_not_trigger_weekly_or_kickoff(monkeypatch):
    """SSOT C negative: tasks empty is context only, never trigger.

    This prompt is not an explicit weekly request, so it must not produce the weekly empty-tasks output.
    It should also not invoke any LLM executors in Responses-mode when grounding is missing.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    def _boom(*args, **kwargs):
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    from services.ceo_advisor_agent import create_ceo_advisor_agent

    out = asyncio.run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Pomozi mi da počnem; treba mi okvir za odluku.",
                snapshot={"payload": {"tasks": []}},
                metadata={"include_debug": True},
                agent_id="ceo_advisor",
                preferred_agent_id="ceo_advisor",
            ),
            ctx={"grounding_pack": {}},
        )
    )

    txt = out.text or ""
    assert "TASKS snapshot is empty" not in txt
    assert "weekly priorities" not in txt.lower()


def test_notion_ops_disarmed_returns_agent_output_not_jsonresponse(monkeypatch):
    """SSOT B + Step 3.4: Notion Ops proposal adapter must always return AgentOutput.

    Disarmed state must not return JSONResponse.
    """

    from services.notion_ops_agent import notion_ops_agent

    out = asyncio.run(
        notion_ops_agent(
            AgentInput(
                message="Kreiraj goal i 3 taska u Notion.",
                session_id="session_test_notion_disarmed",
                metadata={"include_debug": True},
            ),
            ctx={},
        )
    )

    assert isinstance(out, AgentOutput)
    assert out.agent_id == "notion_ops"
    assert out.proposed_commands, "expected proposal(s) when write intent is requested"
    assert "aktiv" in (out.text or "").lower() or "arm" in (out.text or "").lower()


def test_execution_dispatch_requires_armed_and_approved(monkeypatch):
    """SSOT B: dispatch to Notion Ops only when ARMED + approved.

    This is tested at ExecutionOrchestrator layer with a mocked NotionOpsAgent.execute.
    """

    from models.ai_command import AICommand
    from services.notion_ops_state import set_armed

    class _DummyNotionService:  # noqa: D401
        async def execute(self, _cmd):  # noqa: ANN001
            return {"ok": True, "success": True}

    monkeypatch.setattr(
        "services.execution_orchestrator.get_notion_service",
        lambda: _DummyNotionService(),
    )

    from services.execution_orchestrator import ExecutionOrchestrator

    orch = ExecutionOrchestrator()

    # Force policy allowlist to avoid brittle role/policy coupling.
    monkeypatch.setattr(orch.governance.policy, "can_request", lambda _x: True)
    monkeypatch.setattr(
        orch.governance.policy, "is_action_allowed_for_role", lambda *_a, **_k: True
    )

    # Track dispatch.
    called = {"count": 0}

    async def _fake_execute(_cmd):  # noqa: ANN001
        called["count"] += 1
        return {"ok": True, "success": True, "result": {"intent": _cmd.intent}}

    monkeypatch.setattr(orch.notion_agent, "execute", _fake_execute)

    # Approval is required by governance for notion_write.
    monkeypatch.setattr(orch.approvals, "is_fully_approved", lambda _aid: True)

    session_id = "session_test_exec_notion"

    # 1) DISARMED -> must not dispatch.
    asyncio.run(set_armed(session_id, False, prompt="test"))

    cmd = AICommand(
        command="notion_write",
        intent="create_page",
        params={"db_key": "goals", "property_specs": {}},
        initiator="ceo_chat",
        approval_id="approval_test_1",
        metadata={"session_id": session_id},
    )

    res1 = asyncio.run(orch.execute(cmd))
    assert isinstance(res1, dict)
    assert res1.get("execution_state") == "BLOCKED"
    assert called["count"] == 0

    # 2) ARMED + approved -> must dispatch.
    asyncio.run(set_armed(session_id, True, prompt="test"))

    cmd2 = AICommand(
        command="notion_write",
        intent="create_page",
        params={"db_key": "goals", "property_specs": {}},
        initiator="ceo_chat",
        approval_id="approval_test_2",
        metadata={"session_id": session_id},
    )

    res2 = asyncio.run(orch.execute(cmd2))
    assert isinstance(res2, dict)
    assert res2.get("execution_state") == "COMPLETED"
    assert called["count"] == 1
