"""
COO TRANSLATION SERVICE (CANONICAL)
"""

from typing import Optional, Dict, Any
import re

from models.ai_command import AICommand
from services.intent_classifier import IntentClassifier
from services.intent_contract import Intent, IntentType
from services.action_dictionary import is_valid_command


class COOTranslationService:
    READ_ONLY_COMMAND = "system_query"

    CEO_READ_ONLY_MATCHES = {
        "SYSTEM SNAPSHOT: goals": "goals",
        "SYSTEM SNAPSHOT: tasks": "tasks",
        "SYSTEM SNAPSHOT: agents": "agents",
        "SYSTEM STATUS": "status",
        "SYSTEM MODE": "mode",
    }

    def __init__(self):
        self.intent_classifier = IntentClassifier()

    def translate(
        self,
        raw_input: str,
        *,
        source: str,
        context: Dict[str, Any],
    ) -> Optional[AICommand]:

        text = (raw_input or "").strip()
        lowered = text.lower()
        context = context or {}

        # -----------------------------------------------------
        # 0) CEO READ-ONLY HARD MATCH
        # -----------------------------------------------------
        if text in self.CEO_READ_ONLY_MATCHES:
            if not is_valid_command(self.READ_ONLY_COMMAND):
                return None

            return AICommand(
                command=self.READ_ONLY_COMMAND,
                read_only=True,
                params={
                    "snapshot_type": self.CEO_READ_ONLY_MATCHES[text],
                },
                metadata={"context_type": "system"},
                validated=True,
            )

        # -----------------------------------------------------
        # 0B) DIRECT NOTION TASK CREATE (CEO → Notion Ops, Tasks DB)
        #     "kreiraj task ..." / "create task ..."
        # -----------------------------------------------------
        m_task = re.match(r"^\s*(kreiraj|create)\s+task[:\-]?\s*(.+)$", text, re.IGNORECASE)
        if m_task:
            tail = m_task.group(2).strip()

            # Default: cijeli ostatak je naziv taska
            name = tail
            priority = None
            status = None
            due_date = None

            # PRIORITY
            m_prio = re.search(r"\bpriority\b[:\-]?\s*([^,;]+)", tail, re.IGNORECASE)
            if m_prio:
                priority = m_prio.group(1).strip()

            # STATUS
            m_status = re.search(r"\bstatus\b[:\-]?\s*([^,;]+)", tail, re.IGNORECASE)
            if m_status:
                status = m_status.group(1).strip()

            # DUE DATE / ROK / DEADLINE
            m_due = re.search(r"\b(due date|rok|deadline)\b[:\-]?\s*([^,;]+)", tail, re.IGNORECASE)
            if m_due:
                due_date = m_due.group(2).strip()

            # Iz naziva taska izbacimo “priority/status/due date …” dio
            cut_idx = None
            for kw in [" priority", " status", " due date", " rok", " deadline"]:
                idx = tail.lower().find(kw)
                if idx != -1:
                    cut_idx = idx if cut_idx is None else min(cut_idx, idx)
            if cut_idx is not None:
                name = tail[:cut_idx].strip(" ,;-")

            # DSL za Notion properties
            property_specs: Dict[str, Dict[str, Any]] = {
                "Name": {
                    "type": "title",
                    "text": name or tail,
                }
            }

            if status:
                property_specs["Status"] = {
                    "type": "select",
                    "name": status,
                }

            if priority:
                property_specs["Priority"] = {
                    "type": "select",
                    "name": priority,
                }

            if due_date:
                # Očekujemo ISO string (npr. 2025-12-25) – Notion date
                property_specs["Due Date"] = {
                    "type": "date",
                    "start": due_date,
                }

            return AICommand(
                command="notion_write",
                intent="create_page",
                read_only=False,
                params={
                    "db_key": "tasks",           # NOTION_TASKS_DB_ID
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system"},
                validated=True,
            )

        # -----------------------------------------------------
        # 1) INTENT CLASSIFICATION
        # -----------------------------------------------------
        intent: Intent = self.intent_classifier.classify(
            raw_input, source=source
        )

        if intent.confidence < self.intent_classifier.DEFAULT_CONFIDENCE_THRESHOLD:
            return None

        if not intent.is_executable:
            return None

        # -----------------------------------------------------
        # 2) SYSTEM QUERY (READ-ONLY)
        # -----------------------------------------------------
        if intent.type == IntentType.SYSTEM_QUERY:
            if not is_valid_command(self.READ_ONLY_COMMAND):
                return None

            return AICommand(
                command=self.READ_ONLY_COMMAND,
                read_only=True,
                params={},
                metadata={"context_type": "system"},
                validated=True,
            )

        # -----------------------------------------------------
        # 3) GOALS LIST (READ)
        # -----------------------------------------------------
        if intent.type == IntentType.GOALS_LIST:
            if not is_valid_command("list_goals"):
                return None

            return AICommand(
                command="list_goals",
                read_only=True,
                params={},
                metadata={"context_type": "system"},
                validated=True,
            )

        # -----------------------------------------------------
        # 4) GOAL CREATE (WRITE)
        # -----------------------------------------------------
        if intent.type == IntentType.GOAL_CREATE:
            params: Dict[str, Any] = {
                "name": raw_input
            }

            m_q = re.search(r"\bq([1-4])\b", lowered)
            if m_q:
                params["quarter"] = f"Q{m_q.group(1)}"

            m_year = re.search(r"\b(20\d{2})\b", lowered)
            if m_year:
                params["year"] = int(m_year.group(1))

            m_pct = re.search(r"(\d{1,3})\s*%+", lowered)
            if m_pct:
                params["target_pct"] = int(m_pct.group(1))

            return AICommand(
                command="goal_write",
                intent="create_goal",
                read_only=False,
                params=params,
                metadata={"context_type": "system"},
                validated=True,
            )

        return None
