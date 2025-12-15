# services/action_dictionary.py

"""
ACTION DICTIONARY (CANONICAL)

Ovo NIJE execution engine.
Ovo je jedini autoritativni izvor:
- dozvoljenih sistemskih komandi
- njihove semantike
- njihovih handlera

COO Translator i Execution Engine koriste ISKLJUČIVO ovaj modul.
"""

from typing import Callable, Dict, Optional, Any


# ------------------------------------------
# Placeholder izvršne akcije (bez logike)
# ------------------------------------------

def action_create_task(payload: Dict[str, Any]):
    return {"status": "ok", "action": "create_task", "payload": payload}

def action_update_goal(payload: Dict[str, Any]):
    return {"status": "ok", "action": "update_goal", "payload": payload}

def action_sync_notion(payload: Dict[str, Any]):
    return {"status": "ok", "action": "sync_notion", "payload": payload}

def action_focus_mode(payload: Dict[str, Any]):
    return {"status": "ok", "action": "focus_mode", "payload": payload}

def action_update_state(payload: Dict[str, Any]):
    return {"status": "ok", "action": "update_state", "payload": payload}

def action_schedule(payload: Dict[str, Any]):
    return {"status": "ok", "action": "schedule", "payload": payload}

def action_workflow(payload: Dict[str, Any]):
    return {"status": "ok", "action": "workflow", "payload": payload}

def action_system_query(payload: Dict[str, Any]):
    """
    Read-only system state query.
    NO side effects.
    """
    return {
        "status": "ok",
        "action": "system_query",
        "summary": "System is operational",
        "payload": payload,
    }


# ------------------------------------------
# ACTION DEFINITIONS (AUTHORITATIVE)
# ------------------------------------------

ACTION_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "system_query": {
        "handler": action_system_query,
        "description": "Read-only system state query",
        "category": "read",
        "allowed_sources": ["user", "system"],
    },

    "create_task": {
        "handler": action_create_task,
        "description": "Create a new task in the system",
        "category": "write",
        "allowed_sources": ["user", "agent", "system"],
    },
    "update_goal": {
        "handler": action_update_goal,
        "description": "Update an existing goal",
        "category": "write",
        "allowed_sources": ["user", "agent"],
    },
    "sync_notion": {
        "handler": action_sync_notion,
        "description": "Synchronize data with Notion",
        "category": "sync",
        "allowed_sources": ["system", "agent"],
    },
    "focus_mode": {
        "handler": action_focus_mode,
        "description": "Enable or disable focus mode",
        "category": "state",
        "allowed_sources": ["user"],
    },
    "update_state": {
        "handler": action_update_state,
        "description": "Update internal system state",
        "category": "state",
        "allowed_sources": ["system"],
    },
    "schedule": {
        "handler": action_schedule,
        "description": "Schedule an action or task",
        "category": "write",
        "allowed_sources": ["user", "agent"],
    },
    "workflow": {
        "handler": action_workflow,
        "description": "Execute a predefined workflow",
        "category": "workflow",
        "allowed_sources": ["agent", "system"],
    },
}


# ------------------------------------------
# PUBLIC HELPERS (USED BY COO & EXECUTION)
# ------------------------------------------

def is_valid_command(command: str) -> bool:
    return command in ACTION_DEFINITIONS


def get_action_definition(command: str) -> Optional[Dict[str, Any]]:
    return ACTION_DEFINITIONS.get(command)


def get_action_handler(command: str) -> Optional[Callable[[Dict[str, Any]], Any]]:
    definition = ACTION_DEFINITIONS.get(command)
    if not definition:
        return None
    return definition.get("handler")
