from typing import List, Dict, Any
from notion_client import Client
import os

# Notion authentication
notion = Client(auth=os.getenv("NOTION_TOKEN"))

# Database ID for Goals DB (from .env)
GOALS_DB = os.getenv("NOTION_GOALS_DB_ID")


# ============================================================
# GET ALL GOALS — FLAT LIST
# ============================================================
def get_all_goals() -> List[Dict[str, Any]]:
    """
    Returns a simple flat list of Notion goals.
    """
    result = notion.databases.query(database_id=GOALS_DB)
    items = result.get("results", [])

    goals = []

    for item in items:
        props = item["properties"]

        goals.append({
            "id": item["id"],
            "name": props["Name"]["title"][0]["plain_text"]
                if props["Name"]["title"] else "",
            "status": props.get("Status", {}).get("status", {}).get("name"),
            "priority": props.get("Priority", {}).get("select", {}).get("name"),
            "progress": props.get("Progress", {}).get("number"),
        })

    return goals


# ============================================================
# GET FULL GOALS — WITH PARENT/CHILD LINKS
# ============================================================
def get_full_goals() -> List[Dict[str, Any]]:
    """
    Returns detailed goals including parent/child relations + description.
    """
    result = notion.databases.query(database_id=GOALS_DB)
    items = result.get("results", [])

    full = []

    for item in items:
        props = item["properties"]

        full.append({
            "id": item["id"],
            "name": props["Name"]["title"][0]["plain_text"]
                if props["Name"]["title"] else "",
            "status": props.get("Status", {}).get("status", {}).get("name"),
            "priority": props.get("Priority", {}).get("select", {}).get("name"),
            "progress": props.get("Progress", {}).get("number"),
            "description": props.get("Description", {}).get("rich_text", [{}])[0].get("plain_text", ""),
            "parent_goal": props.get("Parent Goal", {}).get("relation", []),
            "child_goals": props.get("Child Goals", {}).get("relation", []),
        })

    return full


# ============================================================
# GET SUBGOALS — ONLY GOALS WITH PARENT
# ============================================================
def get_subgoals() -> List[Dict[str, Any]]:
    """
    Returns only subgoals (goals that have a Parent Goal relation).
    """
    result = notion.databases.query(database_id=GOALS_DB)
    items = result.get("results", [])

    subs = []

    for item in items:
        props = item["properties"]
        parent_rel = props.get("Parent Goal", {}).get("relation", [])

        if parent_rel:  # goal has a parent
            subs.append({
                "id": item["id"],
                "name": props["Name"]["title"][0]["plain_text"]
                    if props["Name"]["title"] else "",
                "parent": parent_rel[0]["id"],
                "status": props.get("Status", {}).get("status", {}).get("name"),
                "progress": props.get("Progress", {}).get("number"),
            })

    return subs