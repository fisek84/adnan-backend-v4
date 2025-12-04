# routers/ai_router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging

# Injected via main.py
ai_service_global = None

def set_ai_service(service):
    global ai_service_global
    ai_service_global = service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/ai", tags=["AI"])


# ============================================================
# REQUEST MODEL
# ============================================================
class AIRequest(BaseModel):
    command: str
    payload: dict | None = None


# ============================================================
# RUN AI COMMAND
# ============================================================
@router.post("/run")
async def run_ai(req: AIRequest):
    logger.info(f"[AI] Received AI command: {req.command}")

    if not ai_service_global:
        logger.error("[AI] AICommandService not initialized")
        raise HTTPException(500, "AICommandService not initialized")

    try:
        result = ai_service_global.execute(req.command, req.payload or {})
        logger.info(f"[AI] Command '{req.command}' executed successfully")
    except Exception as e:
        logger.error(f"[AI] Execution error: {e}")
        raise HTTPException(500, f"AI Execution error: {e}")

    return {"result": result}


# ============================================================
# LIST AVAILABLE COMMANDS
# ============================================================
@router.get("/commands")
async def list_commands():
    if not ai_service_global:
        logger.error("[AI] AICommandService not initialized")
        raise HTTPException(500, "AICommandService not initialized")

    try:
        cmds = ai_service_global.available_commands()
        logger.info(f"[AI] Available commands: {cmds}")
        return {"commands": cmds}
    except Exception as e:
        logger.error(f"[AI] Failed to fetch commands: {e}")
        raise HTTPException(500, f"Could not load commands: {e}")
