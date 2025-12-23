"""
NOTION SCHEMA REGISTRY — KANONSKI IZVOR ISTINE
"""

from typing import Dict, Any, List, Optional
import os


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
                # osnovno
                "Name": {"type": "title", "required": True},
                "Status": {"type": "status", "required": True},
                "Priority": {"type": "select", "required": False},
                "Progress": {"type": "number", "required": False},
                "Description": {"type": "rich_text", "required": False},
                # hijerarhija
                "Parent Goal": {"type": "relation", "target": "goals"},
                "Child Goals": {"type": "relation", "target": "goals"},
                "Project": {"type": "relation", "target": "projects"},
                # operativno
                "Deadline": {"type": "date", "required": False},
            },
        },
        # =======================
        # GOALS — DERIVED VIEWS
        # (read-only iz perspektive OS-a)
        # =======================
        "active_goals": {
            "db_id": os.getenv("NOTION_ACTIVE_GOALS_DB_ID"),
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
                # Napomena: dodatne rollup relacije (Goals DB — Central ...,
                # Related back to Goal..., AI Summary DB) su izostavljene iz
                # eksplicitnog mapiranja jer su read-only rollup/relacije koje
                # OS neće direktno pisati.
            },
        },
        "blocked_goals": {
            "db_id": os.getenv("NOTION_BLOCKED_GOALS_DB_ID"),
            "entity": "Goal",
            "write_enabled": False,
            "properties": {
                # ista struktura kao active_goals; dovoljan je subset
                "Name": {"type": "title", "required": True},
                "Status": {"type": "status", "required": False},
                "Priority": {"type": "select", "required": False},
                "Deadline": {"type": "date", "required": False},
            },
        },
        "completed_goals": {
            "db_id": os.getenv("NOTION_COMPLETED_GOALS_DB_ID"),
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
                # osnovno
                "Name": {"type": "title", "required": True},
                "Status": {"type": "select", "required": True},
                "Priority": {"type": "select", "required": False},
                "Description": {"type": "rich_text", "required": False},
                "Due Date": {"type": "date", "required": False},
                "Order": {"type": "number", "required": False},
                # povezanost
                "Goal": {"type": "relation", "target": "goals"},
                "Project": {"type": "relation", "target": "projects"},
                "Agent Exchange DB": {"type": "relation", "target": "agent_exchange"},
                # operativno
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
        # =======================
        # KPI (WEEKLY KPI DB)
        # =======================
        "kpi": {
            "db_id": os.getenv("NOTION_KPI_DB_ID"),
            "entity": "KPI",
            "write_enabled": True,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Period": {"type": "select", "required": True},
                "Cycle": {"type": "select", "required": False},
                "Status": {"type": "select", "required": False},
                "KPI Type": {"type": "select", "required": False},
                # ključne metrike (sve number)
                "Outreach": {"type": "number", "required": False},
                "FUCompletion": {"type": "number", "required": False},
                "ConversionsCount": {"type": "number", "required": False},
                "PartnerActivation": {"type": "number", "required": False},
                "CashflowBAM": {"type": "number", "required": False},
                "Review": {"type": "number", "required": False},
                "SystemDevelopmentScore": {"type": "number", "required": False},
                "ElementsBuilt": {"type": "number", "required": False},
                "LeadInflow": {"type": "number", "required": False},
                "RevenueMomentum": {"type": "number", "required": False},
                "Alignment5KScore": {"type": "number", "required": False},
                "Readiness700K": {"type": "number", "required": False},
                "Alignment10M": {"type": "number", "required": False},
                # blokatori / refleksija
                "Blockers": {"type": "rich_text", "required": False},
                "EcosystemReflection": {"type": "rich_text", "required": False},
                "Meditation": {"type": "number", "required": False},
                "FocusSession": {"type": "number", "required": False},
                "Distractions": {"type": "number", "required": False},
                "PagesRead": {"type": "number", "required": False},
                "LearningMinutes": {"type": "number", "required": False},
                "NewSkill": {"type": "number", "required": False},
                "IdentityAction": {"type": "number", "required": False},
                "Energy": {"type": "number", "required": False},
                "Stress": {"type": "number", "required": False},
                "EmotionalStability": {"type": "number", "required": False},
                "SelfControl": {"type": "number", "required": False},
                "PersonalReflection": {"type": "rich_text", "required": False},
                # AI / agency metrike
                "AIAgentsCreated": {"type": "number", "required": False},
                "AgencyColdOutreach": {"type": "number", "required": False},
                "AgencyScore": {"type": "number", "required": False},
                "AgencyWarmOutreach": {"type": "number", "required": False},
                "CRMWorkflowsBuilt": {"type": "number", "required": False},
                "ClientSessions": {"type": "number", "required": False},
                "ConsultingCalls": {"type": "number", "required": False},
                "ConsultingScore": {"type": "number", "required": False},
                "DiscoveryCalls": {"type": "number", "required": False},
                "OPStandardization": {"type": "number", "required": False},
                "Formula": {"type": "number", "required": False},
                "Daily Score": {"type": "number", "required": False},
            },
        },
        # =======================
        # AGENT EXCHANGE LAYER
        # =======================
        "agent_exchange": {
            "db_id": os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
            "entity": "AgentExchange",
            "write_enabled": True,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Sender": {"type": "people", "required": False},
                "Recipient": {"type": "people", "required": False},
                "Project": {"type": "relation", "target": "projects"},
                "Status": {"type": "select", "required": False},
                "Department Stage": {"type": "select", "required": False},
                "Content": {"type": "rich_text", "required": False},
                "Attachment": {"type": "files", "required": False},
                "Version": {"type": "number", "required": False},
                "Timestamp": {"type": "date", "required": False},
                "Thread / Lineage ID": {"type": "rich_text", "required": False},
                "AI Command Log": {"type": "rich_text", "required": False},
                "Action Type": {"type": "select", "required": False},
                "Agent Output": {"type": "rich_text", "required": False},
                "Agent Response Log": {"type": "rich_text", "required": False},
                "Pipeline Flow": {"type": "select", "required": False},
                "Priority": {"type": "select", "required": False},
                "Related Project": {"type": "relation", "target": "projects"},
                "Related Tasks": {"type": "relation", "target": "tasks"},
                "Version History": {"type": "rich_text", "required": False},
            },
        },
        "agent_projects": {
            "db_id": os.getenv("NOTION_AGENT_PROJECTS_DB_ID"),
            "entity": "AgentProject",
            "write_enabled": True,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Description": {"type": "rich_text", "required": False},
                "Agent": {"type": "people", "required": False},
                "Start Date": {"type": "date", "required": False},
                "Due Date": {"type": "date", "required": False},
                "Priority": {"type": "select", "required": False},
                "Pipeline Flow": {"type": "select", "required": False},
                "Status": {"type": "select", "required": False},
                "Agent Exchange DB": {"type": "relation", "target": "agent_exchange"},
                "Version History": {"type": "rich_text", "required": False},
                "Latest Exchange": {"type": "rich_text", "required": False},
                "Agent Output": {"type": "rich_text", "required": False},
                "Latest Output Check": {"type": "date", "required": False},
                "Latest Pipeline Output": {"type": "rich_text", "required": False},
                "Pipeline Auto": {"type": "select", "required": False},
                "Status Auto": {"type": "select", "required": False},
            },
        },
        "ai_summary": {
            "db_id": os.getenv("NOTION_AI_WEEKLY_SUMMARY_DB_ID"),
            "entity": "AISummary",
            "write_enabled": True,
            "properties": {
                "Name": {"type": "title", "required": True},
                "Summary": {"type": "rich_text", "required": True},
                "AI Agent": {"type": "people", "required": False},
                "Related Goals": {"type": "relation", "target": "goals"},
                "Tags": {"type": "multi_select", "required": False},
            },
        },
        # =======================
        # SOP BAZE (READ-ONLY)
        # =======================
        "outreach_sop": {
            "db_id": os.getenv("NOTION_OUTREACH_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "qualification_sop": {
            "db_id": os.getenv("NOTION_QUALIFICATION_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "follow_up_sop": {
            "db_id": os.getenv("NOTION_FOLLOW_UP_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "fsc_sop": {
            "db_id": os.getenv("NOTION_FSC_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "flp_ops_sop": {
            "db_id": os.getenv("NOTION_FLP_OPS_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "lss_sop": {
            "db_id": os.getenv("NOTION_LSS_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "partner_activation_sop": {
            "db_id": os.getenv("NOTION_PARTNER_ACTIVATION_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "partner_performance_sop": {
            "db_id": os.getenv("NOTION_PARTNER_PERFORMANCE_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "partner_leadership_sop": {
            "db_id": os.getenv("NOTION_PARTNER_LEADERSHIP_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "customer_onboarding_sop": {
            "db_id": os.getenv("NOTION_CUSTOMER_ONBOARDING_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "customer_retention_sop": {
            "db_id": os.getenv("NOTION_CUSTOMER_RETENTION_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "customer_performance_sop": {
            "db_id": os.getenv("NOTION_CUSTOMER_PERFORMANCE_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "partner_potential_sop": {
            "db_id": os.getenv("NOTION_PARTNER_POTENTIAL_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
            },
        },
        "sales_closing_sop": {
            "db_id": os.getenv("NOTION_SALES_CLOSING_SOP_DB_ID"),
            "entity": "SOP",
            "write_enabled": False,
            "properties": {
                "Name": {"type": "title", "required": True},
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
        db_props = db["properties"]

        for prop, value in properties.items():
            p_type = db_props[prop]["type"]

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
                notion_props[prop] = {"status": {"name": value or "Not started"}}

            elif p_type == "number":
                notion_props[prop] = {"number": value}

            elif p_type == "date":
                notion_props[prop] = {"date": {"start": value}}

            elif p_type == "relation":
                ids = relations.get(prop, []) if relations else []
                notion_props[prop] = {"relation": [{"id": rid} for rid in ids]}

            elif p_type == "people":
                # očekuje listu user objekata ili user_id vrijednosti;
                # ovdje samo prosljeđujemo raw value Notion SDK-u.
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
