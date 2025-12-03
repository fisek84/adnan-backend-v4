# services/tasks_service.py

from typing import List
from datetime import datetime
import logging  # Dodajemo logovanje

from models.task_model import TaskModel
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from services.notion_service import NotionService
from utils.helpers import generate_uuid
from services.auto_assign_engine import AutoAssignEngine

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Možemo promeniti nivo logovanja (INFO, DEBUG, ERROR)

class TasksService:
    def __init__(self, notion_service: NotionService):
        self.notion = notion_service
        self.local_tasks = {}  # required for sync service
        self.projects_db_id = None   # sync će postaviti ovo kasnije

    # ------------------------------------------------------
    # CREATE
    # ------------------------------------------------------
    async def create_task(self, data: TaskCreate) -> TaskModel:
        task_id = generate_uuid()
        now = datetime.utcnow()

        task = TaskModel(
            id=task_id,
            notion_id=None,
            title=data.title,
            description=data.description or "",
            goal_id=data.goal_id,
            deadline=data.deadline,
            priority=data.priority,
            status="pending",
            order=0,
            created_at=now,
            updated_at=now,
        )

        # save locally
        self.local_tasks[task_id] = task

        # create in notion → returns page_id
        try:
            notion_page_id = await self.notion.create_task(task)
            logger.info(f"Task {task_id} created in Notion with page ID: {notion_page_id}")

            if isinstance(notion_page_id, str):
                task.notion_id = notion_page_id
                self.local_tasks[task_id] = task
            else:
                logger.error(f"Failed to create task {task_id} in Notion: {notion_page_id['error']}")

        except Exception as e:
            logger.error(f"Error creating task {task_id} in Notion: {str(e)}")

        # AUTO-ASSIGN SYSTEM
        if task.notion_id:
            await self._auto_assign_goal_if_missing(task.notion_id)
            await self._auto_assign_project_if_missing(task.notion_id)
            await self._auto_assign_goal_from_project_if_missing(task.notion_id)
            await self._auto_assign_project_if_missing_advanced(task.notion_id)
            await self._auto_assign_goal_from_project_advanced(task.notion_id)

        return task

    # ... (Ostale metode ostaju iste)
