from typing import Dict, List, Optional
from datetime import datetime, timezone

from models.project_model import ProjectModel
from models.project_create import ProjectCreate
from models.project_update import ProjectUpdate


class ProjectsService:
    def __init__(self):
        self.projects: Dict[str, ProjectModel] = {}
        self.goals_service = None
        self.tasks_service = None
        self.sync_service = None

    # ------------------------------------------------------
    # BINDINGS
    # ------------------------------------------------------
    def bind_goals_service(self, goals_service):
        self.goals_service = goals_service

    def bind_tasks_service(self, tasks_service):
        self.tasks_service = tasks_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------
    def _now(self):
        return datetime.now(timezone.utc)

    def _replace_id(self, old_id: str, new_notion_id: str):
        if old_id not in self.projects:
            return

        project = self.projects.pop(old_id)
        clean_id = new_notion_id.replace("-", "")
        project.id = clean_id
        project.notion_id = new_notion_id
        self.projects[clean_id] = project

    # ------------------------------------------------------
    # CREATE
    # ------------------------------------------------------
    def create_project(
        self,
        data: ProjectCreate,
        forced_id: Optional[str] = None,
        notion_id: Optional[str] = None,
    ) -> ProjectModel:

        now = self._now()
        project_id = forced_id or now.strftime("%Y%m%d%H%M%S%f")

        project = ProjectModel(
            id=project_id,
            notion_id=notion_id,
            title=data.title,
            description=data.description,
            status=data.status or "Active",
            category=data.category,
            priority=data.priority,
            start_date=data.start_date,
            deadline=data.deadline,
            project_type=data.project_type,
            summary=data.summary,
            next_step=data.next_step,
            goal_id=getattr(data, "primary_goal_id", None),
            parent_id=data.parent_id,
            agents=data.agents or [],
            tasks=data.tasks or [],
            handled_by=data.handled_by,
            progress=data.progress or 0,
            created_at=now,
            updated_at=now,
        )

        self.projects[project_id] = project

        # 🔥 FIXED — only valid sync trigger
        if self.sync_service:
            try:
                self.sync_service.debounce_projects_sync()
            except Exception:
                pass

        return project

    # ------------------------------------------------------
    # UPDATE
    # ------------------------------------------------------
    def update_project(self, project_id: str, updates: ProjectUpdate) -> ProjectModel:
        project = self.projects.get(project_id)
        if not project:
            raise ValueError("Project not found")

        for field in [
            "title", "description", "status", "category", "priority",
            "start_date", "deadline", "project_type", "summary",
            "next_step", "goal_id", "parent_id", "agents",
            "tasks", "handled_by",
        ]:
            val = getattr(updates, field, None)
            if val is not None:
                setattr(project, field, val)

        project.updated_at = self._now()

        # 🔥 FIXED — only valid sync trigger
        if self.sync_service:
            try:
                self.sync_service.debounce_projects_sync()
            except Exception:
                pass

        return project

    # ------------------------------------------------------
    # DELETE
    # ------------------------------------------------------
    def delete_project(self, project_id: str):
        proj = self.projects.get(project_id)
        if not proj:
            raise ValueError("Project not found")

        removed = self.projects.pop(project_id)

        # 🔥 FIXED — only valid sync trigger
        if self.sync_service:
            try:
                self.sync_service.debounce_projects_sync()
            except Exception:
                pass

        return removed

    # ------------------------------------------------------
    # GETTERS
    # ------------------------------------------------------
    def get_all(self) -> List[ProjectModel]:
        return list(self.projects.values())

    def get(self, project_id: str) -> Optional[ProjectModel]:
        return self.projects.get(project_id)

    # ------------------------------------------------------
    # MAPPERS
    # ------------------------------------------------------
    def to_dict(self, p: ProjectModel) -> dict:
        return {
            "id": p.id,
            "notion_id": p.notion_id,
            "title": p.title,
            "description": p.description,
            "status": p.status,
            "category": p.category,
            "priority": p.priority,
            "start_date": p.start_date,
            "deadline": p.deadline,
            "project_type": p.project_type,
            "summary": p.summary,
            "next_step": p.next_step,
            "primary_goal_id": p.goal_id,
            "parent_id": p.parent_id,
            "agents": p.agents,
            "tasks": p.tasks,
            "handled_by": p.handled_by,
            "progress": p.progress,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }

    def to_create_model(self, mapped: dict) -> ProjectCreate:
        return ProjectCreate(
            title=mapped["title"],
            description=mapped.get("description", ""),
            status=mapped.get("status", "Active"),
            category=mapped.get("category"),
            priority=mapped.get("priority"),
            start_date=mapped.get("start_date"),
            deadline=mapped.get("deadline"),
            project_type=mapped.get("project_type"),
            summary=mapped.get("summary", ""),
            next_step=mapped.get("next_step", ""),
            primary_goal_id=mapped.get("primary_goal_id"),
            parent_id=mapped.get("parent_id"),
            agents=mapped.get("agents", []),
            tasks=mapped.get("tasks", []),
            handled_by=mapped.get("handled_by"),
            progress=mapped.get("progress", 0),
        )
