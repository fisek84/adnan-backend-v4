# routers/ai_router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import logging
from typing import Optional, Dict, Any

from services.coo_translation_service import COOTranslationService
from services.ai_command_service import AICommandService

# Injected via main.py
ai_command_service: Optional[AICommandService] = None
coo_service: Optional[COOTranslationService] = None


def set_ai_services(command_service: AICommandService, coo: COOTranslationService):
    global ai_command_service, coo_service
    ai_command_service = command_service
    coo_service = coo


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
# RUN AI (CANONICAL UX ENTRY)
# ============================================================
@router.post("/run")
async def run_ai(req: AIRequest):
    logger.info("[AI] Received UX request")

    if not ai_command_service or not coo_service:
        logger.error("[AI] Services not initialized")
        raise HTTPException(500, "AI services not initialized")

    # --------------------------------------------------------
    # COO TRANSLATION (ONLY SEMANTIC GATE)
    # --------------------------------------------------------
    ai_command = coo_service.translate(
        raw_input=req.text,
        source="user",
        context=req.context or {},
    )

    if not ai_command:
        logger.info("[AI] Request rejected by COO")
        return {
            "status": "rejected",
            "reason": "Input cannot be translated into a valid system command.",
        }

    # --------------------------------------------------------
    # EXECUTION
    # --------------------------------------------------------
    try:
        result = ai_command_service.execute(ai_command)
        logger.info(f"[AI] Executed command: {ai_command.command}")

        return {
            "status": "success",
            "command": ai_command.command,
            "result": result,
        }

    except Exception as e:
        logger.exception("[AI] Execution failure")
        raise HTTPException(500, "AI execution failed")


# ============================================================
# INTERNAL — SYSTEM COMMAND LIST (DEBUG ONLY)
# ============================================================
@router.get("/commands", include_in_schema=False)
async def list_commands():
    from services.action_dictionary import ACTION_DEFINITIONS

    return {
        "commands": list(ACTION_DEFINITIONS.keys())
    }
