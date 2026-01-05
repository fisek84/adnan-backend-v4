"""
NOTION SCHEMA REGISTRY — KANONSKI IZVOR ISTINE
"""

from __future__ import annotations
import os
from typing import Any, Dict, List, Optional


class NotionSchemaRegistry:
    """
    Centralni Notion knowledge layer.
    Svi DB-ovi koji su dostupni OS-u moraju biti registrovani ovdje.
    """

    # ============================================================
    # DATABASE DEFINITIONS
    # ============================================================

    DATABASES: Dict[str, Dict[str, Any]] = {
        # =======================
        # GOALS (PRIMARNI DB)
        # =======================
        "goals": {
            "db_id": os.getenv("NOTION_GOALS_DB_ID"),
            "entity": "Goal",
            "write_enabled": True,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Status": {"type": "status", "required": True},
                "Priority": {"type": "select", "required": False},
                "Progress": {"type": "number", "required": False},
                "Description": {"type": "rich_text", "required": False},
                "Parent Goal": {"type": "relation", "target": "goals"},
                "Child Goals": {"type": "relation", "target": "goals"},
                "Project": {"type": "relation", "target": "projects"},
                "Deadline": {"type": "date", "required": False},
            },
        },
        # =======================
        # GOALS — DERIVED VIEWS (READ-ONLY)
        # =======================
        # Fallback: ako posebni view DB_ID nije setovan, koristi primarni goals DB.
        "active_goals": {
            "db_id": os.getenv("NOTION_ACTIVE_GOALS_DB_ID")
            or os.getenv("NOTION_GOALS_DB_ID"),
            "entity": "Goal",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Status": {"type": "status", "required": False},
                "Assigned To": {"type": "people", "required": False},
                "Parent Goal": {"type": "relation", "target": "goals"},
                "Child Goals": {"type": "relation", "target": "goals"},
                "Level": {"type": "select", "required": False},
                "Outcome Result": {"type": "rich_text", "required": False},
                "Description": {"type": "rich_text", "required": False},
                "Progress &": {"type": "number", "required": False},
                "Child Progress %": {"type": "number", "required": False},
                "Task Progress List": {"type": "rich_text", "required": False},
                "Progress % from Tasks": {"type": "number", "required": False},
                "Activity Progress %": {"type": "number", "required": False},
                "Outcome": {"type": "rich_text", "required": False},
                "Goal State (Auto)": {"type": "select", "required": False},
                "Outcome State": {"type": "select", "required": False},
                "Child Status List": {"type": "rich_text", "required": False},
                "Child State %": {"type": "number", "required": False},
                "Parent State": {"type": "select", "required": False},
                "Context State": {"type": "select", "required": False},
                "Activity State": {"type": "select", "required": False},
                "Owner State": {"type": "select", "required": False},
                "Activity Lane": {"type": "select", "required": False},
                "Child State Values": {"type": "rich_text", "required": False},
                "Deadline": {"type": "date", "required": False},
                "Type": {"type": "select", "required": False},
                "Auto Status": {"type": "select", "required": False},
                "Progress": {"type": "number", "required": False},
                "Priority": {"type": "select", "required": False},
                "Progress from Tasks": {"type": "number", "required": False},
                "Auto Status (Calc)": {"type": "number", "required": False},
                "Activity State (Auto)": {"type": "select", "required": False},
                "Parent Progress (Rollup)": {"type": "number", "required": False},
                "Completed At": {"type": "date", "required": False},
                "Category": {"type": "select", "required": False},
                "Completed Tasks": {"type": "number", "required": False},
                "Related Goal": {"type": "relation", "target": "goals"},
                "Tasks DB": {"type": "relation", "target": "tasks"},
                "AI Agent": {"type": "people", "required": False},
            },
        },
        "blocked_goals": {
            "db_id": os.getenv("NOTION_BLOCKED_GOALS_DB_ID")
            or os.getenv("NOTION_GOALS_DB_ID"),
            "entity": "Goal",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Status": {"type": "status", "required": False},
                "Priority": {"type": "select", "required": False},
                "Deadline": {"type": "date", "required": False},
            },
        },
        "completed_goals": {
            "db_id": os.getenv("NOTION_COMPLETED_GOALS_DB_ID")
            or os.getenv("NOTION_GOALS_DB_ID"),
            "entity": "Goal",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Status": {"type": "status", "required": False},
                "Completed At": {"type": "date", "required": False},
                "Priority": {"type": "select", "required": False},
            },
        },
        # =======================
        # TASKS
        # =======================
        "tasks": {
            "db_id": os.getenv("NOTION_TASKS_DB_ID"),
            "entity": "Task",
            "write_enabled": True,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Status": {"type": "select", "required": True},
                "Priority": {"type": "select", "required": False},
                "Description": {"type": "rich_text", "required": False},
                "Due Date": {"type": "date", "required": False},
                "Order": {"type": "number", "required": False},
                "Goal": {"type": "relation", "target": "goals"},
                "Project": {"type": "relation", "target": "projects"},
                "Agent Exchange DB": {"type": "relation", "target": "agent_exchange"},
                "Goal Status": {"type": "select", "required": False},
                "Auto Task Status": {"type": "select", "required": False},
                "Overdue": {"type": "checkbox", "required": False},
                "Is Completed?": {"type": "checkbox", "required": False},
                "Progress % from Status": {"type": "number", "required": False},
                "Deadline": {"type": "date", "required": False},
                "Agent Notes": {"type": "rich_text", "required": False},
                "Task ID": {"type": "rich_text", "required": False},
                "AI Agent": {"type": "people", "required": False},
            },
        },
        # =======================
        # PROJECTS
        # =======================
        "projects": {
            "db_id": os.getenv("NOTION_PROJECTS_DB_ID"),
            "entity": "Project",
            "write_enabled": True,
            "properties": {
                "Project Name": {"type": "title", "required": True},
                "Status": {"type": "select", "required": True},
                "Category": {"type": "select", "required": False},
                "Priority": {"type": "select", "required": False},
                "Start Date": {"type": "date", "required": False},
                "Target Deadline": {"type": "date", "required": False},
                "Progress": {"type": "number", "required": False},
                "CEO Notes": {"type": "rich_text", "required": False},
                "Deliverables": {"type": "rich_text", "required": False},
                "KPI": {"type": "relation", "target": "kpi"},
                "AI Commands": {"type": "rich_text", "required": False},
                "Energy Required": {"type": "number", "required": False},
                "Company": {"type": "rich_text", "required": False},
                "Archive": {"type": "checkbox", "required": False},
                "Project Type": {"type": "select", "required": False},
                "Summary": {"type": "rich_text", "required": False},
                "Next Step": {"type": "rich_text", "required": False},
                "Primary Goal": {"type": "relation", "target": "goals"},
                "Goal Status (Auto)": {"type": "select", "required": False},
                "Goal Progress (Auto)": {"type": "number", "required": False},
                "Agent Exchange DB": {"type": "relation", "target": "agent_exchange"},
                "Tasks DB": {"type": "relation", "target": "tasks"},
                "Handled By": {"type": "people", "required": False},
            },
        },
    }

    # ============================================================
    # VALIDATION
    # ============================================================

    @classmethod
    def get_db(cls, key: str) -> Dict[str, Any]:
        if key not in cls.DATABASES:
            raise ValueError(f"Unknown Notion DB key: {key}")
        return cls.DATABASES[key]

    @classmethod
    def validate_payload(cls, db_key: str, payload: Dict[str, Any]) -> bool:
        db = cls.get_db(db_key)
        props = db["properties"]
        for name, spec in props.items():
            if spec.get("required") and name not in payload:
                raise ValueError(
                    f"Missing required Notion property '{name}' for DB '{db_key}'"
                )
        for key in payload:
            if key not in props:
                raise ValueError(
                    f"Property '{key}' is not defined in schema for DB '{db_key}'"
                )
        return True

    # ============================================================
    # PAYLOAD BUILDER
    # ============================================================

    @classmethod
    def build_create_page_payload(
        cls,
        *,
        db_key: str,
        properties: Dict[str, Any],
        relations: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        cls.validate_payload(db_key, properties)
        db = cls.get_db(db_key)
        notion_props: Dict[str, Any] = {}
        db_props = db["properties"]

        for prop, value in properties.items():
            p_type = db_props[prop]["type"]
            if p_type == "select_or_date":
                p_type = "select"
            if p_type == "title":
                notion_props[prop] = {"title": [{"text": {"content": str(value)}}]}
            elif p_type == "rich_text":
                notion_props[prop] = {"rich_text": [{"text": {"content": str(value)}}]}
            elif p_type == "select":
                if value is not None:
                    notion_props[prop] = {"select": {"name": str(value)}}
            elif p_type == "multi_select":
                if value:
                    notion_props[prop] = {
                        "multi_select": [
                            {"name": str(v)}
                            for v in (value if isinstance(value, list) else [value])
                        ]
                    }
            elif p_type == "status":
                notion_props[prop] = {"select": {"name": str(value or "Not started")}}
            elif p_type == "number":
                notion_props[prop] = {"number": value}
            elif p_type == "date":
                notion_props[prop] = {"date": {"start": value}}
            elif p_type == "relation":
                ids = relations.get(prop, []) if relations else []
                notion_props[prop] = {"relation": [{"id": rid} for rid in ids]}
            elif p_type == "people":
                notion_props[prop] = {"people": value}
            elif p_type == "checkbox":
                notion_props[prop] = {"checkbox": bool(value)}
            elif p_type == "files":
                notion_props[prop] = {"files": value}
            else:
                raise ValueError(f"Unsupported Notion property type: {p_type}")

        return {
            "parent": {"database_id": db["db_id"]},
            "properties": notion_props,
        }
