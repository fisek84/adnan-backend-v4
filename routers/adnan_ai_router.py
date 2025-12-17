# routers/adnan_ai_router.py
# KANONSKA VERZIJA — ČIST ENTRYPOINT, BEZ INTERPRETACIJE EXECUTIONA

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
from typing import Optional, Dict, Any

from services.coo_translation_service import COOTranslationService
from services.coo_conversation_service import COOConversationService
from services.ai_command_service import AICommandService
from models.ai_command import AICommand

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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


class AdnanAIInput(BaseModel):
    text: str
    context: Optional[Dict[str, Any]] = None


@router.post("/input")
async def adnan_ai_input(payload: AdnanAIInput):
    if not ai_command_service or not coo_translation_service or not coo_conversation_service:
        raise HTTPException(500, "AI services not initialized")

    user_text = (payload.text or "").strip()
    if not user_text:
        raise HTTPException(400, "Empty input")

    context = payload.context or {}

    # ========================================================
    # 1. COO CONVERSATION — UX ONLY
    # ========================================================
    conversation_result = coo_conversation_service.handle_user_input(
        raw_input=user_text,
        source="user",
        context=context,
    )

    if conversation_result.type != "ready_for_translation":
        return {
            "type": conversation_result.type,
            "text": conversation_result.text,
            "next_actions": conversation_result.next_actions,
        }

    # ========================================================
    # 2. COO TRANSLATION — UX → SYSTEM
    # ========================================================
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

    # ========================================================
    # 3. SYSTEM EXECUTION — NO STATUS MAPPING
    # ========================================================
    try:
        return await ai_command_service.execute(ai_command)
    except Exception:
        logger.exception("Execution failed")
        raise HTTPException(500, "Execution failed")
