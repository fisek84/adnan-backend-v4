from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging  # Dodajemo logovanje

# Injected through main.py
agents_service_global = None

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/agents", tags=["Agents"])

class AgentRequest(BaseModel):
    action: str
    payload: dict | None = None


@router.post("/run")
async def run_agent(req: AgentRequest):
    logger.info(f"Received agent action: {req.action} with payload: {req.payload}")

    if agents_service_global is None:
        logger.error("AgentsService not initialized")
        raise HTTPException(500, "AgentsService not initialized")

    try:
        result = await agents_service_global.execute(req.action, req.payload or {})
        logger.info(f"Agent action '{req.action}' executed successfully. Result: {result}")
    except Exception as e:
        logger.error(f"Agent execution error: {str(e)}")
        raise HTTPException(500, f"Agent execution error: {str(e)}")

    return {"result": result}


@router.get("/actions")
async def list_actions():
    if agents_service_global is None:
        logger.error("AgentsService not initialized")
        raise HTTPException(500, "AgentsService not initialized")

    available_actions = agents_service_global.available_actions()
    logger.info(f"Available agent actions: {available_actions}")
    return {"actions": available_actions}
