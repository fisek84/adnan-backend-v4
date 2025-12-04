import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, List
import logging

from models.task_create import TaskCreate
from models.task_model import TaskModel
from services.notion_service import NotionService

# Inicijalizacija loggera
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class TasksService:
    goals_service = None
    sync_service = None

    def __init__(self, notion_service: NotionService):
        self.tasks: Dict[str, TaskModel] = {}
        self.notion = notion_service  # NotionService injection

    # ------------------------------------------------------------
    # BINDINGS
    # ------------------------------------------------------------
    def bind_goals_service(self, goals_service):
        self.goals_service = goals_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------
    def _now(self):
        return datetime.now(timezone.utc)

    def _trigger_sync(self):
        if not self.sync_service:
            return
        
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_tasks_sync())
        except RuntimeError:
            asyncio.get_event_loop().create_task(
                self.sync_service.debounce_tasks_sync()
            )

    # ------------------------------------------------------------
    # CREATE TASK
    # ------------------------------------------------------------
    async def create_task(self, data: TaskCreate) -> TaskModel:
        logger.info("Starting task creation...")
        now = self._now()
        task_id = uuid4().hex

        # Provjera da li je goals_service inicijaliziran
        if not self.goals_service:
            logger.error("Goals service is not initialized. Please bind goals service before using.")
            raise ValueError("Goals service is not initialized. Please bind goals service before using.")

        # Provjera da li 'title' postoji
        if not data.title:
            logger.error("Title is required to create a task.")
            raise ValueError("Title is required to create a task.")

        logger.info(f"Creating task with title: {data.title}")

        # Ako goal_id postoji, konvertiraj ga u string
        if data.goal_id:
            try:
                # Osiguraj da goal_id bude string, bez obzira na to je li poslan kao UUID ili string
                data.goal_id = str(data.goal_id)  
                logger.info(f"Using existing goal_id: {data.goal_id}")
            except Exception as e:
                logger.error(f"Error converting goal_id: {e}")
                raise ValueError("Invalid goal_id format.")
        else:
            logger.info("No goal_id provided, task is being created without goal.")

        # Kreiranje taska
        task = TaskModel(
            id=task_id,
            notion_id=None,
            title=data.title,
            description=data.description,
            goal_id=str(data.goal_id) if data.goal_id else None,  # goal_id može biti None ako nije poslan
            deadline=data.deadline,
            priority=data.priority,
            status=data.status or "pending",
            order=0,
            created_at=now,
            updated_at=now,
        )

        logger.info(f"Task created with ID: {task.id}")

        self.tasks[task_id] = task

        # Povezivanje sa Notion-om
        try:
            res = await self.notion.create_task(task)
            logger.info(f"Notion response: {res}")
        except Exception as e:
            logger.error(f"Error connecting to Notion: {e}")
            raise ValueError("Failed to create task in Notion.")
        
        if isinstance(res, str):
            res = {"ok": False, "error": res}
        if not isinstance(res, dict):
            res = {"ok": False, "error": "Invalid Notion response"}

        res.setdefault("ok", False)
        res.setdefault("data", {})

        if res["ok"] and "id" in res["data"]:
            task.notion_id = res["data"]["id"]
            logger.info(f"Task successfully created in Notion with Notion ID: {task.notion_id}")

        self._trigger_sync()  # Sinhronizacija sa Notion-om
        return task

    # ------------------------------------------------------------
    # GET ALL TASKS
    # ------------------------------------------------------------
    def get_all_tasks(self) -> List[TaskModel]:
        """
        Vraća sve zadatke.
        """
        logger.info(f"[TASKS] Total tasks in service: {len(self.tasks)}")
        return list(self.tasks.values())  # Vraća sve zadatke kao listu

    # ------------------------------------------------------------
    # UPDATE TASK
    # ------------------------------------------------------------
    def update_task(self, task_id: str, data: dict) -> TaskModel:
        """
        Ažurira zadatak na osnovu prosleđenog task_id i podataka.
        """
        if task_id not in self.tasks:  
            logger.error(f"Task with id {task_id} not found")
            raise ValueError(f"Task with id {task_id} not found")

        task = self.tasks[task_id]

        # Ažuriranje zadatka sa novim podacima
        task.title = data.get('title', task.title)
        task.description = data.get('description', task.description)
        task.deadline = data.get('deadline', task.deadline)
        task.priority = data.get('priority', task.priority)
        task.status = data.get('status', task.status)

        # Ažuriraj datum poslednje izmene
        task.updated_at = self._now()

        logger.info(f"Task with id {task_id} updated successfully")

        # Vraćanje ažuriranog zadatka
        return task

    # ------------------------------------------------------------
    # DELETE TASK
    # ------------------------------------------------------------
    async def delete_task(self, task_id: str) -> dict:
        """
        Briše zadatak sa zadatim task_id.
        """
        if task_id not in self.tasks:
            logger.error(f"Task with id {task_id} not found")
            raise ValueError(f"Task with id {task_id} not found")

        task = self.tasks.pop(task_id)  # Uklanjamo zadatak iz self.tasks
        logger.info(f"Task with id {task_id} deleted locally")

        return {"ok": True, "task": task}
