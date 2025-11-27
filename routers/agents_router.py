from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Injected through main.py
agents_service_global = None

router = APIRouter(prefix="/agents", tags=["Agents"])


class AgentRequest(BaseModel):
    action: str
    payload: dict | None = None


@router.post("/run")
async def run_agent(req: AgentRequest):
    if agents_service_global is None:
        raise HTTPException(500, "AgentsService not initialized")

    try:
        result = await agents_service_global.execute(req.action, req.payload or {})
    except Exception as e:
        raise HTTPException(500, f"Agent execution error: {str(e)}")

    return {"result": result}


@router.get("/actions")
async def list_actions():
    if agents_service_global is None:
        raise HTTPException(500, "AgentsService not initialized")

    return {"actions": agents_service_global.available_actions()}   