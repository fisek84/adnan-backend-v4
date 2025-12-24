from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from pydantic import BaseModel, Field

NOTION_API_URL = "https://api.notion.com/v1"
DEFAULT_NOTION_VERSION = "2022-06-28"

DEFAULT_HTTP_TIMEOUT_SEC = 20
DEFAULT_PAGE_SIZE = 100
DEFAULT_EXCERPT_LINES = 40
DEFAULT_MAX_ROWS = 50


class ConfigurationError(RuntimeError):
    """Config / environment error for CEO console snapshot service."""


class CeoGoal(BaseModel):
    id: str
    name: str
    status: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[dt.date] = None


class CeoTask(BaseModel):
    id: str
    title: str
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[dt.date] = None
    lead: Optional[str] = None


class CeoApprovalSummary(BaseModel):
    pending: int = 0
    approved_today: int = 0
    total_completed: int = 0
    errors: int = 0


class WeeklyPriorityItem(BaseModel):
    source_type: str  # "goal" or "task"
    id: str
    title: str
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[dt.date] = None


class CeoDashboardSnapshot(BaseModel):
    generated_at: dt.datetime
    goals: List[CeoGoal]
    tasks: List[CeoTask]
    weekly_priority: List[WeeklyPriorityItem]
    approvals: CeoApprovalSummary
    metadata: Dict[str, Any] = Field(default_factory=dict)


@dataclass
class _NotionConfig:
    token: str
    version: str

    goals_db_id: str
    tasks_db_id: str
    approvals_db_id: Optional[str] = None

    sop_db_id: Optional[str] = None
    plans_db_id: Optional[str] = None
    time_management_page_id: Optional[str] = None

    goal_name_prop: str = "Name"
    goal_status_prop: str = "Status"
    goal_priority_prop: str = "Priority"
    goal_deadline_prop: str = "Deadline"

    task_title_prop: str = "Name"
    task_status_prop: str = "Status"
    task_priority_prop: str = "Priority"
    task_due_date_prop: str = "Due"
    task_lead_prop: str = "Lead"

    approval_status_prop: str = "Status"
    approval_last_change_prop: str = "Last change"

    priority_window_days: int = 7
    priority_high_values: Optional[List[str]] = None

    http_timeout_sec: int = DEFAULT_HTTP_TIMEOUT_SEC
    max_rows: int = DEFAULT_MAX_ROWS
    excerpt_lines: int = DEFAULT_EXCERPT_LINES

    def __post_init__(self) -> None:
        if self.priority_high_values is None:
            self.priority_high_values = ["High", "Visok", "Critical"]


class _NotionClient:
    def __init__(self, config: _NotionConfig) -> None:
        self._config = config

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.token}",
            "Notion-Version": self._config.version,
            "Content-Type": "application/json",
        }

    def query_database(
        self,
        database_id: str,
        filter_: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_rows: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        url = f"{NOTION_API_URL}/databases/{database_id}/query"
        payload: Dict[str, Any] = {"page_size": page_size}
        if filter_:
            payload["filter"] = filter_
        if sorts:
            payload["sorts"] = sorts

        results: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None

        max_rows_eff = max_rows if isinstance(max_rows, int) and max_rows > 0 else None

        while True:
            if next_cursor:
                payload["start_cursor"] = next_cursor

            resp = requests.post(
                url,
                headers=self._headers,
                json=payload,
                timeout=self._config.http_timeout_sec,
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Notion query failed (status={resp.status_code}): {resp.text}"
                )

            data = resp.json()
            batch = data.get("results", [])
            if isinstance(batch, list):
                results.extend(batch)

            if max_rows_eff is not None and len(results) >= max_rows_eff:
                return results[:max_rows_eff]

            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break

        return results

    def retrieve_page(self, page_id: str) -> Dict[str, Any]:
        url = f"{NOTION_API_URL}/pages/{page_id}"
        resp = requests.get(url, headers=self._headers, timeout=self._config.http_timeout_sec)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Notion retrieve page failed (status={resp.status_code}): {resp.text}"
            )
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def list_block_children(
        self, block_id: str, page_size: int = 50, max_blocks: int = 100
    ) -> List[Dict[str, Any]]:
        url = f"{NOTION_API_URL}/blocks/{block_id}/children?page_size={page_size}"
        results: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None

        while True:
            full_url = url
            if next_cursor:
                full_url = f"{url}&start_cursor={next_cursor}"

            resp = requests.get(full_url, headers=self._headers, timeout=self._config.http_timeout_sec)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Notion list block children failed (status={resp.status_code}): {resp.text}"
                )

            data = resp.json()
            batch = data.get("results", [])
            if isinstance(batch, list):
                results.extend(batch)

            if len(results) >= max_blocks:
                return results[:max_blocks]

            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break

        return results


class CeoConsoleSnapshotService:
    def __init__(
        self,
        notion_client: Optional[_NotionClient] = None,
        config: Optional[_NotionConfig] = None,
    ) -> None:
        self._notion: Optional[_NotionClient] = notion_client
        self._cfg: Optional[_NotionConfig] = config
        self._ready: bool = False
        self._init_error: Optional[str] = None

        if self._notion is not None and self._cfg is not None:
            self._ready = True
            return

        try:
            svc = self.from_env()
            self._notion = svc._notion
            self._cfg = svc._cfg
            self._ready = True
        except Exception as e:
            self._ready = False
            self._init_error = str(e)

    @staticmethod
    def _env_first(*names: str) -> Optional[str]:
        for n in names:
            v = os.getenv(n)
            if v and v.strip():
                return v.strip()
        return None

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            return default
        try:
            return int(raw.strip())
        except Exception:
            return default

    @classmethod
    def from_env(cls) -> "CeoConsoleSnapshotService":
        token = cls._env_first("NOTION_TOKEN", "NOTION_API_KEY", "NOTION_KEY")
        if not token:
            raise ConfigurationError("NOTION_TOKEN or NOTION_API_KEY must be set.")

        goals_db_id = cls._env_first("NOTION_GOALS_DATABASE_ID", "NOTION_GOALS_DB_ID")
        tasks_db_id = cls._env_first("NOTION_TASKS_DATABASE_ID", "NOTION_TASKS_DB_ID")
        if not goals_db_id or not tasks_db_id:
            raise ConfigurationError(
                "NOTION_GOALS_DATABASE_ID/NOTION_GOALS_DB_ID and "
                "NOTION_TASKS_DATABASE_ID/NOTION_TASKS_DB_ID must be set."
            )

        approvals_db_id = cls._env_first("NOTION_APPROVALS_DATABASE_ID", "NOTION_APPROVALS_DB_ID")
        version = cls._env_first("NOTION_VERSION") or DEFAULT_NOTION_VERSION

        cfg = _NotionConfig(
            token=token,
            version=version,
            goals_db_id=goals_db_id,
            tasks_db_id=tasks_db_id,
            approvals_db_id=approvals_db_id,
            sop_db_id=cls._env_first("NOTION_SOP_DATABASE_ID", "NOTION_SOP_DB_ID"),
            plans_db_id=cls._env_first("NOTION_PLANS_DATABASE_ID", "NOTION_PLANS_DB_ID"),
            time_management_page_id=cls._env_first("NOTION_TIME_MANAGEMENT_PAGE_ID"),
            goal_name_prop=cls._env_first("NOTION_GOAL_NAME_PROP") or "Name",
            goal_status_prop=cls._env_first("NOTION_GOAL_STATUS_PROP") or "Status",
            goal_priority_prop=cls._env_first("NOTION_GOAL_PRIORITY_PROP") or "Priority",
            goal_deadline_prop=cls._env_first("NOTION_GOAL_DEADLINE_PROP") or "Deadline",
            task_title_prop=cls._env_first("NOTION_TASK_TITLE_PROP") or "Name",
            task_status_prop=cls._env_first("NOTION_TASK_STATUS_PROP") or "Status",
            task_priority_prop=cls._env_first("NOTION_TASK_PRIORITY_PROP") or "Priority",
            task_due_date_prop=cls._env_first("NOTION_TASK_DUE_PROP") or "Due",
            task_lead_prop=cls._env_first("NOTION_TASK_LEAD_PROP") or "Lead",
            approval_status_prop=cls._env_first("NOTION_APPROVAL_STATUS_PROP") or "Status",
            approval_last_change_prop=cls._env_first("NOTION_APPROVAL_LAST_CHANGE_PROP") or "Last change",
            priority_window_days=cls._env_int("CEO_PRIORITY_WINDOW_DAYS", 7),
            http_timeout_sec=cls._env_int("NOTION_HTTP_TIMEOUT_SEC", DEFAULT_HTTP_TIMEOUT_SEC),
            max_rows=cls._env_int("CEO_SNAPSHOT_MAX_ROWS", DEFAULT_MAX_ROWS),
            excerpt_lines=cls._env_int("CEO_SNAPSHOT_EXCERPT_LINES", DEFAULT_EXCERPT_LINES),
        )

        high_values_env = cls._env_first("CEO_PRIORITY_HIGH_VALUES")
        if high_values_env:
            cfg.priority_high_values = [v.strip() for v in high_values_env.split(",") if v.strip()]

        return cls(notion_client=_NotionClient(cfg), config=cfg)

    def build_snapshot(self) -> CeoDashboardSnapshot:
        self._require_ready()
        assert self._notion is not None
        assert self._cfg is not None

        now = dt.datetime.utcnow()

        goals = self._load_goals()
        tasks = self._load_tasks()
        weekly_priority = self._build_weekly_priority(goals, tasks)
        approvals = self._build_approvals_summary()

        meta = self._base_metadata()
        meta["kind"] = "dashboard_snapshot"

        return CeoDashboardSnapshot(
            generated_at=now,
            goals=goals,
            tasks=tasks,
            weekly_priority=weekly_priority,
            approvals=approvals,
            metadata=meta,
        )

    def snapshot(self) -> Dict[str, Any]:
        if not self._ready:
            return {
                "available": False,
                "source": "ceo_console_snapshot_service",
                "error": self._init_error or "snapshot service not configured",
            }

        try:
            dash = self.build_snapshot()
            extra = self._build_ceo_advisory_knowledge()
            return {
                "available": True,
                "source": "ceo_console_snapshot_service",
                "generated_at": dash.generated_at.isoformat(),
                "dashboard": dash.model_dump(),
                "knowledge": extra,
            }
        except Exception as e:
            return {"available": False, "source": "ceo_console_snapshot_service", "error": str(e)}

    def get_snapshot(self) -> Dict[str, Any]:
        return self.snapshot()

    def _require_ready(self) -> None:
        if not self._ready or self._notion is None or self._cfg is None:
            raise ConfigurationError(self._init_error or "Snapshot service not ready")

    def _base_metadata(self) -> Dict[str, Any]:
        assert self._cfg is not None
        return {
            "source": "ceo_console_snapshot_service",
            "notion_version": self._cfg.version,
            "priority_window_days": self._cfg.priority_window_days,
        }

    @staticmethod
    def _is_missing_sort_property_error(err: Exception) -> bool:
        s = str(err)
        return (
            "Could not find sort property" in s
            or "sort property with name or id" in s
            or "validation_error" in s and "sort" in s.lower()
        )

    def _safe_query_with_optional_sort(
        self,
        database_id: str,
        sorts: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        assert self._notion is not None
        assert self._cfg is not None

        if not sorts:
            return self._notion.query_database(database_id, filter_=None, sorts=None, max_rows=self._cfg.max_rows)

        try:
            return self._notion.query_database(database_id, filter_=None, sorts=sorts, max_rows=self._cfg.max_rows)
        except RuntimeError as e:
            if self._is_missing_sort_property_error(e):
                # fallback: no sorts (snapshot must not die because of schema mismatch)
                return self._notion.query_database(database_id, filter_=None, sorts=None, max_rows=self._cfg.max_rows)
            raise

    def _build_ceo_advisory_knowledge(self) -> Dict[str, Any]:
        assert self._cfg is not None
        assert self._notion is not None

        knowledge: Dict[str, Any] = {
            "sop": {"available": False},
            "plans": {"available": False},
            "time_management": {"available": False},
        }

        if self._cfg.sop_db_id:
            knowledge["sop"] = self._summarize_simple_database(self._cfg.sop_db_id, "Name", "sop")

        if self._cfg.plans_db_id:
            knowledge["plans"] = self._summarize_simple_database(self._cfg.plans_db_id, "Name", "plans")

        if self._cfg.time_management_page_id:
            knowledge["time_management"] = self._read_page_excerpt(self._cfg.time_management_page_id, "time_management")

        return knowledge

    def _summarize_simple_database(self, database_id: str, title_prop: str, label: str) -> Dict[str, Any]:
        assert self._cfg is not None
        assert self._notion is not None

        out: Dict[str, Any] = {"available": False, "label": label, "items": []}
        try:
            rows = self._notion.query_database(database_id, filter_=None, sorts=None, max_rows=self._cfg.max_rows)
            items: List[Dict[str, Any]] = []
            for row in rows:
                props: Dict[str, Any] = row.get("properties", {}) if isinstance(row, dict) else {}
                title = self._extract_title(props.get(title_prop)) or "(untitled)"
                items.append({"id": row.get("id", ""), "title": title})
            out["available"] = True
            out["count"] = len(items)
            out["items"] = items
            return out
        except Exception as e:
            out["error"] = str(e)
            return out

    def _read_page_excerpt(self, page_id: str, label: str) -> Dict[str, Any]:
        assert self._cfg is not None
        assert self._notion is not None

        out: Dict[str, Any] = {"available": False, "label": label, "page_id": page_id, "title": None, "excerpt": []}
        try:
            page = self._notion.retrieve_page(page_id)
            props = page.get("properties", {}) if isinstance(page, dict) else {}
            title = self._try_extract_page_title(props)

            blocks = self._notion.list_block_children(block_id=page_id, max_blocks=200)
            lines = self._extract_block_plain_text_lines(blocks)
            excerpt = lines[: self._cfg.excerpt_lines]

            out["available"] = True
            out["title"] = title
            out["excerpt"] = excerpt
            out["excerpt_lines"] = len(excerpt)
            return out
        except Exception as e:
            out["error"] = str(e)
            return out

    @staticmethod
    def _try_extract_page_title(props: Dict[str, Any]) -> Optional[str]:
        for _, val in props.items():
            if isinstance(val, dict) and (val.get("type") == "title" or "title" in val):
                title = CeoConsoleSnapshotService._extract_title(val)
                if title:
                    return title
        return None

    @staticmethod
    def _extract_block_plain_text_lines(blocks: List[Dict[str, Any]]) -> List[str]:
        lines: List[str] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            b_type = b.get("type")
            content = b.get(b_type) if isinstance(b_type, str) else None
            if not isinstance(content, dict):
                continue
            rich = content.get("rich_text")
            if isinstance(rich, list):
                text = CeoConsoleSnapshotService._join_rich_text(rich)
                if text:
                    lines.append(text)
        return lines

    @staticmethod
    def _join_rich_text(rich: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for item in rich:
            if not isinstance(item, dict):
                continue
            pt = item.get("plain_text")
            if isinstance(pt, str) and pt.strip():
                parts.append(pt)
        return "".join(parts).strip()

    def _load_goals(self) -> List[CeoGoal]:
        assert self._cfg is not None

        rows = self._safe_query_with_optional_sort(
            self._cfg.goals_db_id,
            sorts=[{"property": self._cfg.goal_deadline_prop, "direction": "ascending"}],
        )

        goals: List[CeoGoal] = []
        for row in rows:
            props: Dict[str, Any] = row.get("properties", {}) if isinstance(row, dict) else {}
            name = self._extract_title(props.get(self._cfg.goal_name_prop))
            status = self._extract_select(props.get(self._cfg.goal_status_prop))
            priority = self._extract_select(props.get(self._cfg.goal_priority_prop))
            deadline = self._extract_date(props.get(self._cfg.goal_deadline_prop))

            goals.append(
                CeoGoal(
                    id=row.get("id", ""),
                    name=name or "(untitled goal)",
                    status=status,
                    priority=priority,
                    deadline=deadline,
                )
            )
        return goals

    def _load_tasks(self) -> List[CeoTask]:
        assert self._cfg is not None

        rows = self._safe_query_with_optional_sort(
            self._cfg.tasks_db_id,
            sorts=[{"property": self._cfg.task_due_date_prop, "direction": "ascending"}],
        )

        tasks: List[CeoTask] = []
        for row in rows:
            props: Dict[str, Any] = row.get("properties", {}) if isinstance(row, dict) else {}
            title = self._extract_title(props.get(self._cfg.task_title_prop))
            status = self._extract_select(props.get(self._cfg.task_status_prop))
            priority = self._extract_select(props.get(self._cfg.task_priority_prop))
            due = self._extract_date(props.get(self._cfg.task_due_date_prop))
            lead = self._extract_people_or_rich_text(props.get(self._cfg.task_lead_prop))

            tasks.append(
                CeoTask(
                    id=row.get("id", ""),
                    title=title or "(untitled task)",
                    status=status,
                    priority=priority,
                    due_date=due,
                    lead=lead,
                )
            )
        return tasks

    def _build_weekly_priority(self, goals: List[CeoGoal], tasks: List[CeoTask]) -> List[WeeklyPriorityItem]:
        assert self._cfg is not None

        window = dt.timedelta(days=self._cfg.priority_window_days)
        today = dt.date.today()
        max_date = today + window

        def is_high(priority: Optional[str]) -> bool:
            return bool(priority and priority in (self._cfg.priority_high_values or []))

        items: List[WeeklyPriorityItem] = []
        for g in goals:
            if g.deadline and is_high(g.priority) and today <= g.deadline <= max_date:
                items.append(
                    WeeklyPriorityItem(
                        source_type="goal",
                        id=g.id,
                        title=g.name,
                        status=g.status,
                        priority=g.priority,
                        due_date=g.deadline,
                    )
                )

        for t in tasks:
            if t.due_date and is_high(t.priority) and today <= t.due_date <= max_date:
                items.append(
                    WeeklyPriorityItem(
                        source_type="task",
                        id=t.id,
                        title=t.title,
                        status=t.status,
                        priority=t.priority,
                        due_date=t.due_date,
                    )
                )

        items.sort(key=lambda i: (i.due_date or dt.date.max, i.title.lower()))
        return items

    def _build_approvals_summary(self) -> CeoApprovalSummary:
        assert self._cfg is not None
        assert self._notion is not None

        if not self._cfg.approvals_db_id:
            return CeoApprovalSummary()

        rows = self._notion.query_database(
            self._cfg.approvals_db_id,
            filter_=None,
            sorts=None,
            max_rows=self._cfg.max_rows,
        )

        today = dt.date.today()
        pending = approved_today = completed = errors = 0

        for row in rows:
            props: Dict[str, Any] = row.get("properties", {}) if isinstance(row, dict) else {}
            status = self._extract_select(props.get(self._cfg.approval_status_prop))
            last_change_date = self._extract_date(props.get(self._cfg.approval_last_change_prop))
            if not status:
                continue

            normalized = status.lower()
            if "pending" in normalized or "blocked" in normalized:
                pending += 1
            elif "approved" in normalized:
                completed += 1
                if last_change_date and last_change_date == today:
                    approved_today += 1
            elif "executed" in normalized or "done" in normalized or "completed" in normalized:
                completed += 1
            elif "error" in normalized or "failed" in normalized:
                errors += 1

        return CeoApprovalSummary(
            pending=pending,
            approved_today=approved_today,
            total_completed=completed,
            errors=errors,
        )

    @staticmethod
    def _extract_title(prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None
        title_items = prop.get("title") or prop.get("rich_text")
        if not isinstance(title_items, list):
            return None
        texts: List[str] = []
        for item in title_items:
            if isinstance(item, dict):
                text = item.get("plain_text")
                if isinstance(text, str) and text:
                    texts.append(text)
        return "".join(texts) if texts else None

    @staticmethod
    def _extract_select(prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None
        select = prop.get("select") or prop.get("status")
        if not isinstance(select, dict):
            return None
        name = select.get("name")
        return name if isinstance(name, str) else None

    @staticmethod
    def _extract_date(prop: Optional[Dict[str, Any]]) -> Optional[dt.date]:
        if not prop:
            return None
        date_obj = prop.get("date")
        if not isinstance(date_obj, dict):
            return None
        start = date_obj.get("start")
        if not isinstance(start, str) or not start:
            return None
        try:
            iso = start.replace("Z", "+00:00")
            if "T" in iso:
                return dt.datetime.fromisoformat(iso).date()
            return dt.date.fromisoformat(iso)
        except Exception:
            return None

    @staticmethod
    def _extract_people_or_rich_text(prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop or not isinstance(prop, dict):
            return None

        if "people" in prop:
            people = prop.get("people") or []
            names: List[str] = []
            if isinstance(people, list):
                for p in people:
                    if isinstance(p, dict):
                        name = p.get("name") or p.get("email")
                        if isinstance(name, str) and name:
                            names.append(name)
            if names:
                return ", ".join(names)

        if "rich_text" in prop:
            rt = prop.get("rich_text") or []
            texts: List[str] = []
            if isinstance(rt, list):
                for item in rt:
                    if isinstance(item, dict):
                        t = item.get("plain_text")
                        if isinstance(t, str) and t:
                            texts.append(t)
            if texts:
                return "".join(texts)

        return None


CEOConsoleSnapshotService = CeoConsoleSnapshotService
