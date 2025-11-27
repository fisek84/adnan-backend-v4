from fastapi import APIRouter
from ext.agents.sender import send_to_agent

router = APIRouter()

@router.post("/agents/message")
async def route_message(data: dict):
    """
    Očekuje payload:
    {
        "agent": "writer"  # ili ops, planner...
        "payload": {...}
    }
    """
    agent = data["agent"]
    payload = data["payload"]
    return send_to_agent(agent, payload)
