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
        """
        Uzmemo sve nakon prefiksa, do prvog stop tokena (priority, status, due date, ...).
        """
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
        """
        Helper za izvlačenje statusa/prioriteta/due date/start datuma iz slobodnog teksta.
        """
        m = re.search(regex, raw_input, flags=re.IGNORECASE)
        if not m:
            return None
        return m.group(1).strip(" ,")

    @staticmethod
    def _extract_date_range(raw_input: str) -> Optional[Dict[str, str]]:
        """
        Podržava:
        - 'od YYYY-MM-DD do YYYY-MM-DD'
        - 'između YYYY-MM-DD i YYYY-MM-DD'
        """
        lowered = raw_input.lower()

        m = re.search(
            r"od\s+(\d{4}-\d{2}-\d{2})\s+do\s+(\d{4}-\d{2}-\d{2})",
            lowered,
        )
        if m:
            return {"start": m.group(1), "end": m.group(2)}

        m = re.search(
            r"između\s+(\d{4}-\d{2}-\d{2})\s+i\s+(\d{4}-\d{2}-\d{2})",
            lowered,
        )
        if m:
            return {"start": m.group(1), "end": m.group(2)}

        return None

    @staticmethod
    def _extract_quarter_range(raw_input: str) -> Optional[Dict[str, str]]:
        """
        Podržava:
        - 'za Q1 2026', 'u Q2 2025', itd.
        Mapira Qx + godina u [start, end] range.
        """
        lowered = raw_input.lower()

        m_q = re.search(r"\bq([1-4])\b", lowered)
        if not m_q:
            return None
        q = int(m_q.group(1))

        m_year = re.search(r"\b(20\d{2})\b", lowered)
        if not m_year:
            return None
        year = int(m_year.group(1))

        if q == 1:
            start = f"{year}-01-01"
            end = f"{year}-03-31"
        elif q == 2:
            start = f"{year}-04-01"
            end = f"{year}-06-30"
        elif q == 3:
            start = f"{year}-07-01"
            end = f"{year}-09-30"
        else:
            start = f"{year}-10-01"
            end = f"{year}-12-31"

        return {"start": start, "end": end}

    @staticmethod
    def _build_task_property_specs_from_text(raw_input: str) -> Dict[str, Any]:
        """
        Mapira CEO NL za TASK u Notion DSL property_specs.

        Primjer:
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
            # fallback: cijeli input kao name
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
        Mapira CEO NL za GOAL u Notion DSL property_specs.

        Primjer:
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
            # fallback: cijeli input kao ime
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
        # 0.A) CEO NL → GOAL + TASK WORKFLOW (BOSANSKI)
        # "kreiraj cilj X ... i task Y ..."
        # koristi postojeće _build_goal/_build_task helpere
        # -----------------------------------------------------
        m_wf = re.search(
            r"(?i)^kreiraj cilj (.+?) i task (.+)$",
            text,
        )
        if m_wf:
            logger.info("COO TRANSLATE: matched GOAL+TASK WORKFLOW")

            if not is_valid_command("goal_task_workflow"):
                return None

            goal_segment = "kreiraj cilj " + m_wf.group(1).strip()
            task_segment = "kreiraj task " + m_wf.group(2).strip()

            goal_specs = self._build_goal_property_specs_from_text(goal_segment)
            task_specs = self._build_task_property_specs_from_text(task_segment)

            return AICommand(
                command="goal_task_workflow",
                intent="run_workflow",
                read_only=False,
                params={
                    "goal": {
                        "db_key": "goals",
                        "property_specs": goal_specs,
                    },
                    "tasks": [
                        {
                            "db_key": "tasks",
                            "property_specs": task_specs,
                        }
                    ],
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.B) CEO NL → 7-DAY PLAN (GOAL + 7 TASKS)
        # "kreiraj 7 day plan za cilj EVO-GOAL-7DAY-002 status Not Started priority High start 2026-02-01"
        # -----------------------------------------------------
        if lowered.startswith("kreiraj 7 day plan za cilj "):
            logger.info("COO TRANSLATE: matched BOSNIAN 7-DAY PLAN WORKFLOW")

            if not is_valid_command("goal_task_workflow"):
                return None

            prefix = "kreiraj 7 day plan za cilj "
            goal_tail = text[len(prefix):].strip()

            synthetic_goal_sentence = "kreiraj cilj " + goal_tail
            goal_specs = self._build_goal_property_specs_from_text(
                synthetic_goal_sentence
            )

            start_date = self._extract_segment(
                r"start\s+(\d{4}-\d{2}-\d{2})",
                text,
            )

            params: Dict[str, Any] = {
                "mode": "7day",
                "goal": {
                    "db_key": "goals",
                    "property_specs": goal_specs,
                },
                # tasks može biti popunjen iz NL ili generisan u agentu na osnovu mode/start_date
                "tasks": [],
            }

            if start_date:
                params["start_date"] = start_date

            return AICommand(
                command="goal_task_workflow",
                intent="run_workflow",
                read_only=False,
                params=params,
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.C) CEO NL → FLP MANAGER PLAN (GOAL + TEMPLATE TASKS)
        # "kreiraj flp manager plan za cilj EVO-FLP-MANAGER-PLAN-001 status Not Started priority High"
        # -----------------------------------------------------
        if lowered.startswith("kreiraj flp manager plan za cilj "):
            logger.info("COO TRANSLATE: matched FLP MANAGER PLAN WORKFLOW")

            if not is_valid_command("goal_task_workflow"):
                return None

            prefix = "kreiraj flp manager plan za cilj "
            goal_tail = text[len(prefix):].strip()

            synthetic_goal_sentence = "kreiraj cilj " + goal_tail
            goal_specs = self._build_goal_property_specs_from_text(
                synthetic_goal_sentence
            )

            goal_name: Optional[str] = None
            name_spec = goal_specs.get("Name")
            if isinstance(name_spec, dict):
                goal_name = name_spec.get("text") or None

            base_task_name = goal_name or "FLP manager task"

            tasks: List[Dict[str, Any]] = []
            for i in range(1, 6):
                tasks.append(
                    {
                        "db_key": "tasks",
                        "property_specs": {
                            "Name": {
                                "type": "title",
                                "text": f"{base_task_name} — step {i}",
                            },
                        },
                    }
                )

            return AICommand(
                command="goal_task_workflow",
                intent="run_workflow",
                read_only=False,
                params={
                    "mode": "flp_manager",
                    "goal": {
                        "db_key": "goals",
                        "property_specs": goal_specs,
                    },
                    "tasks": tasks,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.1) CEO NL → TASK CREATE (NOTION DSL)
        # -----------------------------------------------------
        if lowered.startswith("kreiraj task ") or lowered.startswith("napravi task "):
            logger.info("COO TRANSLATE: matched BOSNIAN TASK CREATE")

            if not is_valid_command("notion_write"):
                return None

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
        # 0.2.a) CEO NL → TASK STATUS SUMMARY (REPORT)
        # 'daj mi sažetak taskova po statusu'
        # -----------------------------------------------------
        if "sažetak taskova po statusu" in lowered or "sazetak taskova po statusu" in lowered:
            logger.info("COO TRANSLATE: matched TASK STATUS SUMMARY REPORT")

            if not is_valid_command("notion_write"):
                return None

            return AICommand(
                command="notion_write",
                intent="query_database",
                read_only=True,
                params={
                    "db_key": "tasks",
                    "property_specs": {},
                },
                metadata={
                    "context_type": "system",
                    "source": source,
                    "report_type": "tasks_by_status",
                },
                validated=True,
            )

        # -----------------------------------------------------
        # 0.2.b) CEO NL → GOAL STATUS SUMMARY (REPORT)
        # 'daj mi sažetak ciljeva po statusu'
        # -----------------------------------------------------
        if "sažetak ciljeva po statusu" in lowered or "sazetak ciljeva po statusu" in lowered:
            logger.info("COO TRANSLATE: matched GOAL STATUS SUMMARY REPORT")

            if not is_valid_command("notion_write"):
                return None

            return AICommand(
                command="notion_write",
                intent="query_database",
                read_only=True,
                params={
                    "db_key": "goals",
                    "property_specs": {},
                },
                metadata={
                    "context_type": "system",
                    "source": source,
                    "report_type": "goals_by_status",
                },
                validated=True,
            )

        # -----------------------------------------------------
        # 0.2) CEO NL → TASK QUERY (READ, NOTION DSL)
        # 'prikazi/daj mi taskove sa statusom X'
        # ili '... sa statusom X i prioritetom Y'
        # + opcioni date range (Due Date)
        # -----------------------------------------------------
        if "taskove" in lowered and "statusom" in lowered:
            logger.info("COO TRANSLATE: matched BOSNIAN TASK QUERY")

            if not is_valid_command("notion_write"):
                return None

            status_value = self._extract_segment(
                r"statusom\s+(.+?)(?=\s+i\s+prioritetom\b|$)", text
            )
            priority_value = self._extract_segment(
                r"prioritetom\s+(\w+)", text
            )
            date_range = self._extract_date_range(text)

            property_specs: Dict[str, Any] = {}
            if status_value:
                property_specs["Status"] = {
                    "type": "select",
                    "name": status_value,
                }
            if priority_value:
                property_specs["Priority"] = {
                    "type": "select",
                    "name": priority_value,
                }
            if date_range:
                property_specs["Due Date"] = {
                    "type": "date_range",
                    "start": date_range["start"],
                    "end": date_range["end"],
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
        # 0.3) CEO NL → GOAL CREATE (NOTION DSL, Bosanski)
        # NE diramo Happy Path: 'create goal ...' ide kroz IntentType.GOAL_CREATE
        # -----------------------------------------------------
        if lowered.startswith("kreiraj cilj "):
            logger.info("COO TRANSLATE: matched BOSNIAN GOAL CREATE")

            if not is_valid_command("notion_write"):
                return None

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

        # -----------------------------------------------------
        # 0.4) CEO NL → GOAL QUERY (READ, Notion DSL)
        # 'prikazi/daj mi ciljeve sa statusom X'
        # ili '... sa statusom X i prioritetom Y'
        # + opcioni date range (Deadline) ili Q-range
        # -----------------------------------------------------
        if "ciljeve" in lowered and "statusom" in lowered:
            logger.info("COO TRANSLATE: matched BOSNIAN GOAL QUERY")

            if not is_valid_command("notion_write"):
                return None

            status_value = self._extract_segment(
                r"statusom\s+(.+?)(?=\s+i\s+prioritetom\b|$)", text
            )
            priority_value = self._extract_segment(
                r"prioritetom\s+(\w+)", text
            )
            date_range = self._extract_date_range(text)
            if not date_range:
                date_range = self._extract_quarter_range(text)

            property_specs: Dict[str, Any] = {}
            if status_value:
                property_specs["Status"] = {
                    "type": "select",
                    "name": status_value,
                }
            if priority_value:
                property_specs["Priority"] = {
                    "type": "select",
                    "name": priority_value,
                }
            if date_range:
                property_specs["Deadline"] = {
                    "type": "date_range",
                    "start": date_range["start"],
                    "end": date_range["end"],
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
        # 0.5) CEO NL → TASK STATUS UPDATE (BY PAGE ID)
        # 'oznaci task <page_id> kao Completed'
        # -----------------------------------------------------
        m_task_status = re.search(
            r"(?i)^(oznaci|označi)\s+task\s+([0-9a-f\-]{36})\s+kao\s+(.+)$",
            text.strip(),
        )
        if m_task_status:
            logger.info("COO TRANSLATE: matched BOSNIAN TASK STATUS UPDATE")

            if not is_valid_command("notion_write"):
                return None

            page_id = m_task_status.group(2).strip()
            status_value = m_task_status.group(3).strip()

            property_specs: Dict[str, Any] = {
                "Status": {
                    "type": "select",
                    "name": status_value,
                }
            }

            return AICommand(
                command="notion_write",
                intent="update_page",
                read_only=False,
                params={
                    "page_id": page_id,
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.6) CEO NL → GOAL STATUS UPDATE (BY PAGE ID)
        # 'oznaci cilj <page_id> kao In Progress'
        # -----------------------------------------------------
        m_goal_status = re.search(
            r"(?i)^(oznaci|označi)\s+cilj\s+([0-9a-f\-]{36})\s+kao\s+(.+)$",
            text.strip(),
        )
        if m_goal_status:
            logger.info("COO TRANSLATE: matched BOSNIAN GOAL STATUS UPDATE")

            if not is_valid_command("notion_write"):
                return None

            page_id = m_goal_status.group(2).strip()
            status_value = m_goal_status.group(3).strip()

            property_specs: Dict[str, Any] = {
                "Status": {
                    "type": "select",
                    "name": status_value,
                }
            }

            return AICommand(
                command="notion_write",
                intent="update_page",
                read_only=False,
                params={
                    "page_id": page_id,
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.7) CEO NL → TASK PRIORITY UPDATE (BY PAGE ID)
        # 'promijeni prioritet taska <page_id> u High'
        # -----------------------------------------------------
        m_task_prio = re.search(
            r"(?i)^promijeni prioritet taska\s+([0-9a-f\-]{36})\s+u\s+(.+)$",
            text.strip(),
        )
        if m_task_prio:
            logger.info("COO TRANSLATE: matched BOSNIAN TASK PRIORITY UPDATE")

            if not is_valid_command("notion_write"):
                return None

            page_id = m_task_prio.group(1).strip()
            prio_value = m_task_prio.group(2).strip()

            property_specs: Dict[str, Any] = {
                "Priority": {
                    "type": "select",
                    "name": prio_value,
                }
            }

            return AICommand(
                command="notion_write",
                intent="update_page",
                read_only=False,
                params={
                    "page_id": page_id,
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.8) CEO NL → GOAL PRIORITY UPDATE (BY PAGE ID)
        # 'promijeni prioritet cilja <page_id> u High'
        # -----------------------------------------------------
        m_goal_prio = re.search(
            r"(?i)^promijeni prioritet cilja\s+([0-9a-f\-]{36})\s+u\s+(.+)$",
            text.strip(),
        )
        if m_goal_prio:
            logger.info("COO TRANSLATE: matched BOSNIAN GOAL PRIORITY UPDATE")

            if not is_valid_command("notion_write"):
                return None

            page_id = m_goal_prio.group(1).strip()
            prio_value = m_goal_prio.group(2).strip()

            property_specs: Dict[str, Any] = {
                "Priority": {
                    "type": "select",
                    "name": prio_value,
                }
            }

            return AICommand(
                command="notion_write",
                intent="update_page",
                read_only=False,
                params={
                    "page_id": page_id,
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.9) CEO NL → TASK DUE DATE UPDATE (BY PAGE ID)
        # 'promijeni due date taska <page_id> na 2026-02-10'
        # -----------------------------------------------------
        m_task_due = re.search(
            r"(?i)^promijeni due date taska\s+([0-9a-f\-]{36})\s+na\s+(\d{4}-\d{2}-\d{2})$",
            text.strip(),
        )
        if m_task_due:
            logger.info("COO TRANSLATE: matched BOSNIAN TASK DUE DATE UPDATE")

            if not is_valid_command("notion_write"):
                return None

            page_id = m_task_due.group(1).strip()
            due_date = m_task_due.group(2).strip()

            property_specs: Dict[str, Any] = {
                "Due Date": {
                    "type": "date",
                    "start": due_date,
                }
            }

            return AICommand(
                command="notion_write",
                intent="update_page",
                read_only=False,
                params={
                    "page_id": page_id,
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.10) CEO NL → GOAL DEADLINE UPDATE (BY PAGE ID)
        # 'promijeni deadline cilja <page_id> na 2026-02-10'
        # ili 'promijeni due date cilja <page_id> na 2026-02-10'
        # -----------------------------------------------------
        m_goal_deadline = re.search(
            r"(?i)^promijeni (?:deadline|due date) cilja\s+([0-9a-f\-]{36})\s+na\s+(\d{4}-\d{2}-\d{2})$",
            text.strip(),
        )
        if m_goal_deadline:
            logger.info("COO TRANSLATE: matched BOSNIAN GOAL DEADLINE UPDATE")

            if not is_valid_command("notion_write"):
                return None

            page_id = m_goal_deadline.group(1).strip()
            deadline = m_goal_deadline.group(2).strip()

            property_specs: Dict[str, Any] = {
                "Deadline": {
                    "type": "date",
                    "start": deadline,
                }
            }

            return AICommand(
                command="notion_write",
                intent="update_page",
                read_only=False,
                params={
                    "page_id": page_id,
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
        # 4) GOAL CREATE (WRITE — HAPPY PATH V1, ENGLISH)
        # -----------------------------------------------------
        if intent.type == IntentType.GOAL_CREATE:
            # Postojeći Happy Path za:
            # "create goal Test Happy Path"
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
