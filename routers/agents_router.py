# routers/agents_router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging

# Injected through main.py
agents_service_global = None

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/agents", tags=["Agents"])


# ============================================================
# REQUEST MODEL
# ============================================================
class AgentRequest(BaseModel):
    action: str
    payload: dict | None = None


# ============================================================
# RUN AGENT ACTION
# ============================================================
@router.post("/run")
async def run_agent(req: AgentRequest):
    logger.info(f"[AGENTS] Received action: {req.action}, payload={req.payload}")

    if agents_service_global is None:
        logger.error("[AGENTS] AgentsService not initialized")
        raise HTTPException(500, "AgentsService not initialized")

    if not req.action or not isinstance(req.action, str):
        logger.error("[AGENTS] Action missing or invalid")
        raise HTTPException(400, "Field 'action' must be a non-empty string")

    # Normalize payload
    payload = req.payload or {}
    if not isinstance(payload, dict):
        logger.error("[AGENTS] Payload must be an object/dict")
        raise HTTPException(400, "Payload must be a JSON object")

    try:
        logger.info(f"[AGENTS] Executing '{req.action}' with payload: {payload}")
        result = await agents_service_global.execute(req.action, payload)
        logger.info(f"[AGENTS] Completed '{req.action}', result: {result}")
    except Exception as e:
        logger.error(f"[AGENTS] Agent execution error: {str(e)}")
        raise HTTPException(500, f"Agent execution error: {str(e)}")

    return {"ok": True, "action": req.action, "result": result}


# ============================================================
# LIST AVAILABLE AGENT ACTIONS
# ============================================================
@router.get("/actions")
async def list_actions():
    if agents_service_global is None:
        logger.error("[AGENTS] AgentsService not initialized")
        raise HTTPException(500, "AgentsService not initialized")

    try:
        actions = agents_service_global.available_actions()
        logger.info(f"[AGENTS] Available actions: {actions}")
        return {"actions": actions}
    except Exception as e:
        logger.error(f"[AGENTS] Error listing actions: {str(e)}")
        raise HTTPException(500, f"Failed to list agent actions: {str(e)}")
