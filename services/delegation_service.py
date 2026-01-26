from __future__ import annotations

from typing import Any, Dict, Optional

from models.agent_contract import AgentInput, AgentOutput
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService


async def execute_delegation(
    *,
    parent_ctx: Dict[str, Any],
    target_agent_id: str,
    task_text: str,
    parent_agent_input: AgentInput,
    delegation_reason: str,
    preferred_agent_id: Optional[str] = None,
) -> AgentOutput:
    """Execute a child agent using the existing SSOT router.

    This is intentionally small and additive:
    - Uses AgentRegistryService + AgentRouterService (existing runtime mechanism).
    - Runs the target agent entrypoint (real call).
    - Returns the child AgentOutput with delegation trace fields.

    Note: Deliverable delegation is read-only and must not produce ProposedCommands.
    """

    reg = AgentRegistryService()
    reg.load_from_agents_json("config/agents.json", clear=True)
    router = AgentRouterService(reg)

    md_parent = (
        parent_agent_input.metadata
        if isinstance(getattr(parent_agent_input, "metadata", None), dict)
        else {}
    )

    child_md: Dict[str, Any] = dict(md_parent)
    # Defense-in-depth: delegation for deliverables is always read-only.
    child_md["read_only"] = True
    child_md.setdefault("require_approval", True)

    child_input = AgentInput(
        message=(task_text or "").strip(),
        identity_pack=parent_agent_input.identity_pack
        if isinstance(parent_agent_input.identity_pack, dict)
        else {},
        snapshot=parent_agent_input.snapshot
        if isinstance(parent_agent_input.snapshot, dict)
        else {},
        conversation_id=getattr(parent_agent_input, "conversation_id", None),
        history=getattr(parent_agent_input, "history", None),
        preferred_agent_id=preferred_agent_id or target_agent_id,
        metadata=child_md,
    )

    out = await router.route(child_input)

    # Hard rule: deliverable execution never returns proposed_commands.
    out.proposed_commands = []

    tr = out.trace if isinstance(out.trace, dict) else {}
    tr = dict(tr)
    tr.update(
        {
            "delegated_by": "ceo_advisor",
            "delegated_to": target_agent_id,
            "delegation_reason": delegation_reason,
        }
    )
    out.trace = tr

    return out
