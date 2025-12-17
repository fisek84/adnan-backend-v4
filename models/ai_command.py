from pydantic import BaseModel, Field, root_validator
from typing import Optional, Any, Dict
import uuid
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AICommand(BaseModel):
    """
    CANONICAL AI COMMAND MODEL
    """

    # ========================================================
    # CORE
    # ========================================================
    command: str
    intent: Optional[str] = None
    read_only: bool = False
    validated: bool = False

    # ========================================================
    # ROLES (KANON)
    # ========================================================
    initiator: str = "ceo"
    owner: str = "system"
    executor: Optional[str] = None

    # ========================================================
    # PAYLOAD (SINGLE SOURCE OF TRUTH)
    # ========================================================
    params: Dict[str, Any] = Field(default_factory=dict)

    # ========================================================
    # EXECUTION IDS (KLJUČNO)
    # ========================================================
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: Optional[str] = None
    approval_id: Optional[str] = None

    # ========================================================
    # STATE
    # ========================================================
    execution_state: Optional[str] = None

    # ========================================================
    # GOVERNANCE / EXECUTION ARTIFACTS
    # (EKSPPLICITNO, NE SKRIVENO)
    # ========================================================
    decision: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None

    # ========================================================
    # METADATA
    # ========================================================
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # ========================================================
    # NORMALIZATION (POST)
    # ========================================================
    @root_validator(pre=False, skip_on_failure=True)
    def normalize_ids(cls, values):
        if not values.get("execution_id"):
            values["execution_id"] = values["request_id"]

        # owner is always system
        values["owner"] = "system"

        return values

    class Config:
        extra = "forbid"
        validate_assignment = True

    @classmethod
    def log(cls, command: "AICommand"):
        logger.info(
            "[AICommand] command=%s intent=%s execution_id=%s approval_id=%s read_only=%s",
            command.command,
            command.intent,
            command.execution_id,
            command.approval_id,
            command.read_only,
        )
