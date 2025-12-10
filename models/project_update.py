from pydantic import BaseModel
from typing import Optional, List
import logging  # Dodajemo logovanje

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None

    start_date: Optional[str] = None
    deadline: Optional[str] = None

    project_type: Optional[str] = None
    summary: Optional[str] = None
    next_step: Optional[str] = None

    # unified naming across Create/Model/Sync
    primary_goal_id: Optional[str] = None

    parent_id: Optional[str] = None

    agents: Optional[List[str]] = None
    tasks: Optional[List[str]] = None

    handled_by: Optional[str] = None

    # important — used in ProjectsService.update_project
    progress: Optional[int] = None

    # ---------------------------------------------------------
    # VALIDATIONS
    # ---------------------------------------------------------

    @classmethod
    def validate_status(cls, value: Optional[str]):
        if value is None:
            return value
        allowed = {"pending", "in_progress", "completed"}
        if value not in allowed:
            logger.error(f"Invalid status value: {value}. Must be one of: {allowed}")
            raise ValueError(f"Status must be one of: {allowed}")
        logger.info(f"Valid status value: {value}")
        return value

    @classmethod
    def validate_priority(cls, value: Optional[str]):
        if value is None:
            return value
        allowed = {"low", "medium", "high"}
        if value not in allowed:
            logger.error(f"Invalid priority value: {value}. Must be one of: {allowed}")
            raise ValueError(f"Priority must be one of: {allowed}")
        logger.info(f"Valid priority value: {value}")
        return value

    @classmethod
    def validate_deadline(cls, value: Optional[str]):
        if value is None:
            return value
        try:
            # Proveravamo samo format datuma (ISO 8601)
            datetime.fromisoformat(value)
        except ValueError:
            logger.error(f"Invalid deadline format: {value}")
            raise ValueError("Deadline must be in ISO format YYYY-MM-DD")
        logger.info(f"Valid deadline format: {value}")
        return value

    class Config:
        extra = "forbid"
