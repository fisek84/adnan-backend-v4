# services/notion_ops_agent.py

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from fastapi.responses import JSONResponse


import logging
from typing import Any, Dict, List

from models.ai_command import AICommand
from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.notion_service import NotionService, get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ------------------------------
# PHASE 6: Notion Ops Session SSOT
# ------------------------------
# Default armed=False.
_NOTION_OPS_SESSIONS: Dict[str, Dict[str, Any]] = {}
_NOTION_OPS_LOCK = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _set_armed(session_id: str, armed: bool, *, prompt: str) -> Dict[str, Any]:
    """
    Set session state to armed/unarmed.
    """
    async with _NOTION_OPS_LOCK:
        st = _NOTION_OPS_SESSIONS.get(session_id) or {}
        st["armed"] = bool(armed)
        st["armed_at"] = _now_iso() if armed else None
        st["last_prompt_id"] = None
        st["last_toggled_at"] = _now_iso()
        _NOTION_OPS_SESSIONS[session_id] = st
        return dict(st)


async def _get_state(session_id: str) -> Dict[str, Any]:
    async with _NOTION_OPS_LOCK:
        st = _NOTION_OPS_SESSIONS.get(session_id) or {"armed": False, "armed_at": None}
        if "armed" not in st:
            st["armed"] = False
        if "armed_at" not in st:
            st["armed_at"] = None
        return dict(st)


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
            proposed.append(
                ProposedCommand(
                    command="ceo.command.propose",
                    args={
                        "prompt": msg,
                        "intent": intent,
                        "supports_bilingual": True,
                    },
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

    # Check session state before proceeding with the action
    session_id = getattr(agent_input, "session_id", None)
    if session_id:
        state = await _get_state(session_id)
        armed = state.get("armed", False)

        if not armed:
            # Block any write operation if Notion Ops is not armed
            return JSONResponse(
                content={
                    "text": "Notion Ops nije aktivan. Želiš aktivirati? (napiši: 'notion ops aktiviraj' / 'notion ops uključi') / Notion Ops is not armed. Want to activate? (write: 'notion ops activate' / 'notion ops enable')",
                    "proposed_commands": proposed,
                    "agent_id": "notion_ops",
                    "read_only": True,
                    "trace": trace,
                }
            )

    return AgentOutput(
        text=text,
        proposed_commands=proposed,
        agent_id="notion_ops",
        read_only=read_only,
        trace=trace,
    )
