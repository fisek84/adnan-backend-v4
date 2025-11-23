from fastapi import APIRouter, HTTPException
from typing import Dict, Any

# ovaj globalni service ćemo kasnije povezati u main.py
agents_service_global = None

router = APIRouter(
    prefix="/agents",
    tags=["agents"]
)


# ---------------------------------------------------------
# 1. POST MESSAGE INTO AGENT EXCHANGE
# ---------------------------------------------------------
@router.post("/message")
def post_agent_message(data: Dict[str, str]) -> Dict[str, Any]:
    if agents_service_global is None:
        raise HTTPException(status_code=500, detail="Agents service not initialized")

    agent = data.get("agent")
    content = data.get("content")
    msg_type = data.get("type", "message")

    return agents_service_global.post_message(agent, content, msg_type)


# ---------------------------------------------------------
# 2. GET MESSAGES FROM AGENT EXCHANGE
# ---------------------------------------------------------
@router.get("/messages")
def get_agent_messages(limit: int = 20) -> Dict[str, Any]:
    if agents_service_global is None:
        raise HTTPException(status_code=500, detail="Agents service not initialized")

    messages = agents_service_global.read_messages(limit)
    return {"status": "ok", "messages": messages}


# ---------------------------------------------------------
# 3. CREATE PROJECT FOR AN AGENT
# ---------------------------------------------------------
@router.post("/project")
def create_project(data: Dict[str, str]) -> Dict[str, Any]:
    if agents_service_global is None:
        raise HTTPException(status_code=500, detail="Agents service not initialized")

    agent = data.get("agent")
    title = data.get("title")
    description = data.get("description", "")

    return agents_service_global.create_project(agent, title, description)


# ---------------------------------------------------------
# 4. UPDATE AGENT STATE
# ---------------------------------------------------------
@router.post("/state")
def update_agent_state(data: Dict[str, str]) -> Dict[str, Any]:
    if agents_service_global is None:
        raise HTTPException(status_code=500, detail="Agents service not initialized")

    agent = data.get("agent")
    new_state = data.get("state")

    return agents_service_global.update_agent_state(agent, new_state)