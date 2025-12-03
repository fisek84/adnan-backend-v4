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
    # INTERNAL HELPERS
    # ------------------------------------------------------
    def _now(self):
        return datetime.now(timezone.utc)

    # ------------------------------------------------------
    # PUBLIC — CREATE
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
            deadline=data.deadline,
            primary_goal_id=data.primary_goal_id,
            status=data.status or "active",
            progress=data.progress or 0,
            tasks=data.tasks or [],
            created_at=now,
            updated_at=now,
        )

        self.projects[project_id] = project

        if self.sync_service:
            try:
                self.sync_service.debounce_projects_sync()
            except:
                pass

        return project

    # ------------------------------------------------------
    # PUBLIC — UPDATE
    # ------------------------------------------------------
    def update_project(self, project_id: str, updates: ProjectUpdate) -> ProjectModel:
        project = self.projects.get(project_id)
        if not project:
            raise ValueError("Project not found")

        for field in [
            "title",
            "description",
            "deadline",
            "primary_goal_id",
            "status",
            "progress",
        ]:
            val = getattr(updates, field, None)
            if val is not None:
                setattr(project, field, val)

        project.updated_at = self._now()

        if self.sync_service:
            self.sync_service.debounce_projects_sync()

        return project

    # ------------------------------------------------------
    # PUBLIC — DELETE
    # ------------------------------------------------------
    def delete_project(self, project_id: str):
        proj = self.projects.get(project_id)
        if not proj:
            raise ValueError("Project not found")

        removed = self.projects.pop(project_id)

        if self.sync_service:
            self.sync_service.debounce_projects_sync()

        return removed

    # ------------------------------------------------------
    # GET ALL
    # ------------------------------------------------------
    def get_all(self) -> List[ProjectModel]:
        return list(self.projects.values())

    def get(self, project_id: str) -> Optional[ProjectModel]:
        return self.projects.get(project_id)

    # ------------------------------------------------------
    # USED BY AUTO-ASSIGN
    # ------------------------------------------------------
    def get_all_tasks_for_project(self, project_id: str):
        project = self.projects.get(project_id)
        if not project:
            return []
        return project.tasks

    # ------------------------------------------------------
    # HELPERS FOR NOTION SYNC (REQUIRED)
    # ------------------------------------------------------
    def to_dict(self, p: ProjectModel) -> dict:
        return {
            "id": p.id,
            "notion_id": p.notion_id,
            "title": p.title,
            "description": p.description,
            "deadline": p.deadline,
            "primary_goal_id": p.primary_goal_id,
            "status": p.status,
            "progress": p.progress,
            "tasks": p.tasks,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }

    def to_create_model(self, mapped: dict) -> ProjectCreate:
        """
        Pretvara mapped Notion projekt → ProjectCreate model.
        Ovo koristi NotionSyncService.load_projects_into_backend().
        """
        return ProjectCreate(
            title=mapped["title"],
            description=mapped["description"],
            deadline=mapped["deadline"],
            primary_goal_id=mapped["primary_goal_id"],
            status=mapped["status"],
            progress=mapped["progress"],
            tasks=mapped.get("tasks", []),
        )
