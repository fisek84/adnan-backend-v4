"""
COO TRANSLATION SERVICE (CANONICAL)
"""

from typing import Optional, Dict, Any
import re

from models.ai_command import AICommand
from services.intent_classifier import IntentClassifier
from services.intent_contract import Intent, IntentType
from services.action_dictionary import is_valid_command
from services.approval_state_service import get_approval_state


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
        self.approvals = get_approval_state()

    def translate(
        self,
        raw_input: str,
        *,
        source: str,
        context: Dict[str, Any],
    ) -> Optional[AICommand]:

        text = (raw_input or "").strip()
        lowered = text.lower().strip()
        context = context or {}

        # -----------------------------------------------------
        # 0) CEO READ-ONLY HARD MATCH
        # -----------------------------------------------------
        if text in self.CEO_READ_ONLY_MATCHES:
            if not is_valid_command(self.READ_ONLY_COMMAND):
                return None

            return AICommand(
                command=self.READ_ONLY_COMMAND,
                intent=None,
                input={
                    "raw_text": raw_input,
                    "snapshot_type": self.CEO_READ_ONLY_MATCHES[text],
                },
                params={},
                metadata={"context_type": "system", "read_only": True},
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
                intent=None,
                input={"raw_text": raw_input},
                params={},
                metadata={"context_type": "system", "read_only": True},
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
                intent=None,
                input={"raw_text": raw_input},
                params={},
                metadata={"context_type": "system", "read_only": True},
                validated=True,
            )

        # -----------------------------------------------------
        # 4) GOAL CREATE (WRITE → APPROVAL)
        # -----------------------------------------------------
        if intent.type == IntentType.GOAL_CREATE:

            approval_id = context.get("approval_id")

            if approval_id:
                try:
                    approval = self.approvals.get(approval_id)
                except KeyError:
                    approval = None
            else:
                approval = None

            if not approval:
                approval = self.approvals.create(
                    command="goal_write",
                    payload_summary={"raw_text": raw_input},
                    scope="goals",
                    risk_level="medium",
                )
                approval_id = approval["approval_id"]

            m_q = re.search(r"\bq([1-4])\b", lowered)
            quarter = f"Q{m_q.group(1)}" if m_q else None
            m_year = re.search(r"\b(20\d{2})\b", lowered)
            year = int(m_year.group(1)) if m_year else None
            m_pct = re.search(r"(\d{1,3})\s*%+", lowered)
            target_pct = int(m_pct.group(1)) if m_pct else None

            return AICommand(
                command="goal_write",
                intent=IntentType.GOAL_CREATE.value,
                input={
                    "raw_text": raw_input,
                    "quarter": quarter,
                    "year": year,
                    "target_pct": target_pct,
                },
                params={},
                metadata={
                    "context_type": "system",
                    "approval_id": approval_id,
                    "read_only": False,
                },
                validated=True,
            )

        return None
