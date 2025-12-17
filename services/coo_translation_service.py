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
