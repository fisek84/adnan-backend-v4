# services/notion_ops_agent.py

from __future__ import annotations

import logging
from typing import Any, Dict, List

from models.ai_command import AICommand
from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.notion_service import NotionService, get_notion_service

# PHASE 6: Import shared Notion Ops state management
from services.notion_ops_state import get_state

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NotionOpsAgent:
    """
    NOTION OPS AGENT — CANONICAL WRITE EXECUTOR (THIN)
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


def _force_disarmed_wrapper_contract(proposed: List[ProposedCommand]) -> None:
    """
    Disarmed contract (E2E):
    - wrapper must be non-executable: scope="none"
    - must NOT require approval while disarmed: requires_approval=False
    - dry_run=True
    """
    for pc in proposed or []:
        try:
            cmd = getattr(pc, "command", None)
            if isinstance(cmd, str) and cmd.strip() == "ceo.command.propose":
                pc.scope = "none"
                pc.requires_approval = False
                pc.dry_run = True
        except Exception:
            pass


# ============================================================
# ROUTER ENTRYPOINT (PROPOSAL-ONLY)
# ============================================================
async def notion_ops_agent(agent_input: AgentInput, ctx: Dict[str, Any]) -> AgentOutput:
    """
    Router-callable adapter with enhanced bilingual support.

    Now supports:
    - Bosnian and English keyword recognition
    - Branch/batch request processing
    - Automatic property name translation
    """
    from services.notion_keyword_mapper import NotionKeywordMapper
    from services.branch_request_handler import BranchRequestHandler

    msg = (getattr(agent_input, "message", None) or "").strip()

    md = getattr(agent_input, "metadata", None)
    if not isinstance(md, dict):
        md = {}

    read_only = bool(md.get("read_only", True))

    proposed: List[ProposedCommand] = []

    if msg:
        # Detect if this is a branch request
        is_branch = BranchRequestHandler.parse_branch_request(msg) is not None

        # Detect intent from keywords (supports both languages)
        intent = NotionKeywordMapper.detect_intent(msg)

        if is_branch:
            # Branch request - propose grouped operation
            proposed.append(
                ProposedCommand(
                    command="ceo.command.propose",
                    args={
                        "prompt": msg,
                        "type": "branch_request",
                        "supports_bilingual": True,
                    },
                    reason="Grupni zahtjev za kreiranje povezanih ciljeva, zadataka i KPI-jeva. / Branch request for creating related goals, tasks, and KPIs.",
                    requires_approval=True,
                    risk="HIGH",
                    dry_run=True,
                )
            )
        elif intent:
            # Single intent detected
            goal_id = md.get("goal_id")
            goal_id_s = goal_id.strip() if isinstance(goal_id, str) else ""

            args: Dict[str, Any] = {
                "prompt": msg,
                "intent": intent,
                "supports_bilingual": True,
            }
            if intent == "create_task" and goal_id_s:
                args["goal_id"] = goal_id_s

            proposed.append(
                ProposedCommand(
                    command="ceo.command.propose",
                    args=args,
                    reason=f"Notion write/workflow mora ići kroz approval/execution pipeline. Detected intent: {intent}",
                    requires_approval=True,
                    risk="HIGH",
                    dry_run=True,
                )
            )
        else:
            # Generic proposal
            proposed.append(
                ProposedCommand(
                    command="ceo.command.propose",
                    args={
                        "prompt": msg,
                        "supports_bilingual": True,
                    },
                    reason="Notion write/workflow mora ići kroz approval/execution pipeline.",
                    requires_approval=True,
                    risk="HIGH",
                    dry_run=True,
                )
            )

    text = (
        "Notion Ops: vraćam prijedlog komande za approval. Podržavam Bosanski i Engleski jezik. / Notion Ops: returning command proposal for approval. Supporting Bosnian and English."
        if msg
        else "Notion Ops: nedostaje prompt za prijedlog komande. / Notion Ops: missing prompt for command proposal."
    )

    trace: Dict[str, Any] = {}
    if isinstance(ctx, dict) and isinstance(ctx.get("trace"), dict):
        trace.update(ctx["trace"])

    trace.update(
        {
            "agent": "notion_ops",
            "mode": "proposal_only",
            "read_only": read_only,
            "bilingual_support": True,
            "supported_languages": ["bosnian", "english"],
        }
    )

    # Check principal-bound state before proceeding with the action (BE-301)
    principal_sub = None
    try:
        md = getattr(agent_input, "metadata", None)
        if isinstance(md, dict):
            v = md.get("principal_sub")
            if isinstance(v, str) and v.strip():
                principal_sub = v.strip()
    except Exception:
        principal_sub = None

    if not principal_sub:
        try:
            ip0 = getattr(agent_input, "identity_pack", None)
            ip = ip0 if isinstance(ip0, dict) else {}
            payload = ip.get("payload") if isinstance(ip.get("payload"), dict) else {}
            v = payload.get("sub") if isinstance(payload, dict) else None
            if not (isinstance(v, str) and v.strip()):
                v = ip.get("sub")
            if isinstance(v, str) and v.strip():
                principal_sub = v.strip()
        except Exception:
            principal_sub = None

    armed = False
    if isinstance(principal_sub, str) and principal_sub.strip():
        state = await get_state(principal_sub)
        armed = bool(state.get("armed", False))

    if not armed:
        # Disarmed: enforce non-executable wrapper contract for E2E.
        trace["notion_ops_armed"] = False
        _force_disarmed_wrapper_contract(proposed)

        return AgentOutput(
            text="Notion Ops nije aktivan. Želiš aktivirati? (napiši: 'notion ops aktiviraj' / 'notion ops uključi') / Notion Ops is not armed. Want to activate? (write: 'notion ops activate' / 'notion ops enable')",
            proposed_commands=proposed,
            agent_id="notion_ops",
            read_only=read_only,
            trace=trace,
        )

    return AgentOutput(
        text=text,
        proposed_commands=proposed,
        agent_id="notion_ops",
        read_only=read_only,
        trace=trace,
    )
