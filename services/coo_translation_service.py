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
from services.goal_nl_parser import parse_ceo_goal_plan  # trenutno se ne koristi, ali ostaje za kompatibilnost


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

    SOP_DB_KEYWORDS: Dict[str, str] = {
        "outreach": "outreach_sop",
        "qualification": "qualification_sop",
        "follow up": "follow_up_sop",
        "follow-up": "follow_up_sop",
        "fsc": "fsc_sop",
        "flp ops": "flp_ops_sop",
        "lss": "lss_sop",
        "partner activation": "partner_activation_sop",
        "partner performance": "partner_performance_sop",
        "partner leadership": "partner_leadership_sop",
        "customer onboarding": "customer_onboarding_sop",
        "customer retention": "customer_retention_sop",
        "customer performance": "customer_performance_sop",
        "partner potential": "partner_potential_sop",
        "sales closing": "sales_closing_sop",
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
    def _parse_bosnian_date(date_str: str) -> Optional[str]:
        """
        Pretvara:
        - 'DD.MM.YYYY' u 'YYYY-MM-DD'
        - ili propušta 'YYYY-MM-DD' kao važeći datum.

        Ako ne prepozna format, vraća None.
        """
        if not date_str:
            return None

        ds = date_str.strip()

        # ISO format već spreman
        if re.match(r"^\d{4}-\d{2}-\d{2}$", ds):
            return ds

        # Klasični bosanski/evropski format
        m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", ds)
        if not m:
            return None

        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    @staticmethod
    def _parse_ceo_goal_plan_bosnian(raw_input: str) -> Dict[str, Any]:
        """
        Generalizovani CEO NL plan (Bosanski):

        Podržava:
        - različite nazive centralnog cilja
        - datume tipa '01.05.2025' ili '2025-05-01'
        - bilo koji broj podciljeva ('Kreiraj ... podciljeva:')
        - N-dnevni plan (7, 14, ...) — 'Kreiraj 7-dnevni plan...', 'Kreiraj 14-dnevni plan...'
        - bilo koji naziv projekta u navodnicima

        Vraća strukturirani plan:
        {
          "central_goal": {name, priority, status, due_date_iso, due_date_raw},
          "subgoals": [{name, priority, status}, ...],
          "tasks": [{day_index, name, priority, status}, ...],
          "project_name": str | None,
          "days_count": int | None,
        }
        """
        text = raw_input.strip()
        plan: Dict[str, Any] = {
            "central_goal": {},
            "subgoals": [],
            "tasks": [],
            "project_name": None,
            "days_count": None,
        }

        # --- CENTRALNI CILJ (generički datum) ---
        m_central = re.search(
            r"kreiraj\s+centralni\s+cilj\s+[\"“](.+?)[\"”]\s+sa\s+due\s+date\s+([0-9./\-]+)\s*,\s*prioritet\s+([A-Za-zČĆŽŠĐčćžšđ]+)\s*,\s*status\s+([A-Za-zČĆŽŠĐčćžšđ]+)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m_central:
            name = m_central.group(1).strip()
            due_raw = m_central.group(2).strip()
            priority = m_central.group(3).strip()
            status = m_central.group(4).strip()
            due_iso = COOTranslationService._parse_bosnian_date(due_raw)

            plan["central_goal"] = {
                "name": name,
                "priority": priority,
                "status": status,
                "due_date_iso": due_iso,
                "due_date_raw": due_raw,
            }

        # --- BROJ DANA (7, 14, ...) ---
        m_days = re.search(
            r"kreiraj\s+(\d+)[-\s]*dnevni\s+plan",
            text,
            flags=re.IGNORECASE,
        )
        if m_days:
            try:
                plan["days_count"] = int(m_days.group(1))
            except ValueError:
                plan["days_count"] = None

        # --- PODCILJEVI ---
        m_sub_section = re.search(
            r"kreiraj\s+.*podcilj[ea]*\s*:(.*?)(?:kreiraj\s+\d+[-\s]*dnevni\s+plan)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m_sub_section:
            sub_text = m_sub_section.group(1)
            for name, prio in re.findall(
                r"([^\n,]+?)\s*\(prioritet\s+([^)]+)\)",
                sub_text,
                flags=re.IGNORECASE,
            ):
                plan["subgoals"].append(
                    {
                        "name": name.strip(" \n\r-•"),
                        "priority": prio.strip(" \n\r,"),
                        "status": "Not Started",
                    }
                )

        # --- PROJEKAT ---
        m_proj = re.search(
            r"projekat\s+[\"“](.+?)[\"”]",
            text,
            flags=re.IGNORECASE,
        )
        if m_proj:
            plan["project_name"] = m_proj.group(1).strip()

        # --- TASKOVI: Dan X: ... (prio) ---
        for day, name, prio in re.findall(
            r"Dan\s+(\d+)\s*:\s*(.+?)\s*\(([^)]+)\)",
            text,
            flags=re.IGNORECASE,
        ):
            try:
                day_index = int(day)
            except ValueError:
                continue

            plan["tasks"].append(
                {
                    "day_index": day_index,
                    "name": name.strip(),
                    "priority": prio.strip(),
                    "status": "To Do",
                }
            )

        return plan

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

    @staticmethod
    def _build_project_property_specs_from_text(raw_input: str) -> Dict[str, Any]:
        """
        Mapira CEO NL za PROJECT u Notion DSL property_specs.

        Primjer:
        'kreiraj projekt EVO-OS rollout status In Progress priority High target deadline 2026-03-31'
        """
        stop_tokens = ["status", "priority", "target deadline", "deadline", "due date"]
        lowered = raw_input.lower()

        if lowered.startswith("kreiraj projekt "):
            name = COOTranslationService._extract_name_after_prefix(
                raw_input,
                prefix="kreiraj projekt ",
                stop_tokens=stop_tokens,
            )
        elif lowered.startswith("napravi projekt "):
            name = COOTranslationService._extract_name_after_prefix(
                raw_input,
                prefix="napravi projekt ",
                stop_tokens=stop_tokens,
            )
        else:
            name = raw_input

        status = COOTranslationService._extract_segment(
            r"status\s+(.+?)(?=\s+priority\b|\s+target deadline\b|\s+deadline\b|\s+due date\b|$)",
            raw_input,
        )
        priority = COOTranslationService._extract_segment(
            r"priority\s+(\w+)", raw_input
        )
        deadline = COOTranslationService._extract_segment(
            r"(?:target deadline|deadline|due date)\s+(\d{4}-\d{2}-\d{2})",
            raw_input,
        )

        property_specs: Dict[str, Any] = {
            "Project Name": {"type": "title", "text": name},
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
            property_specs["Target Deadline"] = {
                "type": "date",
                "start": deadline,
            }

        return property_specs

    @staticmethod
    def _build_ceo_goal_plan_params(plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pretvara strukturirani CEO plan u parametre za goal_task_workflow:
        - goal: centralni cilj
        - subgoals: lista podciljeva
        - tasks: lista taskova
        - project (opcionalno)
        - days_count (opcionalno)
        """
        # --- CENTRAL GOAL ---
        central = plan.get("central_goal") or {}
        cg_name = central.get("name") or ""
        cg_status = central.get("status")
        cg_priority = central.get("priority")
        cg_due_iso = central.get("due_date_iso")

        goal_sentence = f"kreiraj cilj {cg_name}"
        if cg_status:
            goal_sentence += f" status {cg_status}"
        if cg_priority:
            goal_sentence += f" priority {cg_priority}"
        if cg_due_iso:
            goal_sentence += f" due date {cg_due_iso}"

        goal_specs = COOTranslationService._build_goal_property_specs_from_text(
            goal_sentence
        )

        # --- SUBGOALS ---
        subgoals_cfg: List[Dict[str, Any]] = []
        for sg in plan.get("subgoals") or []:
            sg_name = sg.get("name") or ""
            sg_priority = sg.get("priority")
            sg_status = sg.get("status") or "Not Started"

            sg_sentence = f"kreiraj cilj {sg_name}"
            if sg_status:
                sg_sentence += f" status {sg_status}"
            if sg_priority:
                sg_sentence += f" priority {sg_priority}"

            sg_specs = COOTranslationService._build_goal_property_specs_from_text(
                sg_sentence
            )

            subgoals_cfg.append(
                {
                    "db_key": "goals",
                    "property_specs": sg_specs,
                    "link_to_parent_goal": True,
                }
            )

        # --- TASKS ---
        tasks_cfg: List[Dict[str, Any]] = []
        for t in plan.get("tasks") or []:
            t_name = t.get("name") or ""
            t_priority = t.get("priority")
            t_status = t.get("status") or "To Do"

            t_sentence = f"kreiraj task {t_name}"
            if t_priority:
                t_sentence += f" priority {t_priority}"
            if t_status:
                t_sentence += f" status {t_status}"

            t_specs = COOTranslationService._build_task_property_specs_from_text(
                t_sentence
            )

            cfg: Dict[str, Any] = {
                "db_key": "tasks",
                "property_specs": t_specs,
            }
            if "day_index" in t:
                cfg["day_index"] = t["day_index"]

            tasks_cfg.append(cfg)

        params: Dict[str, Any] = {
            "mode": "ceo_goal_plan",
            "goal": {
                "db_key": "goals",
                "property_specs": goal_specs,
            },
            "subgoals": subgoals_cfg,
            "tasks": tasks_cfg,
        }

        project_name = plan.get("project_name")
        if project_name:
            params["project"] = {"name": project_name}

        days_count = plan.get("days_count")
        if days_count:
            params["days_count"] = days_count

        return params

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

        logger.info("COO TRANSLATE v3 ACTIVE: raw='%s'", text)

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
        # 0.A) CEO GOAL PLAN (centralni cilj + podciljevi + N-dnevni taskovi)
        # -----------------------------------------------------
        if lowered.startswith("kreiraj centralni cilj"):
            logger.info(
                "COO TRANSLATE: matched CEO GOAL PLAN (central goal + subgoals + tasks)"
            )

            if not is_valid_command("goal_task_workflow"):
                return None

            structured_plan = self._parse_ceo_goal_plan_bosnian(text)
            params = self._build_ceo_goal_plan_params(structured_plan)

            return AICommand(
                command="goal_task_workflow",
                intent="run_workflow",
                read_only=False,
                params=params,
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.B) CEO NL → GOAL + TASK WORKFLOW (BOSANSKI)
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
        # 0.C) CEO NL → 7-DAY PLAN (GOAL + 7 TASKS)
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
        # 0.D) CEO NL → FLP MANAGER PLAN (GOAL + TEMPLATE TASKS)
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
        # 0.2.c) CEO NL → KPI WEEKLY SUMMARY (REPORT)
        # -----------------------------------------------------
        if "weekly kpi" in lowered and (
            "rezime" in lowered or "sažetak" in lowered or "sazetak" in lowered
        ):
            logger.info("COO TRANSLATE: matched KPI WEEKLY SUMMARY REPORT")

            if not is_valid_command("notion_write"):
                return None

            time_scope = "this_week"
            if (
                "prošlu sedmicu" in lowered
                or "proslu sedmicu" in lowered
                or "prošle sedmice" in lowered
                or "prosle sedmice" in lowered
            ):
                time_scope = "last_week"

            return AICommand(
                command="notion_write",
                intent="query_database",
                read_only=True,
                params={
                    "db_key": "kpi",
                    "property_specs": {},
                },
                metadata={
                    "context_type": "system",
                    "source": source,
                    "report_type": "kpi_weekly_summary",
                    "time_scope": time_scope,
                },
                validated=True,
            )

        # -----------------------------------------------------
        # 0.2.d) CEO NL → KPI PERIOD SUMMARY (Qx YYYY)
        # -----------------------------------------------------
        if "kpi" in lowered and (
            "rezime" in lowered or "sažetak" in lowered or "sazetak" in lowered
        ) and "weekly kpi" not in lowered:
            m_period = re.search(r"\bq([1-4])\s*(20\d{2})", lowered)
            if m_period:
                logger.info("COO TRANSLATE: matched KPI PERIOD SUMMARY")

                if not is_valid_command("notion_write"):
                    return None

                q = m_period.group(1)
                year = m_period.group(2)
                period_label = f"Q{q} {year}"

                property_specs: Dict[str, Any] = {
                    "Period": {
                        "type": "select",
                        "name": period_label,
                    }
                }

                return AICommand(
                    command="notion_write",
                    intent="query_database",
                    read_only=True,
                    params={
                        "db_key": "kpi",
                        "property_specs": property_specs,
                    },
                    metadata={
                        "context_type": "system",
                        "source": source,
                        "report_type": "kpi_period_summary",
                        "period": period_label,
                    },
                    validated=True,
                )

        # -----------------------------------------------------
        # 0.2.e) CEO NL → KPI TOP N BY STATUS
        # -----------------------------------------------------
        if "kpi" in lowered and "top" in lowered and (
            "statusom" in lowered or "status" in lowered
        ):
            logger.info("COO TRANSLATE: matched KPI TOP N BY STATUS")

            if not is_valid_command("notion_write"):
                return None

            m_top = re.search(r"top\s+(\d+)", lowered)
            limit: Optional[int] = None
            if m_top:
                try:
                    limit = int(m_top.group(1))
                except ValueError:
                    limit = None

            status_value = self._extract_segment(
                r"(?:statusom|status)\s+(.+)$",
                text,
            )

            property_specs: Dict[str, Any] = {}
            if status_value:
                property_specs["Status"] = {
                    "type": "select",
                    "name": status_value,
                }

            metadata: Dict[str, Any] = {
                "context_type": "system",
                "source": source,
                "report_type": "kpi_top_by_status",
            }
            if limit is not None:
                metadata["limit"] = limit
            if status_value:
                metadata["status"] = status_value

            return AICommand(
                command="notion_write",
                intent="query_database",
                read_only=True,
                params={
                    "db_key": "kpi",
                    "property_specs": property_specs,
                },
                metadata=metadata,
                validated=True,
            )

        # -----------------------------------------------------
        # 0.2.f) CEO NL → SOP LOOKUP (READ-ONLY)
        # -----------------------------------------------------
        if "sop" in lowered or "proces" in lowered or "procedure" in lowered:
            for keyword, db_key in self.SOP_DB_KEYWORDS.items():
                if keyword in lowered:
                    logger.info(
                        "COO TRANSLATE: matched SOP LOOKUP (%s -> %s)", keyword, db_key
                    )

                    if not is_valid_command("notion_write"):
                        return None

                    return AICommand(
                        command="notion_write",
                        intent="query_database",
                        read_only=True,
                        params={
                            "db_key": db_key,
                            "property_specs": {},
                        },
                        metadata={
                            "context_type": "system",
                            "source": source,
                            "report_type": "sop_lookup",
                            "sop_key": db_key,
                            "keyword": keyword,
                        },
                        validated=True,
                    )

        # -----------------------------------------------------
        # 0.2.g) CEO NL → AGENT EXCHANGE OPEN REQUESTS (READ-ONLY)
        # -----------------------------------------------------
        if ("agent exchange" in lowered or ("zahtjev" in lowered and "agent" in lowered)) and (
            "otvorene" in lowered or "otvoreni" in lowered or "open" in lowered
        ):
            logger.info("COO TRANSLATE: matched AGENT EXCHANGE OPEN REQUESTS")

            if not is_valid_command("notion_write"):
                return None

            property_specs: Dict[str, Any] = {
                "Status": {
                    "type": "select",
                    "name": "Open",
                }
            }

            return AICommand(
                command="notion_write",
                intent="query_database",
                read_only=True,
                params={
                    "db_key": "agent_exchange",
                    "property_specs": property_specs,
                },
                metadata={
                    "context_type": "system",
                    "source": source,
                    "report_type": "agent_exchange_open",
                },
                validated=True,
            )

        # -----------------------------------------------------
        # 0.2) CEO NL → TASK QUERY (READ, NOTION DSL)
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
        # 0.3.a) CEO NL → GOAL CREATE SYNONYMS ("napravi novi cilj ...")
        # -----------------------------------------------------
        m_new_goal = re.match(
            r"(?i)^(napravi|naprvi)\s+(novi\s+)?cilj\s*[:\-]?\s*(.+)$",
            text.strip(),
        )
        if m_new_goal:
            logger.info("COO TRANSLATE: matched BOSNIAN GOAL CREATE (NAPRAVI NOVI CILJ)")

            if not is_valid_command("notion_write"):
                return None

            tail = m_new_goal.group(3).strip()
            synthetic = "kreiraj cilj " + tail

            property_specs = self._build_goal_property_specs_from_text(synthetic)

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
        # 0.3.b) CEO NL → PROJECT CREATE (KREIRAJ / NAPRAVI PROJEKT ...)
        # -----------------------------------------------------
        m_new_project = re.match(
            r"(?i)^(kreiraj|napravi)\s+(novi\s+)?projekt\s*[:\-]?\s*(.+)$",
            text.strip(),
        )
        if m_new_project:
            logger.info("COO TRANSLATE: matched PROJECT CREATE")

            if not is_valid_command("notion_write"):
                return None

            tail = m_new_project.group(3).strip()
            synthetic = "kreiraj projekt " + tail

            property_specs = self._build_project_property_specs_from_text(synthetic)

            return AICommand(
                command="notion_write",
                intent="create_page",
                read_only=False,
                params={
                    "db_key": "projects",
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.3) CEO NL → GOAL CREATE (NOTION DSL, Bosanski)
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
        # 0.4.a) CEO NL → PROJECT QUERY BY STATUS (READ)
        # -----------------------------------------------------
        if (
            ("projekat" in lowered or "projekti" in lowered or "projekte" in lowered or "projekt" in lowered)
            and "statusu" in lowered
        ):
            logger.info("COO TRANSLATE: matched PROJECT QUERY BY STATUS")

            if not is_valid_command("notion_write"):
                return None

            status_value = self._extract_segment(
                r"statusu\s+(.+)$",
                text,
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
                    "db_key": "projects",
                    "property_specs": property_specs,
                },
                metadata={"context_type": "system", "source": source},
                validated=True,
            )

        # -----------------------------------------------------
        # 0.5) CEO NL → TASK STATUS UPDATE (BY PAGE ID)
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
