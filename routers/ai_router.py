from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import logging
from typing import Optional, Dict, Any

from services.coo_conversation_service import COOConversationService
from services.coo_translation_service import COOTranslationService
from services.ai_command_service import AICommandService
from services.response_formatter import ResponseFormatter

# Injected via main.py
ai_command_service: Optional[AICommandService] = None
coo_conversation_service: Optional[COOConversationService] = None
coo_translation_service: Optional[COOTranslationService] = None
response_formatter: Optional[ResponseFormatter] = None


def set_ai_services(
    *,
    command_service: AICommandService,
    conversation_service: COOConversationService,
    translation_service: COOTranslationService,
    formatter: ResponseFormatter,
):
    global ai_command_service, coo_conversation_service, coo_translation_service, response_formatter
    ai_command_service = command_service
    coo_conversation_service = conversation_service
    coo_translation_service = translation_service
    response_formatter = formatter


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
# RUN AI — CANONICAL UX ENTRYPOINT
# ============================================================
@router.post("/run")
async def run_ai(req: AIRequest):
    logger.info("[AI] UX request received")

    if (
        not ai_command_service
        or not coo_conversation_service
        or not coo_translation_service
        or not response_formatter
    ):
        logger.error("[AI] Services not initialized")
        raise HTTPException(500, "AI services not initialized")

    context = req.context or {}

    # --------------------------------------------------------
    # 1. COO CONVERSATION (UX LAYER)
    # --------------------------------------------------------
    conversation_result = coo_conversation_service.handle_user_input(
        raw_input=req.text,
        source="user",
        context=context,
    )

    if conversation_result.type != "ready_for_translation":
        # UX-only response, NO EXECUTION
        return {
            "type": conversation_result.type,
            "text": conversation_result.text,
            "next_actions": conversation_result.next_actions,
            "readiness": conversation_result.readiness,
        }

    # --------------------------------------------------------
    # 2. COO TRANSLATION (UX → SYSTEM)
    # --------------------------------------------------------
    ai_command = coo_translation_service.translate(
        raw_input=req.text,
        source="user",
        context=context,
    )

    if not ai_command:
        logger.info("[AI] Translation rejected")
        return {
            "status": "rejected",
            "reason": "Input cannot be translated into a valid system command.",
        }

    # --------------------------------------------------------
    # 3. EXECUTION (SYSTEM)
    # --------------------------------------------------------
    try:
        execution_result = await ai_command_service.execute(ai_command)
    except Exception:
        logger.exception("[AI] Execution failure")
        raise HTTPException(500, "AI execution failed")

    # --------------------------------------------------------
    # 4. RESPONSE FORMATTER (SINGLE UX OUTPUT)
    # --------------------------------------------------------
    formatted = response_formatter.format(
        intent=ai_command.intent or "",
        confidence=1.0,
        csi_state={"state": ai_command.execution_state or "IDLE"},
        execution_result=execution_result,
        request_id=ai_command.request_id,
    )

    return formatted


# ============================================================
# INTERNAL — SYSTEM COMMAND LIST (DEBUG ONLY)
# ============================================================
@router.get("/commands", include_in_schema=False)
async def list_commands():
    from services.action_dictionary import ACTION_DEFINITIONS

    return {
        "commands": list(ACTION_DEFINITIONS.keys())
    }
