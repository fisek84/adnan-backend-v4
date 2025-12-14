from fastapi import APIRouter
from services.agent_router.agent_router import AgentRouter

router = APIRouter()
agent_router = AgentRouter()


@router.post("/agents/execute")
async def execute_agent(command: dict):
    """
    Očekuje DELEGATION CONTRACT:
    {
        "command": "create_database_entry",
        "payload": {...}
    }
    """
    return await agent_router.execute(command)
