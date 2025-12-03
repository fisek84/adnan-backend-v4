from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging  # Dodajemo logovanje

# Injected iz main.py
ai_service_global = None

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/ai", tags=["AI"])


class AIRequest(BaseModel):
    command: str
    payload: dict | None = None


@router.post("/run")
async def run_ai(req: AIRequest):
    logger.info(f"Received AI command: {req.command}")

    if not ai_service_global:
        logger.error("AICommandService not initialized")
        raise HTTPException(500, "AICommandService not initialized")

    try:
        result = ai_service_global.execute(req.command, req.payload or {})
        logger.info(f"AI command '{req.command}' executed successfully.")
    except Exception as e:
        logger.error(f"AI Execution error: {str(e)}")
        raise HTTPException(500, f"AI Execution error: {str(e)}")

    return {"result": result}


@router.get("/commands")
async def list_commands():
    if not ai_service_global:
        logger.error("AICommandService not initialized")
        raise HTTPException(500, "AICommandService not initialized")

    available_commands = ai_service_global.available_commands()
    logger.info(f"Available AI commands: {available_commands}")
    return {"commands": available_commands}
