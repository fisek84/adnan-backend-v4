import os

from fastapi import APIRouter
from services.agent_router.agent_router import AgentRouter

router = APIRouter()
agent_router = AgentRouter()


_WRITE_INTENTS = {
    "notion_write",
    "goal_write",
    "update_goal",
    "goal_task_workflow",
    "memory_write",
}


def _guard_enabled() -> bool:
    v = (os.getenv("ENABLE_WRITE_INTENT_GUARD", "0") or "0").strip()
    return v in {"1", "true", "True"}


def _is_write_intent(payload: dict) -> tuple[bool, str | None]:
    if not isinstance(payload, dict):
        return False, None

    top_command = payload.get("command")
    if isinstance(top_command, str) and top_command in _WRITE_INTENTS:
        return True, top_command

    top_intent = payload.get("intent")
    if isinstance(top_intent, str) and top_intent in _WRITE_INTENTS:
        return True, top_intent

    nested = payload.get("payload")
    if isinstance(nested, dict):
        nested_command = nested.get("command")
        if isinstance(nested_command, str) and nested_command in _WRITE_INTENTS:
            return True, nested_command

        nested_intent = nested.get("intent")
        if isinstance(nested_intent, str) and nested_intent in _WRITE_INTENTS:
            return True, nested_intent

    return False, None


@router.post("/agents/execute")
async def execute_agent(command: dict):
    """
    Očekuje DELEGATION CONTRACT:
    {
        "command": "create_database_entry",
        "payload": {...}
    }
    """
    if _guard_enabled():
        is_write, cmd = _is_write_intent(command)
        if is_write:
            return {
                "success": False,
                "reason": "write_intent_not_allowed_on_this_endpoint",
                "blocked_by": "write_intent_guard",
                "message": "Use /api/chat or /api/ceo-console/command for write proposals",
                "command": cmd,
            }

    return await agent_router.execute(command)
