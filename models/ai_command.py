from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AICommand(BaseModel):
    """
    CANONICAL AI COMMAND MODEL

    HARD CANON:
    - execution_id is immutable SSOT for execution lifecycle
    - approval_id is REQUIRED for any write execution (enforced downstream)
    - model is STRICT (extra=forbid)
    """

    # ========================================================
    # CORE
    # ========================================================
    command: str
    intent: Optional[str] = None
    read_only: bool = False
    validated: bool = False

    # ========================================================
    # ROLES (CANON)
    # ========================================================
    initiator: str = "ceo"
    owner: str = "system"
    executor: Optional[str] = None

    # ========================================================
    # CONTEXT
    # ========================================================
    context_type: Optional[str] = None

    # ========================================================
    # PAYLOAD
    # ========================================================
    params: Dict[str, Any] = Field(default_factory=dict)

    # ========================================================
    # EXECUTION IDS (SSOT)
    # ========================================================
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: Optional[str] = None
    approval_id: Optional[str] = None

    # ========================================================
    # STATE
    # ========================================================
    execution_state: Optional[str] = None

    # ========================================================
    # GOVERNANCE ARTIFACTS
    # ========================================================
    decision: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None

    # ========================================================
    # METADATA
    # ========================================================
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # ========================================================
    # CONFIG
    # ========================================================
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        frozen=False,
    )

    # ========================================================
    # NORMALIZATION (POST INIT)
    # ========================================================
    @model_validator(mode="after")
    def normalize_ids(self) -> "AICommand":
        # execution_id is SSOT; default to request_id if missing
        if not isinstance(self.execution_id, str) or not self.execution_id.strip():
            object.__setattr__(self, "execution_id", self.request_id)

        # owner is always system
        if self.owner != "system":
            object.__setattr__(self, "owner", "system")

        return self

    # ========================================================
    # LOGGING
    # ========================================================
    @classmethod
    def log(cls, command: "AICommand") -> None:
        logger.info(
            "[AICommand] command=%s intent=%s execution_id=%s approval_id=%s read_only=%s state=%s",
            command.command,
            command.intent,
            command.execution_id,
            command.approval_id,
            command.read_only,
            command.execution_state,
        )
