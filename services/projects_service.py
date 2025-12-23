from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from uuid import uuid4

from models.project_model import ProjectModel
from models.project_create import ProjectCreate
from models.project_update import ProjectUpdate

from services.write_gateway.write_gateway import WriteGateway, WriteEnvelope


class ProjectsService:
    def __init__(self, write_gateway: Optional[WriteGateway] = None):
        self.projects: Dict[str, ProjectModel] = {}
        self.goals_service = None
        self.tasks_service = None
        self.sync_service = None

        self.write_gateway = write_gateway or WriteGateway()

        # SSOT enforcement handlers
        self.write_gateway.register_handler("projects_create", self._wg_create_project)
        self.write_gateway.register_handler("projects_update", self._wg_update_project)
        self.write_gateway.register_handler("projects_delete", self._wg_delete_project)

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

    def _trigger_sync(self):
        if self.sync_service:
            try:
                self.sync_service.debounce_projects_sync()
            except Exception:
                pass

    def _wg_execution_id(self, payload: dict) -> str:
        exec_id = payload.get("execution_id") or payload.get("idempotency_key")
        if isinstance(exec_id, str) and exec_id.strip():
            return exec_id.strip()
        return f"exec_{uuid4().hex}"

    def _replace_id(self, old_id: str, new_notion_id: str):
        if old_id not in self.projects:
            return

        project = self.projects.pop(old_id)
        clean_id = new_notion_id.replace("-", "")
        project.id = clean_id
        project.notion_id = new_notion_id
        self.projects[clean_id] = project

    # ------------------------------------------------------
    # CREATE (WRITE via gateway)
    # ------------------------------------------------------
    async def create_project(
        self,
        data: ProjectCreate,
        forced_id: Optional[str] = None,
        notion_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = data.model_dump() if hasattr(data, "model_dump") else dict(data)
        envelope = {
            "command": "projects_create",
            "actor_id": str(payload.get("actor_id") or "system"),
            "resource": "projects",
            "payload": {
                "data": payload,
                "forced_id": forced_id,
                "notion_id": notion_id,
            },
            "task_id": "PROJECTS_CREATE",
            "execution_id": self._wg_execution_id(payload),
            "metadata": payload.get("metadata")
            if isinstance(payload.get("metadata"), dict)
            else None,
            "approval_id": payload.get("approval_id"),
        }
        return await self.write_gateway.write(envelope)

    # ------------------------------------------------------
    # UPDATE (WRITE via gateway)
    # ------------------------------------------------------
    async def update_project(
        self, project_id: str, updates: ProjectUpdate
    ) -> Dict[str, Any]:
        payload = (
            updates.model_dump() if hasattr(updates, "model_dump") else dict(updates)
        )
        envelope = {
            "command": "projects_update",
            "actor_id": str(payload.get("actor_id") or "system"),
            "resource": f"project:{project_id}",
            "payload": {"project_id": project_id, "updates": payload},
            "task_id": "PROJECTS_UPDATE",
            "execution_id": self._wg_execution_id(payload),
            "metadata": payload.get("metadata")
            if isinstance(payload.get("metadata"), dict)
            else None,
            "approval_id": payload.get("approval_id"),
        }
        return await self.write_gateway.write(envelope)

    # ------------------------------------------------------
    # DELETE (WRITE via gateway)
    # ------------------------------------------------------
    async def delete_project(self, project_id: str) -> Dict[str, Any]:
        envelope = {
            "command": "projects_delete",
            "actor_id": "system",
            "resource": f"project:{project_id}",
            "payload": {"project_id": project_id},
            "task_id": "PROJECTS_DELETE",
            "execution_id": f"exec_{uuid4().hex}",
        }
        return await self.write_gateway.write(envelope)

    # ------------------------------------------------------
    # GETTERS
    # ------------------------------------------------------
    def get_all(self) -> List[ProjectModel]:
        return list(self.projects.values())

    def get(self, project_id: str) -> Optional[ProjectModel]:
        return self.projects.get(project_id)

    # ------------------------------------------------------
    # WRITE GATEWAY HANDLERS (REAL DOMAIN SIDE EFFECTS)
    # ------------------------------------------------------
    async def _wg_create_project(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        data_dict = payload.get("data") or {}
        forced_id = payload.get("forced_id")
        notion_id = payload.get("notion_id")

        data = ProjectCreate(**data_dict) if isinstance(data_dict, dict) else data_dict

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
        self._trigger_sync()

        return {"project_id": project_id, "notion_id": notion_id}

    async def _wg_update_project(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        project_id = str(payload.get("project_id") or "").strip()
        updates_dict = payload.get("updates") or {}

        project = self.projects.get(project_id)
        if not project:
            raise ValueError("Project not found")

        updates = (
            ProjectUpdate(**updates_dict)
            if isinstance(updates_dict, dict)
            else updates_dict
        )

        for field in [
            "title",
            "description",
            "status",
            "category",
            "priority",
            "start_date",
            "deadline",
            "project_type",
            "summary",
            "next_step",
            "goal_id",
            "parent_id",
            "agents",
            "tasks",
            "handled_by",
        ]:
            val = getattr(updates, field, None)
            if val is not None:
                setattr(project, field, val)

        project.updated_at = self._now()
        self._trigger_sync()

        return {"project_id": project_id, "updated": True}

    async def _wg_delete_project(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        project_id = str(payload.get("project_id") or "").strip()

        proj = self.projects.get(project_id)
        if not proj:
            raise ValueError("Project not found")

        self.projects.pop(project_id)
        self._trigger_sync()

        return {
            "project_id": project_id,
            "deleted": True,
            "notion_id": getattr(proj, "notion_id", None),
        }

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
