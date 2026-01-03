# routers/adnan_ai_router.py
# KANONSKA VERZIJA — READ/PROPOSE ONLY (FAZA 4)
# - NEMA execution iz chat-a
# - kompatibilno sa app_bootstrap injection hook-om (command_service/coo_translation/coo_conversation)
#
# Napomena:
# - Agent registry se učitava iz config/agents.json (SSOT) i koristi AgentRouterService.
# - Ovaj router je legacy UX wrapper; canonical endpoint je /api/chat.

from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.coo_conversation_service import COOConversationService
from services.coo_translation_service import COOTranslationService
from services.ai_command_service import AICommandService

from models.agent_contract import AgentInput, AgentOutput
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Keep these for bootstrap compatibility; only conversation is required.
ai_command_service: Optional[AICommandService] = None
coo_translation_service: Optional[COOTranslationService] = None
coo_conversation_service: Optional[COOConversationService] = None

# Canon agentic layer (read-only)
_agent_registry = AgentRegistryService()
_agent_router = AgentRouterService(_agent_registry)


def set_adnan_ai_services(
    command_service: AICommandService,
    coo_translation: COOTranslationService,
    coo_conversation: COOConversationService,
):
    """
    Bootstrap hook (legacy-compatible).

    FAZA 4 rule:
    - We accept all services for compatibility with app_bootstrap.
    - This router MUST NOT execute anything.
    """
    global ai_command_service, coo_translation_service, coo_conversation_service
    ai_command_service = command_service
    coo_translation_service = coo_translation
    coo_conversation_service = coo_conversation


class AdnanAIInput(BaseModel):
    text: str
    context: Optional[Dict[str, Any]] = None

    # Optional CANON payloads (ako ih klijent već ima)
    identity_pack: Optional[Dict[str, Any]] = None
    snapshot: Optional[Dict[str, Any]] = None

    # Optional agent selection (passthrough)
    preferred_agent_id: Optional[str] = None


def _ensure_registry_loaded() -> None:
    """
    Best-effort load; never raises from this wrapper.
    Canonical load happens in gateway lifespan; this is only a fallback.
    """
    try:
        if not _agent_registry.list_agents():
            _agent_registry.load_from_agents_json("config/agents.json", clear=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Agent registry load fallback failed: %s", exc)


def _ensure_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


@router.post("/input", response_model=AgentOutput)
async def adnan_ai_input(payload: AdnanAIInput) -> AgentOutput:
    """
    Legacy UX endpoint -> READ/PROPOSE ONLY wrapper.

    Pravila:
    - nema execute
    - nema approval create
    - samo agent_router.route() -> AgentOutput
    """
    if not coo_conversation_service:
        raise HTTPException(
            500, "AI services not initialized (coo_conversation_service missing)"
        )

    user_text = (payload.text or "").strip()
    if not user_text:
        raise HTTPException(400, "Empty input")

    context = payload.context or {}

    # Normalize optional payloads (IMPORTANT: do NOT blindly do "or {}" because it
    # destroys the distinction between "not provided" and "provided empty/invalid".)
    identity_pack = _ensure_dict(payload.identity_pack)
    snapshot = _ensure_dict(payload.snapshot)

    # 1) COO CONVERSATION — UX ONLY
    conversation_result = coo_conversation_service.handle_user_input(
        raw_input=user_text,
        source="user",
        context=context,
    )

    if getattr(conversation_result, "type", None) != "ready_for_translation":
        return AgentOutput(
            text=getattr(conversation_result, "text", "") or "",
            proposed_commands=[],
            agent_id="ux_gate",
            read_only=True,
            trace={
                "selected_by": "coo_conversation_gate",
                "conversation_type": getattr(conversation_result, "type", None),
                "next_actions": getattr(conversation_result, "next_actions", None),
                "endpoint": "/adnan-ai/input",
                "canon": "read_propose_only",
            },
        )

    # 2) CANON AGENT ROUTER — READ/PROPOSE ONLY
    _ensure_registry_loaded()

    md: Dict[str, Any] = {
        "context": context,
        "endpoint": "/adnan-ai/input",
        "read_only": True,
        "legacy_wrapper": True,
        "canon": "read_propose_only",
    }

    # Track snapshot origin for downstream diagnostics.
    # If snapshot is non-empty dict -> treat as client-provided snapshot.
    if isinstance(snapshot, dict) and len(snapshot) > 0:
        md.setdefault("snapshot_source", "client")

    agent_input = AgentInput(
        message=user_text,
        identity_pack=identity_pack,
        snapshot=snapshot,
        preferred_agent_id=payload.preferred_agent_id,
        metadata=md,
    )

    out = _agent_router.route(agent_input)

    # Final hard gate (defense-in-depth)
    out.read_only = True
    if out.trace is None:
        out.trace = {}
    if isinstance(out.trace, dict):
        out.trace["endpoint"] = "/adnan-ai/input"
        out.trace["canon"] = "read_propose_only"

    pcs = out.proposed_commands or []
    for pc in pcs:
        try:
            if hasattr(pc, "dry_run"):
                pc.dry_run = True
            if hasattr(pc, "execute"):
                pc.execute = False
            if hasattr(pc, "approved"):
                pc.approved = False
            if hasattr(pc, "requires_approval"):
                pc.requires_approval = True
        except Exception:
            # fail-soft
            continue
    out.proposed_commands = pcs

    return out
