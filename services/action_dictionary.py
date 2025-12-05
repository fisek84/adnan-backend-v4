# services/action_dictionary.py

"""
ACTION DICTIONARY (Korak 8.2)

Ovo NIJE Action Engine.
Ovo je samo mapiranje:
directive → backend funkcija (placeholder)

U 8.3 ćemo implementirati pravi Execution Engine.
"""

# ------------------------------------------
# Placeholder izvršne akcije (bez logike)
# ------------------------------------------
def action_create_task(params: dict):
    return {"status": "ok", "action": "create_task", "params": params}

def action_update_goal(params: dict):
    return {"status": "ok", "action": "update_goal", "params": params}

def action_sync_notion(params: dict):
    return {"status": "ok", "action": "sync_notion", "params": params}

def action_focus_mode(params: dict):
    return {"status": "ok", "action": "focus_mode", "params": params}

def action_update_state(params: dict):
    return {"status": "ok", "action": "update_state", "params": params}

def action_schedule(params: dict):
    return {"status": "ok", "action": "schedule", "params": params}

def action_workflow(params: dict):
    return {"status": "ok", "action": "workflow", "params": params}


# ------------------------------------------
# ACTION MAP
# ------------------------------------------
ACTION_MAP = {
    "create_task": action_create_task,
    "update_goal": action_update_goal,
    "sync_notion": action_sync_notion,
    "focus_mode": action_focus_mode,
    "update_state": action_update_state,
    "schedule": action_schedule,
    "workflow": action_workflow,
}

