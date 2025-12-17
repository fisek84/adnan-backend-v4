from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import logging
from typing import Optional, Dict, Any

from services.coo_conversation_service import COOConversationService
from services.coo_translation_service import COOTranslationService
from services.ai_command_service import AICommandService

# Injected via main.py
ai_command_service: Optional[AICommandService] = None
coo_conversation_service: Optional[COOConversationService] = None
coo_translation_service: Optional[COOTranslationService] = None


def set_ai_services(
    *,
    command_service: AICommandService,
    conversation_service: COOConversationService,
    translation_service: COOTranslationService,
):
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
# RUN AI — UX ENTRYPOINT
# ============================================================
@router.post("/run")
async def run_ai(req: AIRequest):
    logger.info("[AI] UX request received")

    if (
        not ai_command_service
        or not coo_conversation_service
        or not coo_translation_service
    ):
        raise HTTPException(500, "AI services not initialized")

    context = req.context or {}

    # 1) COO CONVERSATION
    convo = coo_conversation_service.handle_user_input(
        raw_input=req.text,
        source="user",
        context=context,
    )

    if convo.type != "ready_for_translation":
        return {
            "type": convo.type,
            "text": convo.text,
            "next_actions": convo.next_actions,
        }

    # 2) TRANSLATION
    command = coo_translation_service.translate(
        raw_input=req.text,
        source="user",
        context=context,
    )

    if not command:
        return {
            "status": "rejected",
            "reason": "Input cannot be translated",
        }

    # 3) EXECUTION
    return await ai_command_service.execute(command)
    