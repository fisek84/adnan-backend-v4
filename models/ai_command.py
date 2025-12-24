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
    # EXECUTION IDS (KLJUĆNO)
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

    # Pydantic v2 configuration
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # ========================================================
    # NORMALIZATION (POST)
    # ========================================================
    @model_validator(mode="after")
    def normalize_ids(self) -> "AICommand":
        # Ako execution_id nije postavljen, normalizujemo ga na request_id
        if not self.execution_id:
            object.__setattr__(self, "execution_id", self.request_id)

        # owner je uvijek "system" (bez trigera validate_assignment)
        if self.owner != "system":
            object.__setattr__(self, "owner", "system")

        return self

    @classmethod
    def log(cls, command: "AICommand") -> None:
        logger.info(
            "[AICommand] command=%s intent=%s execution_id=%s approval_id=%s read_only=%s",
            command.command,
            command.intent,
            command.execution_id,
            command.approval_id,
            command.read_only,
        )
