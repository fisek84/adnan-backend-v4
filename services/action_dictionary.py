from typing import Callable, Dict, Optional, Any
from services.notion_service import NotionService


# ------------------------------------------
# READ-ONLY SYSTEM HANDLERS
# ------------------------------------------

def action_system_identity(payload: Dict[str, Any]):
    return {
        "execution_state": "COMPLETED",
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
        "execution_state": "COMPLETED",
        "action": "system_query",
        "response": {
            "type": "SYSTEM_READ_SNAPSHOT",
            "summary": "System is operational",
        },
    }


def action_system_notion_inbox(payload: Dict[str, Any]):
    """
    READ-ONLY Notion inbox scan.
    """
    notion: NotionService = payload["notion_service"]

    snapshot = notion.get_knowledge_snapshot()
    tasks = snapshot.get("tasks", [])

    inbox = [
        {
            "id": t["id"],
            "name": t["name"],
        }
        for t in tasks
        if "adnan.ai" in t["name"].lower()
        or "adnan ai" in t["name"].lower()
    ]

    return {
        "execution_state": "COMPLETED",
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
    """
    READ-ONLY delegation preview from Notion inbox.
    NO execution, NO decision.
    """
    notion: NotionService = payload["notion_service"]

    snapshot = notion.get_knowledge_snapshot()
    tasks = snapshot.get("tasks", [])

    inbox = [
        {
            "title": t["name"],
            "source": "notion",
            "suggested_action": "Delegirati kao zadatak ili follow-up",
        }
        for t in tasks
        if "adnan.ai" in t["name"].lower()
        or "adnan ai" in t["name"].lower()
    ]

    return {
        "execution_state": "COMPLETED",
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
# ACTION DEFINITIONS
# ------------------------------------------

ACTION_DEFINITIONS = {

    "system_identity": {
        "handler": action_system_identity,
        "category": "read",
    },

    "system_query": {
        "handler": action_system_query,
        "category": "read",
    },

    "system_notion_inbox": {
        "handler": action_system_notion_inbox,
        "category": "read",
    },

    "system_inbox_delegation_preview": {
        "handler": action_system_inbox_delegation_preview,
        "category": "read",
    },
}


def is_valid_command(command: str) -> bool:
    return command in ACTION_DEFINITIONS


def get_action_definition(command: str) -> Optional[Dict[str, Any]]:
    return ACTION_DEFINITIONS.get(command)


def get_action_handler(command: str) -> Optional[Callable]:
    d = ACTION_DEFINITIONS.get(command)
    return d["handler"] if d else None
