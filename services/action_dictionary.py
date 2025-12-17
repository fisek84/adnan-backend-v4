from typing import Callable, Dict, Optional, Any
from services.notion_service import NotionService


# ------------------------------------------
# READ-ONLY SYSTEM HANDLERS
# ------------------------------------------

def action_system_identity(payload: Dict[str, Any]):
    return {
        "action": "system_identity",
        "response": {
            "type": "SYSTEM_IDENTITY",
            "summary": "Adnan.AI identity",
            "identity": {
                "name": "Adnan.AI",
                "role": "Digitalni klon / co-CEO / COO",
                "owner": "Adnan",
                "mode": "read-only",
            },
        },
    }


def action_system_query(payload: Dict[str, Any]):
    return {
        "action": "system_query",
        "response": {
            "type": "SYSTEM_READ_SNAPSHOT",
            "summary": "System is operational",
        },
    }


def action_system_notion_inbox(payload: Dict[str, Any]):
    notion: NotionService = payload.get("notion_service")
    if not notion:
        return {
            "action": "system_notion_inbox",
            "response": {
                "type": "ERROR",
                "summary": "Notion service not provided.",
            },
        }

    snapshot = notion.get_knowledge_snapshot() or {}
    tasks = snapshot.get("tasks", []) or []

    inbox = [
        {
            "id": t.get("id"),
            "name": t.get("name"),
        }
        for t in tasks
        if isinstance(t, dict)
        and isinstance(t.get("name"), str)
        and (
            "adnan.ai" in t["name"].lower()
            or "adnan ai" in t["name"].lower()
        )
    ]

    return {
        "action": "system_notion_inbox",
        "response": {
            "type": "NOTION_INBOX",
            "summary": f"Imam {len(inbox)} zadataka u Notion inboxu.",
            "count": len(inbox),
            "items": inbox,
            "last_sync": snapshot.get("last_sync"),
        },
    }


def action_system_inbox_delegation_preview(payload: Dict[str, Any]):
    notion: NotionService = payload.get("notion_service")
    if not notion:
        return {
            "action": "system_inbox_delegation_preview",
            "response": {
                "type": "ERROR",
                "summary": "Notion service not provided.",
            },
        }

    snapshot = notion.get_knowledge_snapshot() or {}
    tasks = snapshot.get("tasks", []) or []

    inbox = [
        {
            "title": t.get("name"),
            "source": "notion",
            "suggested_action": "Delegirati kao zadatak ili follow-up",
        }
        for t in tasks
        if isinstance(t, dict)
        and isinstance(t.get("name"), str)
        and (
            "adnan.ai" in t["name"].lower()
            or "adnan ai" in t["name"].lower()
        )
    ]

    return {
        "action": "system_inbox_delegation_preview",
        "response": {
            "type": "INBOX_DELEGATION_PREVIEW",
            "summary": f"Imam {len(inbox)} stavki koje mogu biti delegirane.",
            "count": len(inbox),
            "items": inbox,
            "last_sync": snapshot.get("last_sync"),
        },
    }


# ------------------------------------------
# ACTION DEFINITIONS (CANONICAL)
# ------------------------------------------
# PRAVILO:
# - READ → ima handler
# - WRITE → NEMA handler (delegira se agentima)

ACTION_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    # READ
    "system_identity": {
        "handler": action_system_identity,
        "category": "read",
        "allowed_owners": ["system"],
    },
    "system_query": {
        "handler": action_system_query,
        "category": "read",
        "allowed_owners": ["system"],
    },
    "system_notion_inbox": {
        "handler": action_system_notion_inbox,
        "category": "read",
        "allowed_owners": ["system"],
    },
    "system_inbox_delegation_preview": {
        "handler": action_system_inbox_delegation_preview,
        "category": "read",
        "allowed_owners": ["system"],
    },

    # WRITE (DELEGATED TO AGENTS)
    "goal_write": {
        "handler": None,              # ❗️NAMJERNO — delegira se NotionOpsAgent-u
        "category": "write",
        "allowed_owners": ["system"],
    },
    "update_goal": {
        "handler": None,
        "category": "write",
        "allowed_owners": ["system"],
    },

    # GENERIC NOTION WRITE/READ (create_page / update_page / query_database)
    "notion_write": {
        "handler": None,              # sve ide kroz NotionOpsAgent + NotionService
        "category": "write",
        "allowed_owners": ["system"],
    },

    # WORKFLOW (goal + taskovi) — KROZ AGENTA, NE DIREKTNO
    "goal_task_workflow": {
        "handler": None,
        "category": "write",
        "allowed_owners": ["system"],
    },
}


def is_valid_command(command: str) -> bool:
    return isinstance(command, str) and command in ACTION_DEFINITIONS


def get_action_definition(command: str) -> Optional[Dict[str, Any]]:
    if not isinstance(command, str):
        return None
    return ACTION_DEFINITIONS.get(command)


def get_action_handler(command: str) -> Optional[Callable]:
    definition = get_action_definition(command)
    if not definition:
        return None
    return definition.get("handler")
