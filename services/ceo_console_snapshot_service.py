from __future__ import annotations

import os
import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from pydantic import BaseModel, Field

NOTION_API_URL = "https://api.notion.com/v1"
DEFAULT_NOTION_VERSION = "2022-06-28"


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
    """Glavni payload koji vidi frontend CEO dashboarda."""

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

    def __post_init__(self) -> None:
        if self.priority_high_values is None:
            # Dodaj svoje vrijednosti ako koristiš lokalizirane statuse
            self.priority_high_values = ["High", "Visok", "Critical"]


class _NotionClient:
    """Minimal, read-only Notion client (poštuje CANON – READ path only)."""

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
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        url = f"{NOTION_API_URL}/databases/{database_id}/query"
        payload: Dict[str, Any] = {"page_size": page_size}
        if filter_:
            payload["filter"] = filter_
        if sorts:
            payload["sorts"] = sorts

        results: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None

        while True:
            if next_cursor:
                payload["start_cursor"] = next_cursor

            resp = requests.post(url, headers=self._headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Notion query failed (status={resp.status_code}): {resp.text}"
                )

            data = resp.json()
            results.extend(data.get("results", []))
            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break

        return results


class CeoConsoleSnapshotService:
    """
    Servis koji čita iz Notiona i vraća jedan snapshot
    za CEO dashboard (bez ikakvih write/side-effect akcija).
    """

    def __init__(self, notion_client: _NotionClient, config: _NotionConfig) -> None:
        self._notion = notion_client
        self._cfg = config

    # ------------- Public API -------------

    @classmethod
    def from_env(cls) -> "CeoConsoleSnapshotService":
        """
        Factory koji čita sve što treba iz env varijabli.

        Obavezno:
          - NOTION_TOKEN ili NOTION_API_KEY
          - NOTION_GOALS_DATABASE_ID
          - NOTION_TASKS_DATABASE_ID

        Opcionalno:
          - NOTION_APPROVALS_DATABASE_ID
          - NOTION_VERSION
          - i override property imena ako želiš (vidi ispod).
        """
        token = os.getenv("NOTION_TOKEN") or os.getenv("NOTION_API_KEY")
        if not token:
            raise ConfigurationError("NOTION_TOKEN or NOTION_API_KEY must be set.")

        goals_db_id = os.getenv("NOTION_GOALS_DATABASE_ID")
        tasks_db_id = os.getenv("NOTION_TASKS_DATABASE_ID")

        if not goals_db_id or not tasks_db_id:
            raise ConfigurationError(
                "NOTION_GOALS_DATABASE_ID and NOTION_TASKS_DATABASE_ID must be set."
            )

        approvals_db_id = os.getenv("NOTION_APPROVALS_DATABASE_ID")
        version = os.getenv("NOTION_VERSION") or DEFAULT_NOTION_VERSION

        cfg = _NotionConfig(
            token=token,
            version=version,
            goals_db_id=goals_db_id,
            tasks_db_id=tasks_db_id,
            approvals_db_id=approvals_db_id,
            goal_name_prop=os.getenv("NOTION_GOAL_NAME_PROP", "Name"),
            goal_status_prop=os.getenv("NOTION_GOAL_STATUS_PROP", "Status"),
            goal_priority_prop=os.getenv("NOTION_GOAL_PRIORITY_PROP", "Priority"),
            goal_deadline_prop=os.getenv("NOTION_GOAL_DEADLINE_PROP", "Deadline"),
            task_title_prop=os.getenv("NOTION_TASK_TITLE_PROP", "Name"),
            task_status_prop=os.getenv("NOTION_TASK_STATUS_PROP", "Status"),
            task_priority_prop=os.getenv("NOTION_TASK_PRIORITY_PROP", "Priority"),
            task_due_date_prop=os.getenv("NOTION_TASK_DUE_PROP", "Due"),
            task_lead_prop=os.getenv("NOTION_TASK_LEAD_PROP", "Lead"),
            approval_status_prop=os.getenv("NOTION_APPROVAL_STATUS_PROP", "Status"),
            approval_last_change_prop=os.getenv(
                "NOTION_APPROVAL_LAST_CHANGE_PROP", "Last change"
            ),
            priority_window_days=int(os.getenv("CEO_PRIORITY_WINDOW_DAYS", "7")),
        )

        high_values_env = os.getenv("CEO_PRIORITY_HIGH_VALUES")
        if high_values_env:
            cfg.priority_high_values = [
                v.strip() for v in high_values_env.split(",") if v.strip()
            ]

        notion_client = _NotionClient(cfg)
        return cls(notion_client=notion_client, config=cfg)

    def build_snapshot(self) -> CeoDashboardSnapshot:
        """
        Glavna metoda – frontendu vraća jedan snapshot,
        bez ikakvog mutiranja sistema (pure READ).
        """
        now = dt.datetime.utcnow()

        goals = self._load_goals()
        tasks = self._load_tasks()
        weekly_priority = self._build_weekly_priority(goals, tasks)
        approvals = self._build_approvals_summary()

        meta = {
            "source": "ceo_console_snapshot_service",
            "notion_version": self._cfg.version,
            "priority_window_days": self._cfg.priority_window_days,
        }

        return CeoDashboardSnapshot(
            generated_at=now,
            goals=goals,
            tasks=tasks,
            weekly_priority=weekly_priority,
            approvals=approvals,
            metadata=meta,
        )

    # ------------- Interno: Goals -------------

    def _load_goals(self) -> List[CeoGoal]:
        rows = self._notion.query_database(
            self._cfg.goals_db_id,
            filter_=None,
            sorts=[
                {"property": self._cfg.goal_deadline_prop, "direction": "ascending"}
            ],
        )

        goals: List[CeoGoal] = []
        for row in rows:
            props: Dict[str, Any] = row.get("properties", {})

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

    # ------------- Interno: Tasks -------------

    def _load_tasks(self) -> List[CeoTask]:
        rows = self._notion.query_database(
            self._cfg.tasks_db_id,
            filter_=None,
            sorts=[
                {"property": self._cfg.task_due_date_prop, "direction": "ascending"}
            ],
        )

        tasks: List[CeoTask] = []
        for row in rows:
            props: Dict[str, Any] = row.get("properties", {})

            title = self._extract_title(props.get(self._cfg.task_title_prop))
            status = self._extract_select(props.get(self._cfg.task_status_prop))
            priority = self._extract_select(props.get(self._cfg.task_priority_prop))
            due = self._extract_date(props.get(self._cfg.task_due_date_prop))
            lead = self._extract_people_or_rich_text(
                props.get(self._cfg.task_lead_prop)
            )

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

    # ------------- Interno: Weekly priority -------------

    def _build_weekly_priority(
        self, goals: List[CeoGoal], tasks: List[CeoTask]
    ) -> List[WeeklyPriorityItem]:
        window = dt.timedelta(days=self._cfg.priority_window_days)
        today = dt.date.today()
        max_date = today + window

        items: List[WeeklyPriorityItem] = []

        def is_high(priority: Optional[str]) -> bool:
            if not priority:
                return False
            return priority in self._cfg.priority_high_values

        for g in goals:
            if not g.deadline or not is_high(g.priority):
                continue
            if today <= g.deadline <= max_date:
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
            if not t.due_date or not is_high(t.priority):
                continue
            if today <= t.due_date <= max_date:
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

        # Sortiraj po datumu pa po nazivu
        items.sort(key=lambda i: (i.due_date or dt.date.max, i.title.lower()))
        return items

    # ------------- Interno: Approvals -------------

    def _build_approvals_summary(self) -> CeoApprovalSummary:
        if not self._cfg.approvals_db_id:
            # Ako nema DB za approvals, vrati nule – UX ne izmišlja stanje
            return CeoApprovalSummary()

        rows = self._notion.query_database(
            self._cfg.approvals_db_id,
            filter_=None,
            sorts=None,
        )

        today = dt.date.today()

        pending = 0
        approved_today = 0
        completed = 0
        errors = 0

        for row in rows:
            props: Dict[str, Any] = row.get("properties", {})
            status = self._extract_select(props.get(self._cfg.approval_status_prop))
            last_change_date = self._extract_date(
                props.get(self._cfg.approval_last_change_prop)
            )

            if not status:
                continue

            normalized = status.lower()
            if "pending" in normalized or "blocked" in normalized:
                pending += 1
            elif "approved" in normalized:
                completed += 1
                if last_change_date and last_change_date == today:
                    approved_today += 1
            elif (
                "executed" in normalized
                or "done" in normalized
                or "completed" in normalized
            ):
                completed += 1
            elif "error" in normalized or "failed" in normalized:
                errors += 1

        return CeoApprovalSummary(
            pending=pending,
            approved_today=approved_today,
            total_completed=completed,
            errors=errors,
        )

    # ------------- Interno: Notion helpers -------------

    @staticmethod
    def _extract_title(prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None
        # Notion "title" property: list of rich_text
        title_items = prop.get("title") or prop.get("rich_text")
        if not isinstance(title_items, list):
            return None
        texts: List[str] = []
        for item in title_items:
            text = item.get("plain_text")
            if text:
                texts.append(text)
        return "".join(texts) if texts else None

    @staticmethod
    def _extract_select(prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None
        select = prop.get("select") or prop.get("status")
        if not select:
            return None
        name = select.get("name")
        return name

    @staticmethod
    def _extract_date(prop: Optional[Dict[str, Any]]) -> Optional[dt.date]:
        if not prop:
            return None
        date_obj = prop.get("date")
        if not date_obj:
            return None
        start = date_obj.get("start")
        if not start:
            return None
        try:
            # Notion date start is ISO string
            if "T" in start:
                return dt.datetime.fromisoformat(start).date()
            return dt.date.fromisoformat(start)
        except Exception:
            return None

    @staticmethod
    def _extract_people_or_rich_text(prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None

        if "people" in prop:
            people = prop.get("people") or []
            names: List[str] = []
            for p in people:
                name = p.get("name") or p.get("email")
                if name:
                    names.append(name)
            if names:
                return ", ".join(names)

        if "rich_text" in prop:
            texts: List[str] = []
            for item in prop.get("rich_text") or []:
                t = item.get("plain_text")
                if t:
                    texts.append(t)
            if texts:
                return "".join(texts)

        return None
