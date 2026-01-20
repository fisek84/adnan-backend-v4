"""
NOTION SCHEMA REGISTRY â€” KANONSKI IZVOR ISTINE

Enhanced with bilingual property support (Bosnian â†” English)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from services.notion_keyword_mapper import NotionKeywordMapper


class NotionSchemaRegistry:
    """
    Centralni Notion knowledge layer.
    Svi DB-ovi/PAGE-ovi koji su dostupni OS-u moraju biti registrovani ovdje.

    object_type:
      - "database" (default): query_database
      - "page": retrieve_page (read-only)
    optional:
      - ako True, snapshot smije soft-skip bez __error spam-a kad nema access / object_not_found / page-not-db
    """

    # ============================================================
    # DATABASE/PAGE DEFINITIONS
    # ============================================================

    DATABASES: Dict[str, Dict[str, Any]] = {
        # =======================
        # GOALS (PRIMARNI DB)
        # =======================
        "goals": {
            "db_id": os.getenv("NOTION_GOALS_DB_ID"),
            "entity": "Goal",
            "object_type": "database",
            "optional": False,
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
        # GOALS â€” DERIVED VIEWS (READ-ONLY)
        # =======================
        # Fallback: ako posebni view DB_ID nije setovan, koristi primarni goals DB.
        "active_goals": {
            "db_id": os.getenv("NOTION_ACTIVE_GOALS_DB_ID")
            or os.getenv("NOTION_GOALS_DB_ID"),
            "entity": "Goal",
            "object_type": "database",
            "optional": True,
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
            "object_type": "database",
            "optional": True,
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
            "object_type": "database",
            "optional": True,
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
            "object_type": "database",
            "optional": False,
            "write_enabled": True,
            "identifiers": ["page_id", "Task ID"],
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
                "Goal Status": {"type": "select", "required": False, "read_only": True},
                "Auto Task Status": {
                    "type": "select",
                    "required": False,
                    "read_only": True,
                },
                "Overdue": {"type": "checkbox", "required": False, "read_only": True},
                "Is Completed?": {
                    "type": "checkbox",
                    "required": False,
                    "read_only": True,
                },
                "Progress % from Status": {
                    "type": "number",
                    "required": False,
                    "read_only": True,
                },
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
            "object_type": "database",
            "optional": False,
            "write_enabled": True,
            "identifiers": ["page_id", "Project Name"],
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
                "Goal Status (Auto)": {
                    "type": "select",
                    "required": False,
                    "read_only": True,
                },
                "Goal Progress (Auto)": {
                    "type": "number",
                    "required": False,
                    "read_only": True,
                },
                "Agent Exchange DB": {"type": "relation", "target": "agent_exchange"},
                "Tasks DB": {"type": "relation", "target": "tasks"},
                "Handled By": {"type": "people", "required": False},
            },
        },
        # =======================
        # OPTIONAL SOURCES (SNAPSHOT + WORKFLOWS)
        # =======================
        # NOTE: kpi_weekly_summary workflow ti trenutno pokuĹˇava pisati u ai_summary.
        # Zato ai_summary / ai_weekly_summary MORAJU biti write_enabled=True.
        "ai_summary": {
            "db_id": os.getenv("NOTION_AI_SUMMARY_DB_ID"),
            "entity": "AISummary",
            "object_type": "database",
            "optional": True,
            "write_enabled": True,  # <-- FIX: dozvoli pisanje
            "properties": {
                # Minimalni set: prilagodi imena ako tvoj DB koristi drugaÄŤije kolone
                "Name": {"type": "title", "required": True},
                "Summary": {"type": "rich_text", "required": False},
            },
        },
        "ai_weekly_summary": {
            "db_id": os.getenv("NOTION_AI_WEEKLY_SUMMARY_DB_ID")
            or os.getenv("NOTION_AI_SUMMARY_DB_ID"),
            "entity": "AIWeeklySummary",
            "object_type": "database",
            "optional": True,
            "write_enabled": True,  # <-- FIX: dozvoli pisanje
            "properties": {
                "Name": {"type": "title", "required": True},
                "Summary": {"type": "rich_text", "required": False},
            },
        },
        "kpi": {
            "db_id": os.getenv("NOTION_KPI_DB_ID"),
            "entity": "KPI",
            "object_type": "database",
            "optional": True,
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Value": {"type": "number", "required": False},
                "Unit": {"type": "select", "required": False},
                "As Of": {"type": "date", "required": False},
                "Notes": {"type": "rich_text", "required": False},
            },
        },
        "leads": {
            "db_id": os.getenv("NOTION_LEAD_DB_ID") or os.getenv("NOTION_LEADS_DB_ID"),
            "entity": "Lead",
            "object_type": "database",
            "optional": True,
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Status": {"type": "select", "required": False},
                "Email": {"type": "rich_text", "required": False},
                "Company": {"type": "rich_text", "required": False},
                "Source": {"type": "select", "required": False},
                "Created At": {"type": "date", "required": False},
            },
        },
        "agent_exchange": {
            "db_id": os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
            "entity": "AgentExchange",
            "object_type": "database",
            "optional": True,
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Status": {"type": "select", "required": False},
                "Summary": {"type": "rich_text", "required": False},
                "Created At": {"type": "date", "required": False},
                "Task": {"type": "relation", "target": "tasks"},
                "Project": {"type": "relation", "target": "projects"},
            },
        },
        "agent_project": {
            "db_id": os.getenv("NOTION_AGENT_PROJECT_DB_ID"),
            "entity": "AgentProject",
            "object_type": "database",
            "optional": True,
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Status": {"type": "select", "required": False},
                "Summary": {"type": "rich_text", "required": False},
                "Owner": {"type": "people", "required": False},
                "Project": {"type": "relation", "target": "projects"},
                "Created At": {"type": "date", "required": False},
            },
        },
        # =======================
        # SOP / OPS SOURCES (PAGES, NOT DATABASES)
        # =======================
        "outreach_sop": {
            "db_id": os.getenv("NOTION_OUTREACH_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "qualification_sop": {
            "db_id": os.getenv("NOTION_QUALIFICATION_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "follow_up_sop": {
            "db_id": os.getenv("NOTION_FOLLOW_UP_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "fsc_sop": {
            "db_id": os.getenv("NOTION_FSC_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "flp_ops_sop": {
            "db_id": os.getenv("NOTION_FLP_OPS_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "lss_sop": {
            "db_id": os.getenv("NOTION_LSS_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "partner_activation_sop": {
            "db_id": os.getenv("NOTION_PARTNER_ACTIVATION_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "partner_performance_sop": {
            "db_id": os.getenv("NOTION_PARTNER_PERFORMANCE_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "partner_leadership_sop": {
            "db_id": os.getenv("NOTION_PARTNER_LEADERSHIP_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "partner_potential_sop": {
            "db_id": os.getenv("NOTION_PARTNER_POTENTIAL_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "customer_onboarding_sop": {
            "db_id": os.getenv("NOTION_CUSTOMER_ONBOARDING_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "customer_retention_sop": {
            "db_id": os.getenv("NOTION_CUSTOMER_RETENTION_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "customer_performance_sop": {
            "db_id": os.getenv("NOTION_CUSTOMER_PERFORMANCE_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        "sales_closing_sop": {
            "db_id": os.getenv("NOTION_SALES_CLOSING_SOP_DB_ID"),
            "entity": "SOP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
        },
        # FLP (u tvom outputu je "page, not database" -> tretiramo kao page)
        "flp": {
            "db_id": os.getenv("NOTION_FLP_DB_ID"),
            "entity": "FLP",
            "object_type": "page",
            "optional": True,
            "write_enabled": False,
            "properties": {},
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

        # payload validation only applies to databases used for create/update
        if db.get("object_type") != "database":
            raise ValueError(
                f"Notion key '{db_key}' is not a database (object_type={db.get('object_type')})."
            )

        if db.get("write_enabled") is False:
            raise ValueError(
                f"Notion DB '{db_key}' is write_disabled (write_enabled=False)."
            )

        props = db.get("properties") or {}
        for name, spec in props.items():
            if (
                spec.get("required")
                and spec.get("read_only") is not True
                and name not in payload
            ):
                raise ValueError(
                    f"Missing required Notion property '{name}' for DB '{db_key}'"
                )
        for k in payload:
            if k not in props:
                raise ValueError(
                    f"Property '{k}' is not defined in schema for DB '{db_key}'"
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
        db_props = db.get("properties") or {}

        for prop, value in properties.items():
            if db_props.get(prop, {}).get("read_only") is True:
                continue

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

    # ============================================================
    # BILINGUAL SUPPORT (Bosnian â†” English)
    # ============================================================

    @classmethod
    def translate_properties_payload(
        cls, payload: Dict[str, Any], db_key: str
    ) -> Dict[str, Any]:
        """
        Translate property names from Bosnian to English for a given database.

        This enables users to submit requests in Bosnian and have them
        automatically mapped to the correct Notion property names.

        Args:
            payload: Dictionary with potentially Bosnian property names
            db_key: Target database key (e.g., 'tasks', 'goals')

        Returns:
            Payload with English Notion property names
        """
        db = cls.get_db(db_key)
        db_props = db.get("properties") or {}

        translated = {}

        for key, value in payload.items():
            # Try to translate the property name
            notion_prop_name = NotionKeywordMapper.normalize_field_name(key)

            # Check if this property exists in the database schema
            if notion_prop_name in db_props:
                # Also translate value if needed
                if isinstance(value, str):
                    prop_type = db_props[notion_prop_name].get("type")
                    if prop_type in ("status", "select"):
                        # Try to translate status/priority values
                        internal_key = NotionKeywordMapper.translate_property_name(key)
                        if internal_key in ("status", "task_status"):
                            value = NotionKeywordMapper.translate_status_value(value)
                        elif internal_key == "priority":
                            value = NotionKeywordMapper.translate_priority_value(value)

                translated[notion_prop_name] = value
            else:
                # Keep original if no mapping found
                translated[key] = value

        return translated

    @classmethod
    def normalize_create_payload(
        cls, payload: Dict[str, Any], db_key: str
    ) -> Dict[str, Any]:
        """
        Normalize and translate a create payload for a database.

        Handles both Bosnian and English inputs, translating as needed.

        Args:
            payload: Raw payload from user (potentially in Bosnian)
            db_key: Target database key

        Returns:
            Normalized payload ready for Notion API
        """
        # First translate Bosnian to English
        translated = cls.translate_properties_payload(payload, db_key)

        return translated
