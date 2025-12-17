# services/coo_translation_service.py
"""
COO TRANSLATION SERVICE (CANONICAL)
"""

from typing import Optional, Dict, Any, List
import re
import logging

from models.ai_command import AICommand
from services.intent_classifier import IntentClassifier
from services.intent_contract import Intent, IntentType
from services.action_dictionary import is_valid_command

logger = logging.getLogger(__name__)


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

    # -----------------------------------------------------
    # INTERNAL HELPERS — NOTION DSL PARSING
    # -----------------------------------------------------
    @staticmethod
    def _extract_name_after_prefix(
        raw_input: str,
        prefix: str,
        stop_tokens: Optional[List[str]] = None,
    ) -> str:
        stop_tokens = stop_tokens or []
        text_after = raw_input[len(prefix):].strip()

        lowered_after = text_after.lower()
        cut_pos = len(text_after)

        for token in stop_tokens:
            idx = lowered_after.find(f" {token.lower()} ")
            if idx != -1 and idx < cut_pos:
                cut_pos = idx

        name = text_after[:cut_pos].strip(" ,")
        return name or text_after

    @staticmethod
    def _extract_segment(regex: str, raw_input: str) -> Optional[str]:
        m = re.search(regex, raw_input, flags=re.IGNORECASE)
        if not m:
            return None
        return m.group(1).strip(" ,")

    @staticmethod
    def _build_task_property_specs_from_text(raw_input: str) -> Dict[str, Any]:
        """
        CEO NL → TASK DSL
        npr:
        'kreiraj task EVO-CEO-TASK-001 priority High status Not Started due date 2025-12-25'
        """
        stop_tokens = ["priority", "status", "due date"]
        lowered = raw_input.lower()

        if lowered.startswith("kreiraj task "):
            name = COOTranslationService._extract_name_after_prefix(
                raw_input,
                prefix="kreiraj task ",
                stop_tokens=stop_tokens,
            )
        elif lowered.startswith("napravi task "):
            name = COOTranslationService._extract_name_after_prefix(
                raw_input,
                prefix="napravi task ",
                stop_tokens=stop_tokens,
            )
        else:
            name = raw_input

        status = COOTranslationService._extract_segment(
            r"status\s+(.+?)(?=\s+due date\b|$)", raw_input
        )
        priority = COOTranslationService._extract_segment(
            r"priority\s+(\w+)", raw_input
        )
        due_date = COOTranslationService._extract_segment(
            r"due date\s+(\d{4}-\d{2}-\d{2})", raw_input
        )

        property_specs: Dict[str, Any] = {
            "Name": {"type": "title", "text": name},
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
            property_specs["Due Date"] = {
                "type": "date",
                "start": due_date,
            }

        return property_specs

    @staticmethod
    def _build_goal_property_specs_from_text(raw_input: str) -> Dict[str, Any]:
        """
        CEO NL → GOAL DSL
        npr:
        'kreiraj cilj FLP manager status Not Started priority High deadline 2025-12-31'
        """
        stop_tokens = ["priority", "status", "due date", "deadline"]
        lowered = raw_input.lower()

        if lowered.startswith("kreiraj cilj "):
            name = COOTranslationService._extract_name_after_prefix(
                raw_input,
                prefix="kreiraj cilj ",
                stop_tokens=stop_tokens,
            )
        else:
            name = raw_input

        status = COOTranslationService._extract_segment(
            r"status\s+(.+?)(?=\s+priority\b|\s+due date\b|\s+deadline\b|$)",
            raw_input,
        )
        priority = COOTranslationService._extract_segment(
            r"priority\s+(\w+)", raw_input
        )
        deadline = COOTranslationService._extract_segment(
            r"(?:due date|deadline)\s+(\d{4}-\d{2}-\d{2})", raw_input
        )

        property_specs: Dict[str, Any] = {
            "Name": {"type": "title", "text": name},
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

        if deadline:
            property_specs["Deadline"] = {
                "type": "date",
                "start": deadline,
            }

        return property_specs

    # -----------------------------------------------------
    # MAIN TRANSLATION ENTRYPOINT
    # -----------------------------------------------------
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

        logger.info("COO TRANSLATE v2 ACTIVE: raw='%s'", text)

        # ==============================================
        # BOSNIAN GOAL CREATE (CEO NL → Notion DSL)
        # ==============================================
        if lowered.startswith("kreiraj cilj "):
            logger.info("COO TRANSLATE: matched BOSNIAN GOAL CREATE")

            property_specs = self._build_goal_property_specs_from_text(text)

            return AICommand(
                command="notion_write",
                intent="create_page",
                read_only=False,
                params={
                    "db_key": "goals",
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # ==============================================
        # BOSNIAN GOAL QUERY (CEO NL → Notion DSL)
        # 'prikazi ciljeve sa statusom X'
        # ==============================================
        if "prikazi ciljeve" in lowered and "statusom" in lowered:
            logger.info("COO TRANSLATE: matched BOSNIAN GOAL QUERY")

            status_value = self._extract_segment(
                r"statusom\s+(.+)$", text
            )

            property_specs: Dict[str, Any] = {}
            if status_value:
                property_specs["Status"] = {
                    "type": "select",
                    "name": status_value,
                }

            return AICommand(
                command="notion_write",
                intent="query_database",
                read_only=True,
                params={
                    "db_key": "goals",
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # CEO READ-ONLY HARD MATCH
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
        # CEO NL → TASK CREATE (NOTION DSL)
        # -----------------------------------------------------
        if lowered.startswith("kreiraj task ") or lowered.startswith(
            "napravi task "
        ):
            property_specs = self._build_task_property_specs_from_text(text)

            return AICommand(
                command="notion_write",
                intent="create_page",
                read_only=False,
                params={
                    "db_key": "tasks",
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # CEO NL → TASK QUERY (READ, NOTION DSL)
        # 'prikazi taskove sa statusom X'
        # -----------------------------------------------------
        if "prikazi taskove" in lowered and "statusom" in lowered:

            status_value = self._extract_segment(
                r"statusom\s+(.+)$", text
            )

            property_specs: Dict[str, Any] = {}
            if status_value:
                property_specs["Status"] = {
                    "type": "select",
                    "name": status_value,
                }

            return AICommand(
                command="notion_write",
                intent="query_database",
                read_only=True,
                params={
                    "db_key": "tasks",
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 1) INTENT CLASSIFICATION (SVE OSTALO)
        # -----------------------------------------------------
        intent: Intent = self.intent_classifier.classify(
            raw_input, source=source
        )

        if (
            intent.confidence
            < self.intent_classifier.DEFAULT_CONFIDENCE_THRESHOLD
        ):
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
        # 4) GOAL CREATE (WRITE — HAPPY PATH V1, ENG)
        # -----------------------------------------------------
        if intent.type == IntentType.GOAL_CREATE:
            params: Dict[str, Any] = {"name": raw_input}

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
