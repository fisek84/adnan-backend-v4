from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.ai_command_service import AICommandService
from services.coo_conversation_service import COOConversationService
from services.coo_translation_service import COOTranslationService

# Injected via main.py
ai_command_service: Optional[AICommandService] = None
coo_conversation_service: Optional[COOConversationService] = None
coo_translation_service: Optional[COOTranslationService] = None


def set_ai_services(
    *,
    command_service: AICommandService,
    conversation_service: COOConversationService,
    translation_service: COOTranslationService,
) -> None:
    global ai_command_service
    global coo_conversation_service
    global coo_translation_service

    ai_command_service = command_service
    coo_conversation_service = conversation_service
    coo_translation_service = translation_service


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/ai", tags=["AI"])


# ============================================================
# REQUEST MODEL (UX INPUT ONLY)
# ============================================================


class AIRequest(BaseModel):
    text: str = Field(..., min_length=1)
    context: Optional[Dict[str, Any]] = None


# ============================================================
# RUN AI — UX ENTRYPOINT (CANON: READ-ONLY)
# ============================================================


@router.post("/run")
async def run_ai(req: AIRequest) -> Dict[str, Any]:
    """
    CANON:
    - This endpoint is a chat/UX entrypoint and MUST NOT execute writes.
    - It may only: read context, produce advice, and propose AICommand(s).
    - Execution (side-effects) must happen through the dedicated execution path (/api/execute),
      followed by governance approval.
    """
    logger.info("[AI] UX request received")

    if not ai_command_service or not coo_conversation_service or not coo_translation_service:
        raise HTTPException(500, "AI services not initialized")

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text is required")

    context: Dict[str, Any] = req.context or {}

    # 1) COO CONVERSATION (ADVICE / CLARIFY / STOP)
    convo = coo_conversation_service.handle_user_input(
        raw_input=text,
        source="user",
        context=context,
    )

    # If not ready, return the advisory/clarification response (READ-only)
    if getattr(convo, "type", None) != "ready_for_translation":
        return {
            "ok": True,
            "read_only": True,
            "type": getattr(convo, "type", "unknown"),
            "text": getattr(convo, "text", ""),
            "next_actions": getattr(convo, "next_actions", []),
            "proposed_commands": [],
        }

    # 2) TRANSLATION (PROPOSE AICommand)
    command = coo_translation_service.translate(
        raw_input=text,
        source="user",
        context=context,
    )

    if not command:
        return {
            "ok": True,
            "read_only": True,
            "type": "rejected",
            "text": "Input cannot be translated into a command. Clarify intent and try again.",
            "next_actions": ["Clarify the request with concrete scope, constraints, and desired outcome."],
            "proposed_commands": [],
        }

    # 3) PROPOSAL ONLY (NO EXECUTION HERE)
    # Normalize proposed command for UI
    proposed = {
        "status": "BLOCKED",
        "command": command,
        "required_approval": True,
    }

    return {
        "ok": True,
        "read_only": True,
        "type": "proposal",
        "text": getattr(convo, "text", "") or "Proposed command is ready for approval/execution flow.",
        "next_actions": getattr(convo, "next_actions", []) or ["Review proposal, then execute via /api/execute if approved."],
        "proposed_commands": [proposed],
    }


# Export alias (style kao ostali routeri)
ai_router = router
