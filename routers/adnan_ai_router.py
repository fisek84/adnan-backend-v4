# routers/adnan_ai_router.py
# KANONSKA VERZIJA — BEZ MIJENJANJA STRUKTURE, SAMO ISPRAVAN FLOW

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
from services.workflow_event_bridge import WorkflowEventBridge
from models.ai_command import AICommand


router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ai_command_service: Optional[AICommandService] = None
coo_translation_service: Optional[COOTranslationService] = None
coo_conversation_service: Optional[COOConversationService] = None

_workflow_bridge = WorkflowEventBridge()


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
    # 1. COO CONVERSATION — CANONICAL ENTRYPOINT (ALWAYS)
    # ========================================================
    conversation_result: COOConversationResult = coo_conversation_service.handle_user_input(
        raw_input=user_text,
        source="user",
        context=context,
    )

    # --------------------------------------------------------
    # NOT READY → UX RESPONSE
    # --------------------------------------------------------
    if conversation_result.type != "ready_for_translation":
        return {
            "status": "ok",
            "type": conversation_result.type,
            "text": conversation_result.text,
            "next_actions": conversation_result.next_actions,
        }

    # ========================================================
    # 2. COO TRANSLATION — SINGLE AUTHORIZED HANDOFF
    # ========================================================
    ai_command: Optional[AICommand] = coo_translation_service.translate(
        raw_input=user_text,
        source="system",
        context=context,
    )

    if not ai_command:
        return {
            "status": "rejected",
            "reason": "Input could not be translated into a valid system command.",
        }

    # ========================================================
    # 3. EXECUTION
    # ========================================================
    try:
        result = await ai_command_service.execute(ai_command)

        response = {
            "status": "success",
            "command": ai_command.command,
            "result": result,
        }

        workflow_id = result.get("workflow_id")
        if workflow_id:
            response["workflow"] = _workflow_bridge.snapshot(workflow_id)

        return response

    except Exception as e:
        logger.exception("Execution failed")
        raise HTTPException(500, str(e))
