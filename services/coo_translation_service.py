# services/coo_translation_service.py
# FULL FILE — zamijeni cijeli services/coo_translation_service.py ovim.

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from models.ai_command import AICommand

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class _ParsedFields:
    title: str
    status: Optional[str] = None
    priority: Optional[str] = None
    due: Optional[str] = None
    description: Optional[str] = None


class COOTranslationService:
    """
    COO TRANSLATION SERVICE — CANONICAL

    Uloga:
    - PREVODI user text (NL ili structured) u AICommand (PROPOSAL)
    - NE izvršava ništa
    - NE poziva NotionService / agente
    - vraća ili:
        - AICommand(read_only=True) za sistemska pitanja (system_query)
        - AICommand za write/workflow directive (npr. goal_task_workflow, notion_write, goal_write)
        - None ako ne može da prevede input

    FAZA 4:
    - Chat/UX slojevi smiju samo "propose"; execution ide kroz /api/execute i approval pipeline.
    """

    READ_ONLY_COMMAND = "system_query"

    _KNOWN_COMMANDS: set[str] = {
        "goal_task_workflow",
        "notion_write",
        "goal_write",
        "list_goals",
        READ_ONLY_COMMAND,
    }

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------
    def translate(
        self,
        *,
        raw_input: str,
        source: str = "user",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AICommand]:
        text = (raw_input or "").strip()
        ctx = context or {}

        if not text:
            return None

        # 0) Explicit structured payload in context
        cmd_from_ctx = self._translate_from_context(ctx)
        if cmd_from_ctx is not None:
            return cmd_from_ctx

        # 1) JSON payload in text
        cmd = self._translate_from_json_text(text, source=source, context=ctx)
        if cmd is not None:
            return cmd

        # 2) Explicit kv format
        cmd = self._translate_from_explicit_kv(text, source=source, context=ctx)
        if cmd is not None:
            return cmd

        # 3) Workflow (goal + tasks, including “Dan 1: ...” plan, KPI weekly summary)
        cmd = self._translate_goal_task_workflow(text, source=source, context=ctx)
        if cmd is not None:
            return cmd

        # 4) Single goal
        cmd = self._translate_goal(text, source=source, context=ctx)
        if cmd is not None:
            return cmd

        # 5) Single task
        cmd = self._translate_task(text, source=source, context=ctx)
        if cmd is not None:
            return cmd

        # 6) Read-only question fallback
        if self._looks_like_question(text):
            return AICommand(
                command=self.READ_ONLY_COMMAND,
                intent="advice",
                read_only=True,
                params={"query": text, "source": source, "context": ctx},
                initiator=str(ctx.get("initiator") or "ceo"),
                validated=True,
                metadata={"context_type": "ux", "source": source},
            )

        return None

    # ------------------------------------------------------------
    # VALIDATION HELPERS
    # ------------------------------------------------------------
    @classmethod
    def is_valid_command(cls, command_name: str) -> bool:
        name = str(command_name or "").strip()
        return bool(name and name in cls._KNOWN_COMMANDS)

    # ------------------------------------------------------------
    # CONTEXT-BASED TRANSLATION
    # ------------------------------------------------------------
    def _translate_from_context(self, ctx: Dict[str, Any]) -> Optional[AICommand]:
        if not isinstance(ctx, dict) or not ctx:
            return None

        payload = ctx.get("ai_command") or ctx.get("command_payload")
        if isinstance(payload, dict):
            return self._ai_command_from_dict(payload, fallback_ctx=ctx)

        command_type = ctx.get("command_type")
        if command_type == "create_goal":
            goal = ctx.get("goal") or {}
            if isinstance(goal, dict):
                name = (goal.get("name") or "").strip()
                if name:
                    specs: Dict[str, Any] = {"Name": {"type": "title", "text": name}}
                    prio = (goal.get("priority") or "").strip()
                    status = (goal.get("status") or "").strip()
                    due = (goal.get("due") or "").strip()
                    if status:
                        specs["Status"] = {"type": "status", "name": status}
                    if prio:
                        specs["Priority"] = {"type": "select", "name": prio}
                    if due:
                        iso = self._try_parse_date_to_iso(due)
                        if iso:
                            specs["Deadline"] = {"type": "date", "start": iso}

                    return AICommand(
                        command="notion_write",
                        intent="create_page",
                        read_only=False,
                        params={"db_key": "goals", "property_specs": specs},
                        initiator=str(ctx.get("initiator") or "ceo"),
                        validated=True,
                        metadata={"context_type": "ux", "source": "smart_context"},
                    )

        return None

    # ------------------------------------------------------------
    # JSON / STRUCTURED TEXT
    # ------------------------------------------------------------
    def _translate_from_json_text(
        self, text: str, *, source: str, context: Dict[str, Any]
    ) -> Optional[AICommand]:
        t = text.strip()
        if not (t.startswith("{") and t.endswith("}")):
            return None

        try:
            data = json.loads(t)
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        return self._ai_command_from_dict(data, fallback_ctx=context, source=source)

    def _ai_command_from_dict(
        self,
        data: Dict[str, Any],
        *,
        fallback_ctx: Dict[str, Any],
        source: str = "user",
    ) -> Optional[AICommand]:
        if not isinstance(data, dict) or not data:
            return None

        if "command" not in data and isinstance(data.get("directive"), str):
            data = dict(data)
            data["command"] = data.get("directive")

        inner = data.get("command")
        if isinstance(inner, dict):
            merged = dict(data)
            inner_cmd = inner.get("command") or inner.get("directive")
            if isinstance(inner_cmd, str) and inner_cmd:
                merged["command"] = inner_cmd
            if "intent" in inner and "intent" not in merged:
                merged["intent"] = inner.get("intent")
            if "params" in inner and "params" not in merged:
                merged["params"] = inner.get("params")
            if "read_only" in inner and "read_only" not in merged:
                merged["read_only"] = inner.get("read_only")
            if "metadata" in inner and "metadata" not in merged:
                merged["metadata"] = inner.get("metadata")
            data = merged

        cmd_name = str(data.get("command") or "").strip()
        if not cmd_name:
            return None

        if cmd_name != self.READ_ONLY_COMMAND and not self.is_valid_command(cmd_name):
            return None

        intent = data.get("intent")
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        read_only = bool(data.get("read_only", False))

        initiator = str(data.get("initiator") or fallback_ctx.get("initiator") or "ceo")
        metadata = (
            data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        )
        if "context_type" not in metadata:
            metadata["context_type"] = str(fallback_ctx.get("context_type") or "ux")
        metadata.setdefault("source", source)

        try:
            return AICommand(
                command=cmd_name,
                intent=str(intent) if isinstance(intent, str) and intent.strip() else None,
                read_only=read_only,
                params=params,
                initiator=initiator,
                validated=True,
                metadata=metadata,
                execution_id=data.get("execution_id"),
                approval_id=data.get("approval_id"),
            )
        except Exception:
            return AICommand(
                command=cmd_name,
                intent=str(intent) if isinstance(intent, str) and intent.strip() else None,
                read_only=read_only,
                params=params,
                initiator=initiator,
                validated=True,
                metadata=metadata,
            )

    # ------------------------------------------------------------
    # EXPLICIT KV (command=..., intent=...)
    # ------------------------------------------------------------
    def _translate_from_explicit_kv(
        self, text: str, *, source: str, context: Dict[str, Any]
    ) -> Optional[AICommand]:
        lower = text.lower()
        if "command" not in lower and "directive" not in lower:
            return None

        cmd = self._kv_extract(text, "command") or self._kv_extract(text, "directive")
        if not cmd:
            return None

        cmd = cmd.strip()
        if cmd != self.READ_ONLY_COMMAND and not self.is_valid_command(cmd):
            return None

        intent = self._kv_extract(text, "intent")
        read_only = self._kv_extract(text, "read_only")
        ro_flag = str(read_only or "").strip().lower() in ("1", "true", "yes")

        params: Dict[str, Any] = {}
        if cmd == "notion_write":
            db_key = self._kv_extract(text, "db") or self._kv_extract(text, "db_key")
            if db_key:
                params["db_key"] = db_key.strip()

        metadata: Dict[str, Any] = {"context_type": "ux", "source": source}
        initiator = str(context.get("initiator") or "ceo")

        return AICommand(
            command=cmd,
            intent=intent.strip() if isinstance(intent, str) and intent.strip() else None,
            read_only=ro_flag,
            params=params,
            initiator=initiator,
            validated=True,
            metadata=metadata,
        )

    # ------------------------------------------------------------
    # WORKFLOW TRANSLATION
    # ------------------------------------------------------------
    def _translate_goal_task_workflow(
        self, text: str, *, source: str, context: Dict[str, Any]
    ) -> Optional[AICommand]:
        t = text.strip()

        # =========================================================
        # KPI WEEKLY SUMMARY (SPECIAL WORKFLOW)
        # Trigger example (tests): "kpi weekly summary", "kpi sedmični rezime", "kpi tjedni pregled", ...
        # =========================================================
        if (
            re.search(r"\bkpi\b", t, flags=re.IGNORECASE)
            and re.search(r"\b(weekly|sedmic|sedmič|tjedn)\b", t, flags=re.IGNORECASE)
            and re.search(
                r"\b(summary|sažetak|sazetak|rezime|pregled|izvjestaj|izveštaj|report)\b",
                t,
                flags=re.IGNORECASE,
            )
        ):
            time_scope = "this_week"
            if re.search(r"\b(last|prosla|prošla|zadnja|prethodna)\b", t, flags=re.IGNORECASE):
                time_scope = "last_week"

            return AICommand(
                command="goal_task_workflow",
                intent=None,
                read_only=False,
                params={
                    "workflow_type": "kpi_weekly_summary",
                    "db_key": "kpi",
                    "time_scope": time_scope,
                },
                initiator=str(context.get("initiator") or "ceo"),
                validated=True,
                metadata={"context_type": "workflow", "source": source},
            )

        # explicit “goal_task_workflow” with inline JSON
        if "goal_task_workflow" in t:
            payload = self._try_extract_inline_json(t)
            if isinstance(payload, dict):
                goal = payload.get("goal")
                tasks = payload.get("tasks")
                if isinstance(goal, dict) and isinstance(tasks, list) and tasks:
                    return AICommand(
                        command="goal_task_workflow",
                        intent=None,
                        read_only=False,
                        params={"goal": goal, "tasks": tasks},
                        initiator=str(context.get("initiator") or "ceo"),
                        validated=True,
                        metadata={"context_type": "workflow", "source": source},
                    )

        # heuristic triggers for goal+tasks / day-plan
        has_goal_word = bool(re.search(r"\b(goal|cilj)\b", t, flags=re.IGNORECASE))
        has_task_word = bool(
            re.search(r"\b(task|tasks|zadatak|zadaci|zadatci)\b", t, flags=re.IGNORECASE)
        )
        has_day_plan = bool(re.search(r"\bDan\s*\d+\s*:", t, flags=re.IGNORECASE))
        mentions_7day = bool(
            re.search(r"\b(7\s*[- ]?\s*dnevni|7\s*day)\b", t, flags=re.IGNORECASE)
        )
        mentions_14day = bool(
            re.search(r"\b(14\s*[- ]?\s*dnevni|14\s*day)\b", t, flags=re.IGNORECASE)
        )

        if not (has_goal_word and (has_task_word or has_day_plan or mentions_7day or mentions_14day)):
            return None

        goal_title = self._extract_goal_title(t)

        day_tasks = self._extract_day_plan_tasks(t)
        subgoal_tasks = self._extract_subgoals_as_tasks(t)
        _, fallback_task_titles = self._split_goal_and_tasks(t)

        tasks_compound: List[Tuple[str, Optional[str]]] = []
        tasks_compound.extend(subgoal_tasks)
        tasks_compound.extend(day_tasks)

        if not tasks_compound and fallback_task_titles:
            tasks_compound = [(x, None) for x in fallback_task_titles if x.strip()]

        if not goal_title or not tasks_compound:
            return None

        goal_specs = {
            "db_key": "goals",
            "property_specs": {
                "Name": {"type": "title", "text": goal_title},
                "Status": {"type": "status", "name": "Not started"},
            },
        }

        tasks_specs: List[Dict[str, Any]] = []
        for title, prio in tasks_compound:
            if not title.strip():
                continue
            prop: Dict[str, Any] = {
                "Name": {"type": "title", "text": title.strip()},
                "Status": {"type": "select", "name": "Not started"},
            }
            if prio:
                prop["Priority"] = {"type": "select", "name": prio}
            tasks_specs.append({"db_key": "tasks", "property_specs": prop})

        if not tasks_specs:
            return None

        return AICommand(
            command="goal_task_workflow",
            intent=None,
            read_only=False,
            params={"goal": goal_specs, "tasks": tasks_specs},
            initiator=str(context.get("initiator") or "ceo"),
            validated=True,
            metadata={"context_type": "workflow", "source": source},
        )

    def _extract_goal_title(self, text: str) -> Optional[str]:
        t = (text or "").strip()
        if not t:
            return None

        m = re.search(
            r"(?i)\b(?:kreiraj|napravi|dodaj|create)\s+(?:cilj|goal)\s*[:\-]\s*(.+)",
            t,
        )
        if m:
            rest = (m.group(1) or "").strip()
            rest = re.split(r"[\n\r\.]", rest, maxsplit=1)[0].strip(" ,:-")
            if rest:
                return rest

        fields = self._parse_common_fields(t, entity="goal")
        title = (fields.title or "").strip()
        return title or None

    def _extract_day_plan_tasks(self, text: str) -> List[Tuple[str, Optional[str]]]:
        t = (text or "").strip()
        if not t:
            return []

        out: List[Tuple[str, Optional[str]]] = []

        matches = list(re.finditer(r"(?i)\bDan\s*(\d{1,2})\s*:\s*", t))
        if not matches:
            return out

        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
            seg = t[start:end].strip()
            seg = seg.splitlines()[0].strip() if seg else seg

            prio = None
            pm = re.search(r"\(([^)]+)\)", seg)
            if pm:
                prio_candidate = (pm.group(1) or "").strip()
                prio_candidate = prio_candidate.split(",")[0].strip()
                prio_candidate = prio_candidate.split(";")[0].strip()
                if prio_candidate:
                    prio = prio_candidate
                seg = re.sub(r"\s*\([^)]+\)\s*", " ", seg).strip()

            seg = re.sub(r"(?i)^\s*(task|zadatak)\s*\d*\s*[:\-]\s*", "", seg).strip()
            seg = seg.strip(" .,-")

            if seg:
                out.append((seg, prio))

        return out

    def _extract_subgoals_as_tasks(self, text: str) -> List[Tuple[str, Optional[str]]]:
        t = (text or "").strip()
        if not t:
            return []

        if not re.search(r"(?i)\bpodcilj\b", t):
            return []

        out: List[Tuple[str, Optional[str]]] = []

        m = re.search(r"(?i)\bpodcilj(?:a|e|i)?\b\s*[:\-]?\s*(.+)", t)
        if not m:
            return out

        tail = (m.group(1) or "").strip()
        tail = re.split(
            r"(?i)\b(7\s*[- ]?\s*dnevni|14\s*[- ]?\s*dnevni|plan|Dan\s*\d+\s*:|task|zadatak)\b",
            tail,
        )[0].strip()

        parts = [p.strip() for p in tail.split(",") if p.strip()]
        for p in parts:
            prio = None
            pm = re.search(r"(?i)\bprioritet\b\s*([^\)\.\n,;]+)", p)
            if pm:
                pr = (pm.group(1) or "").strip()
                pr = pr.split(",")[0].strip()
                pr = pr.split(";")[0].strip()
                prio = pr or None

            title = re.sub(r"\([^)]+\)", " ", p)
            title = re.sub(r"(?i)\bprioritet\b\s*[^\.\n,;]+", " ", title)
            title = re.sub(r"(?i)\bpodcilj\b", "", title)
            title = re.sub(r"\s+", " ", title).strip(" :.-")

            if title:
                out.append((f"Podcilj: {title}", prio))

        return out

    # ------------------------------------------------------------
    # GOAL TRANSLATION
    # ------------------------------------------------------------
    def _translate_goal(
        self, text: str, *, source: str, context: Dict[str, Any]
    ) -> Optional[AICommand]:
        t = text.strip()

        if re.search(
            r"\b(list\s+goals|prikaži\s+ciljeve|prikazi\s+ciljeve)\b",
            t,
            re.IGNORECASE,
        ):
            return AICommand(
                command="list_goals",
                intent="read",
                read_only=True,
                params={"query": t},
                initiator=str(context.get("initiator") or "ceo"),
                validated=True,
                metadata={"context_type": "ux", "source": source},
            )

        if not re.search(r"^(create|kreiraj|napravi|dodaj)\s+", t, re.IGNORECASE):
            return None
        if not re.search(r"\b(goal|cilj)\b", t, re.IGNORECASE):
            return None

        fields = self._parse_common_fields(t, entity="goal")
        if not fields.title:
            return None

        specs: Dict[str, Any] = {"Name": {"type": "title", "text": fields.title}}
        specs["Status"] = {"type": "status", "name": fields.status or "Not started"}

        if fields.priority:
            specs["Priority"] = {"type": "select", "name": fields.priority}

        if fields.due:
            specs["Deadline"] = {"type": "date", "start": fields.due}

        if fields.description:
            specs["Description"] = {"type": "rich_text", "text": fields.description}

        return AICommand(
            command="notion_write",
            intent="create_page",
            read_only=False,
            params={"db_key": "goals", "property_specs": specs},
            initiator=str(context.get("initiator") or "ceo"),
            validated=True,
            metadata={"context_type": "ux", "source": source},
        )

    # ------------------------------------------------------------
    # TASK TRANSLATION
    # ------------------------------------------------------------
    def _translate_task(
        self, text: str, *, source: str, context: Dict[str, Any]
    ) -> Optional[AICommand]:
        t = text.strip()

        if not re.search(r"^(create|kreiraj|napravi|dodaj)\s+", t, re.IGNORECASE):
            return None

        if not re.search(r"\b(task|zadatak|todo|to-do)\b", t, re.IGNORECASE):
            return None

        fields = self._parse_common_fields(t, entity="task")
        if not fields.title:
            return None

        specs: Dict[str, Any] = {
            "Name": {"type": "title", "text": fields.title},
            "Status": {"type": "select", "name": fields.status or "Not started"},
        }

        if fields.priority:
            specs["Priority"] = {"type": "select", "name": fields.priority}

        if fields.due:
            specs["Due Date"] = {"type": "date", "start": fields.due}

        if fields.description:
            specs["Description"] = {"type": "rich_text", "text": fields.description}

        return AICommand(
            command="notion_write",
            intent="create_page",
            read_only=False,
            params={"db_key": "tasks", "property_specs": specs},
            initiator=str(context.get("initiator") or "ceo"),
            validated=True,
            metadata={"context_type": "ux", "source": source},
        )

    # ------------------------------------------------------------
    # PARSING HELPERS
    # ------------------------------------------------------------
    def _parse_common_fields(self, text: str, *, entity: str) -> _ParsedFields:
        raw = text.strip()

        status = self._extract_field_value(raw, "status")
        priority = self._extract_field_value(raw, "prioritet") or self._extract_field_value(
            raw, "priority"
        )
        due_raw = (
            self._extract_field_value(raw, "due")
            or self._extract_field_value(raw, "rok")
            or self._extract_field_value(raw, "deadline")
        )
        due = self._try_parse_date_to_iso(due_raw) if due_raw else None

        description = (
            self._extract_field_value(raw, "opis")
            or self._extract_field_value(raw, "description")
            or self._extract_field_value(raw, "desc")
        )

        cleaned = raw
        cleaned = re.sub(
            r"(?i)\b(status|prioritet|priority|due|rok|deadline|opis|description|desc)\b.*$",
            "",
            cleaned,
        ).strip(" ,.-")

        if entity == "goal":
            cleaned = re.sub(
                r"(?i)^(create|kreiraj|napravi|dodaj)\s+(goal|cilj)\s*[:\-]?\s*",
                "",
                cleaned,
            ).strip()
        else:
            cleaned = re.sub(
                r"(?i)^(create|kreiraj|napravi|dodaj)\s+(task|zadatak|todo|to-do)\s*[:\-]?\s*",
                "",
                cleaned,
            ).strip()

        title = cleaned.strip(" ,.-")

        return _ParsedFields(
            title=title,
            status=status.strip(" ,.-") if isinstance(status, str) and status.strip() else None,
            priority=priority.strip(" ,.-") if isinstance(priority, str) and priority.strip() else None,
            due=due,
            description=description.strip() if isinstance(description, str) and description.strip() else None,
        )

    @staticmethod
    def _extract_field_value(text: str, key: str) -> Optional[str]:
        """
        Robust extractor that stops at punctuation or next directive keywords.
        Fixes the Notion select/status issue: prevents capturing full sentences.
        """
        if not text or not key:
            return None

        m = re.search(rf"(?i)\b{re.escape(key)}\b\s*[: ]+\s*", text)
        if not m:
            return None

        tail = text[m.end() :].strip()
        if not tail:
            return None

        stop_re = re.compile(
            r"(?i)([\n\r,;\.])|(\b(prioritet|priority|due|rok|deadline|opis|description|desc|kreiraj|napravi|dodaj|create|plan|dan|task|tasks|zadatak|zadaci|podcilj|subgoal)\b)"
        )

        stop = stop_re.search(tail)
        if stop:
            tail = tail[: stop.start()].strip()

        tail = tail.strip().strip('"').strip("'").strip()

        if "," in tail:
            tail = tail.split(",")[0].strip()

        return tail or None

    @staticmethod
    def _try_parse_date_to_iso(value: str) -> Optional[str]:
        if not isinstance(value, str) or not value.strip():
            return None

        v = value.strip()

        m = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})$", v)
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            return f"{y}-{mo}-{d}"

        m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})\.?$", v)
        if m:
            d, mo, y = m.group(1), m.group(2), m.group(3)
            return f"{y}-{mo}-{d}"

        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(v, fmt)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                continue

        return None

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return False
        if "?" in t:
            return True
        if re.match(r"(?i)^(šta|sta|kako|zašto|zasto|why|how|what)\b", t):
            return True
        if re.search(r"(?i)\b(prikaži|prikazi|pogledaj|procitaj|read|show|list)\b", t):
            return True
        return False

    @staticmethod
    def _kv_extract(text: str, key: str) -> Optional[str]:
        m = re.search(rf"(?i)\b{re.escape(key)}\b\s*[:=]\s*([^\n;]+)", text)
        if not m:
            return None
        return (m.group(1) or "").strip()

    @staticmethod
    def _try_extract_inline_json(text: str) -> Optional[Dict[str, Any]]:
        matches = list(re.finditer(r"\{.*\}", text, flags=re.DOTALL))
        if not matches:
            return None
        candidate = matches[-1].group(0)
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _split_goal_and_tasks(text: str) -> Tuple[Optional[str], List[str]]:
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            return None, []

        joined = " ".join(lines)
        m = re.split(r"(?i)\b(tasks|zadaci|zadatci)\b\s*[:\-]?", joined, maxsplit=1)
        goal_part = (m[0] or "").strip(" :,-") if m else joined.strip()

        task_titles: List[str] = []
        for ln in lines:
            mm = re.match(r"(?i)^(task|zadatak)\s*[:\-]\s*(.+)$", ln)
            if mm:
                title = (mm.group(2) or "").strip()
                if title:
                    task_titles.append(title)

        if not task_titles:
            after = False
            for ln in lines:
                if re.search(r"(?i)\b(tasks|zadaci|zadatci)\b", ln):
                    after = True
                    continue
                if after:
                    mm = re.match(r"^\s*[-*]\s*(.+)$", ln)
                    if mm:
                        title = (mm.group(1) or "").strip()
                        if title:
                            task_titles.append(title)

        return (goal_part if goal_part else None, task_titles)
