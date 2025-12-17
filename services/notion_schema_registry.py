"""
NOTION SCHEMA REGISTRY — KANONSKI IZVOR ISTINE
"""

from typing import Dict, Any, List, Optional
import os


class NotionSchemaRegistry:
    """
    Centralni Notion knowledge layer.
    """

    # ============================================================
    # DATABASE DEFINITIONS
    # ============================================================

    DATABASES: Dict[str, Dict[str, Any]] = {

        # =======================
        # GOALS
        # =======================
        "goals": {
            "db_id": os.getenv("NOTION_GOALS_DB_ID"),
            "entity": "Goal",
            "write_enabled": True,
            "properties": {
                "Name":        {"type": "title", "required": True},
                "Status":      {"type": "status", "required": True},
                "Priority":    {"type": "select", "required": False},
                "Progress":    {"type": "number", "required": False},
                "Description": {"type": "rich_text", "required": False},
                "Parent Goal": {"type": "relation", "target": "goals"},
                "Child Goals": {"type": "relation", "target": "goals"},
                "Project":     {"type": "relation", "target": "projects"},
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
                "Name":        {"type": "title", "required": True},
                "Status":      {"type": "select", "required": True},
                "Priority":    {"type": "select", "required": False},
                "Description": {"type": "rich_text", "required": False},
                "Due Date":    {"type": "date", "required": False},
                "Order":       {"type": "number", "required": False},
                "Goal":        {"type": "relation", "target": "goals"},
                "Project":     {"type": "relation", "target": "projects"},
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
                "Name":        {"type": "title", "required": True},
                "Status":      {"type": "select", "required": True},
                "Owner":       {"type": "people", "required": False},
                "Description": {"type": "rich_text", "required": False},
                "Goals":       {"type": "relation", "target": "goals"},
                "Tasks":       {"type": "relation", "target": "tasks"},
            },
        },

        # =======================
        # KPI
        # =======================
        "kpi": {
            "db_id": os.getenv("NOTION_KPI_DB_ID"),
            "entity": "KPI",
            "write_enabled": True,
            "properties": {
                "Name":        {"type": "title", "required": True},
                "Value":       {"type": "number", "required": True},
                "Target":      {"type": "number", "required": False},
                "Period":      {"type": "select", "required": True},
                "Notes":       {"type": "rich_text", "required": False},
                "Project":     {"type": "relation", "target": "projects"},
                "Goal":        {"type": "relation", "target": "goals"},
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
    def validate_payload(cls, db_key: str, payload: Dict[str, Any]):
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

        for prop, value in properties.items():
            p_type = db["properties"][prop]["type"]

            if p_type == "title":
                notion_props[prop] = {
                    "title": [{"text": {"content": str(value)}}]
                }

            elif p_type == "rich_text":
                notion_props[prop] = {
                    "rich_text": [{"text": {"content": str(value)}}]
                }

            elif p_type == "select":
                if value is not None:
                    notion_props[prop] = {"select": {"name": str(value)}}

            elif p_type == "status":
                notion_props[prop] = {
                    "status": {"name": value or "Not started"}
                }

            elif p_type == "number":
                notion_props[prop] = {"number": value}

            elif p_type == "date":
                notion_props[prop] = {"date": {"start": value}}

            elif p_type == "relation":
                ids = relations.get(prop, []) if relations else []
                notion_props[prop] = {
                    "relation": [{"id": rid} for rid in ids]
                }

            elif p_type == "people":
                notion_props[prop] = {"people": value}

            else:
                raise ValueError(f"Unsupported Notion property type: {p_type}")

        return {
            "parent": {"database_id": db["db_id"]},
            "properties": notion_props,
        }
