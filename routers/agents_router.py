from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from services.agents_service import AgentsService


router = APIRouter(prefix="/agents", tags=["Agents"])

# Global DI reference (set from main.py)
agents_service_global: Optional[AgentsService] = None


# ============================================================
# INTERNAL VALIDATION
# ============================================================
def _require_agents_service() -> AgentsService:
    if agents_service_global is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AgentsService is not initialized"
        )
    return agents_service_global


# ============================================================
# REQUEST MODELS (PRO)
# ============================================================
class MessagePayload(BaseModel):
    agent: str
    content: str
    type: str = "message"


class ProjectPayload(BaseModel):
    agent: str
    title: str
    description: Optional[str] = ""


class StatePayload(BaseModel):
    agent: str
    state: str


# ============================================================
# 1. POST MESSAGE INTO AGENT EXCHANGE
# ============================================================
@router.post(
    "/message",
    summary="Post a message from an AI agent into the Agent Exchange DB",
    status_code=200
)
async def post_agent_message(
    payload: MessagePayload,
    service: AgentsService = Depends(_require_agents_service)
):
    result = await service.post_message(
        agent=payload.agent,
        content=payload.content,
        msg_type=payload.type
    )
    return {
        "status": "success",
        "action": "post_message",
        "input": payload,
        "output": result
    }


# ============================================================
# 2. READ MESSAGES FROM AGENT EXCHANGE
# ============================================================
@router.get(
    "/messages",
    summary="Retrieve latest messages from Agent Exchange DB",
    status_code=200
)
async def get_agent_messages(
    limit: int = 20,
    service: AgentsService = Depends(_require_agents_service)
):
    messages = await service.read_messages(limit)
    return {
        "status": "success",
        "count": len(messages),
        "messages": messages
    }


# ============================================================
# 3. CREATE PROJECT FOR AN AGENT
# ============================================================
@router.post(
    "/project",
    summary="Create a project entry for an AI agent",
    status_code=201
)
async def create_project(
    payload: ProjectPayload,
    service: AgentsService = Depends(_require_agents_service)
):
    result = await service.create_project(
        agent=payload.agent,
        project_title=payload.title,
        description=payload.description
    )
    return {
        "status": "success",
        "action": "create_project",
        "input": payload,
        "output": result
    }


# ============================================================
# 4. UPDATE AGENT STATE
# ============================================================
@router.post(
    "/state",
    summary="Update the internal state of an AI agent",
    status_code=200
)
async def update_agent_state(
    payload: StatePayload,
    service: AgentsService = Depends(_require_agents_service)
):
    result = await service.update_agent_state(
        agent=payload.agent,
        new_state=payload.state
    )
    return {
        "status": "success",
        "action": "update_agent_state",
        "input": payload,
        "output": result
    }