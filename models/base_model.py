from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import logging  # Dodajemo logovanje

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# TASK MODEL (FINAL — OVO JE NEDOSTAJALO)
# ============================================================
class TaskModel(BaseModel):
    id: str
    notion_id: Optional[str] = Field(
        None, description="Notion page ID for sync/delete"
    )

    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None

    goal_id: Optional[str] = None
    priority: Optional[str] = None
    status: str
    order: int = 0

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        validate_assignment = True

    @classmethod
    def log_task_creation(cls, task: "TaskModel"):
        logger.info(f"Creating task: {task.title} with ID: {task.id}")
        logger.debug(f"Task details: {task.dict()}")

    @classmethod
    def log_task_update(cls, task: "TaskModel"):
        logger.info(f"Updating task: {task.title} with ID: {task.id}")
        logger.debug(f"Updated task details: {task.dict()}")
