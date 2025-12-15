# routers/adnan_ai_router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
from typing import Optional, Dict, Any

from services.coo_translation_service import COOTranslationService
from services.coo_conversation_service import (
    COOConversationService,
    COOConversationResult,
)
from services.ai_command_service import AICommandService
from services.intent_contract import IntentType
from models.ai_command import AICommand


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Injected in bootstrap
ai_command_service: Optional[AICommandService] = None
coo_translation_service: Optional[COOTranslationService] = None
coo_conversation_service: Optional[COOConversationService] = None


def set_adnan_ai_services(
    command_service: AICommandService,
    coo_translation: COOTranslationService,
    coo_conversation: COOConversationService,
):
    global ai_command_service, coo_translation_service, coo_conversation_service
    ai_command_service = command_service
    coo_translation_service = coo_translation
    coo_conversation_service = coo_conversation


# ============================================================
# REQUEST MODEL
# ============================================================

class AdnanAIInput(BaseModel):
    text: str
    context: Optional[Dict[str, Any]] = None


# ============================================================
# CANONICAL UX ENTRYPOINT
# ============================================================

@router.post("/input")
async def adnan_ai_input(payload: AdnanAIInput):
    """
    Canonical UX entrypoint.

    FLOW:
    UX text
      → COO Conversation (UX language)
        → message / question → return UX response
        → ready_for_translation
             → COO Translation (system language)
             → AICommandService
             → ExecutionOrchestrator

    SPECIAL:
      CONFIRM + pending approval
        → REQUEST_EXECUTION
    """

    if not ai_command_service or not coo_translation_service or not coo_conversation_service:
        raise HTTPException(500, "AI services not initialized")

    user_text = (payload.text or "").strip()
    if not user_text:
        raise HTTPException(400, "Empty input")

    context = payload.context or {}

    # --------------------------------------------------------
    # 0. CONFIRM → REQUEST_EXECUTION (APPROVAL FLOW)
    # --------------------------------------------------------
    if (
        user_text.lower() in {"da", "može", "moze", "ok", "yes"}
        and context.get("pending_approval")
    ):
        pending = context["pending_approval"]

        ai_command = AICommand(
            command=pending["command"],
            intent=IntentType.REQUEST_EXECUTION.value,
            source="system",
            input={
                "requested_by": "user",
                "original_intent": pending.get("intent_type"),
            },
            params={},
            metadata={
                "executor": "autonomy",
                "approval_granted": True,
            },
            validated=True,
        )

        result = await ai_command_service.execute(ai_command)

        return {
            "status": "success",
            "command": ai_command.command,
            "result": result,
        }

    # --------------------------------------------------------
    # 1. COO CONVERSATION LAYER (JEZIK ZA LJUDE)
    # --------------------------------------------------------
    conversation_result: COOConversationResult = coo_conversation_service.handle_user_input(
        raw_input=user_text,
        source="user",
        context=context,
    )

    # Ako NIJE spremno za execution → VRATI UX ODGOVOR
    if conversation_result.type != "ready_for_translation":
        response = {
            "status": "ok",
            "type": conversation_result.type,
            "text": conversation_result.text,
            "next_actions": conversation_result.next_actions,
        }

        # Ako je approval potreban, pošalji hint u context
        if conversation_result.readiness and conversation_result.readiness.get("requires_approval"):
            response["context"] = {
                "pending_approval": {
                    "command": conversation_result.readiness.get("proposed_command"),
                    "intent_type": conversation_result.readiness.get("intent_type"),
                }
            }

        return response

    # --------------------------------------------------------
    # 2. COO TRANSLATION (UX → SYSTEM)
    # --------------------------------------------------------
    ai_command: Optional[AICommand] = coo_translation_service.translate(
        raw_input=user_text,
        source="user",
        context=context,
    )

    if not ai_command:
        return {
            "status": "rejected",
            "reason": "Input could not be translated into a valid system command.",
        }

    # --------------------------------------------------------
    # 3. EXECUTION (ASYNC)
    # --------------------------------------------------------
    try:
        result = await ai_command_service.execute(ai_command)
        return {
            "status": "success",
            "command": ai_command.command,
            "result": result,
        }

    except Exception as e:
        logger.exception("Execution failed")
        raise HTTPException(500, str(e))
