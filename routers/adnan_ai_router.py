# routers/adnan_ai_router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
from typing import Optional, Dict, Any

from services.coo_translation_service import COOTranslationService
from services.ai_command_service import AICommandService
from models.ai_command import AICommand


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Injected in main.py
ai_command_service: Optional[AICommandService] = None
coo_service: Optional[COOTranslationService] = None


def set_adnan_ai_services(
    command_service: AICommandService,
    coo: COOTranslationService,
):
    global ai_command_service, coo_service
    ai_command_service = command_service
    coo_service = coo


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
      → COO Translation
      → AICommand
      → AICommandService
      → ExecutionOrchestrator
    """

    if not ai_command_service or not coo_service:
        raise HTTPException(500, "AI services not initialized")

    user_text = payload.text.strip()
    if not user_text:
        raise HTTPException(400, "Empty input")

    # --------------------------------------------------------
    # COO TRANSLATION (UX → SYSTEM)
    # --------------------------------------------------------
    ai_command: Optional[AICommand] = coo_service.translate(
        raw_input=user_text,
        source="user",
        context=payload.context or {},
    )

    if not ai_command:
        return {
            "status": "rejected",
            "reason": "Input could not be translated into a valid system command.",
        }

    # --------------------------------------------------------
    # EXECUTION (ASYNC)
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
