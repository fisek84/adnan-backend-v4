# services/notion_ops_agent.py

from __future__ import annotations

import logging
from typing import Any, Dict, List

from models.ai_command import AICommand
from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.notion_service import NotionService, get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NotionOpsAgent:
    """
    NOTION OPS AGENT — CANONICAL WRITE EXECUTOR (THIN)

    CANON (PRODUCTION):
    - NEVER executes proposal wrapper
    - REQUIRES approval_id for any write
    - ACCEPTS workflow intents (goal_task_workflow) as orchestration results
    - Delegates ONLY atomic writes to NotionService
    """

    def __init__(self, notion: NotionService):
        if notion is None:
            raise TypeError("NotionOpsAgent requires a NotionService instance")
        self.notion = notion

    async def execute(self, command: AICommand) -> Dict[str, Any]:
        if not isinstance(command, AICommand):
            raise TypeError("NotionOpsAgent.execute requires AICommand")

        # --- HARD NORMALIZATION SAFETY ---
        if not isinstance(command.intent, str) or not command.intent.strip():
            raise RuntimeError("NotionOpsAgent: missing intent")

        intent = command.intent.strip()

        # --- SECURITY: approval_id required for any write / workflow ---
        approval_id = getattr(command, "approval_id", None)
        if not isinstance(approval_id, str) or not approval_id.strip():
            md = getattr(command, "metadata", None)
            if isinstance(md, dict):
                approval_id = md.get("approval_id")

        if not isinstance(approval_id, str) or not approval_id.strip():
            raise RuntimeError(
                "SECURITY VIOLATION: NotionOpsAgent execution without approval_id"
            )

        logger.info(
            "NotionOpsAgent.execute intent=%s execution_id=%s approval_id=%s",
            intent,
            getattr(command, "execution_id", None),
            approval_id,
        )

        # ============================================================
        # WORKFLOW INTENTS (ORCHESTRATION RESULT — TERMINAL HERE)
        # ============================================================
        if intent == "goal_task_workflow":
            # Orchestrator already validated + approved this workflow.
            # At this layer we ACK success deterministically.
            return {
                "ok": True,
                "success": True,
                "workflow": command.params or {},
                "note": "goal_task_workflow executed (orchestrated upstream)",
            }

        # ============================================================
        # ATOMIC NOTION INTENTS → DELEGATE
        # ============================================================
        return await self.notion.execute(command)


# ============================================================
# FACTORY
# ============================================================
def create_notion_ops_agent() -> NotionOpsAgent:
    return NotionOpsAgent(get_notion_service())


# ============================================================
# ROUTER ENTRYPOINT (PROPOSAL-ONLY)
# ============================================================
async def notion_ops_agent(agent_input: AgentInput, ctx: Dict[str, Any]) -> AgentOutput:
    """
    Router-callable adapter.

    CANON:
    - NEVER executes Notion writes
    - ONLY returns ProposedCommand
    - Execution MUST go through /api/execute/raw → approval → orchestrator
    """

    msg = (getattr(agent_input, "message", None) or "").strip()

    md = getattr(agent_input, "metadata", None)
    if not isinstance(md, dict):
        md = {}

    read_only = bool(md.get("read_only", True))

    proposed: List[ProposedCommand] = []

    if msg:
        proposed.append(
            ProposedCommand(
                command="ceo.command.propose",
                args={"prompt": msg},
                reason="Notion write/workflow mora ići kroz approval/execution pipeline.",
                requires_approval=True,
                risk="HIGH",
                dry_run=True,
            )
        )

    text = (
        "Notion Ops: vraćam prijedlog komande za approval."
        if msg
        else "Notion Ops: nedostaje prompt za prijedlog komande."
    )

    trace: Dict[str, Any] = {}
    if isinstance(ctx, dict) and isinstance(ctx.get("trace"), dict):
        trace.update(ctx["trace"])

    trace.update(
        {
            "agent": "notion_ops",
            "mode": "proposal_only",
            "read_only": read_only,
        }
    )

    return AgentOutput(
        text=text,
        proposed_commands=proposed,
        agent_id="notion_ops",
        read_only=read_only,
        trace=trace,
    )
