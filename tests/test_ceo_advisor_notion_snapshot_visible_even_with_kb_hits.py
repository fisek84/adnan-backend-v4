import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict


class _CapturingExecutor:
    def __init__(self) -> None:
        self.last_context: Optional[Dict[str, Any]] = None
        self.last_text: Optional[str] = None

    async def ceo_command(
        self, *, text: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        self.last_text = text
        self.last_context = context
        return {
            "text": "Da — prema NOTION_SNAPSHOT imamo ciljeve i taskove.",
            "proposed_commands": [],
        }


def test_notion_snapshot_is_visible_in_instructions_even_when_kb_has_hits(
    monkeypatch,
):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")

    gp = {
        "enabled": True,
        "identity_pack": {"payload": {"system": "test"}},
        "kb_retrieved": {
            "entries": [
                {
                    "id": "KB1",
                    "title": "Some KB",
                    "content": "KB content",
                }
            ],
            "used_entry_ids": ["KB1"],
        },
        "notion_snapshot": {
            "ready": True,
            "payload": {
                "goals": [{"id": "g1"}],
                "tasks": [{"id": "t1"}],
                "projects": [{"id": "p1"}],
            },
        },
        "memory_snapshot": {"payload": {"active_decision": None}},
    }

    exec0 = _CapturingExecutor()

    def _fake_get_executor(*_a, **_k):
        return exec0

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor", _fake_get_executor
    )

    agent_input = DummyAgentInput(
        message="Da li imamo ciljeve i taskove u Notion?",
        snapshot={},
        metadata={"ui_output_lang": "bs"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={"grounding_pack": gp}))

    assert out.read_only is True
    assert out.proposed_commands == []

    lowered = (out.text or "").lower()
    assert "trenutno nemam to znanje" not in lowered
    assert "nije u kuriranom kb-u" not in lowered

    assert exec0.last_context is not None
    instructions = exec0.last_context.get("instructions")
    assert isinstance(instructions, str) and instructions.strip()

    # NOTION_SNAPSHOT must be included even when KB has hits.
    assert "NOTION_SNAPSHOT:" in instructions
    assert (
        "(omitted: KB-first)"
        not in instructions.split("NOTION_SNAPSHOT:\n", 1)[1][:120]
    )

    # Proof: payload lists are present.
    assert '"goals"' in instructions
    assert '"tasks"' in instructions
    assert '"projects"' in instructions
