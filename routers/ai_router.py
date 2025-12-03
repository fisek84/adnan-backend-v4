from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Injected iz main.py
ai_service_global = None

router = APIRouter(prefix="/ai", tags=["AI"])


class AIRequest(BaseModel):
    command: str
    payload: dict | None = None


@router.post("/run")
async def run_ai(req: AIRequest):
    if not ai_service_global:
        raise HTTPException(500, "AICommandService not initialized")

    try:
        result = ai_service_global.execute(req.command, req.payload or {})
    except Exception as e:
        raise HTTPException(500, f"AI Execution error: {str(e)}")

    return {"result": result}


@router.get("/commands")
async def list_commands():
    if not ai_service_global:
        raise HTTPException(500, "AICommandService not initialized")

    return {"commands": ai_service_global.available_commands()}