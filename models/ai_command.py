from pydantic import BaseModel, Field, root_validator
from typing import Optional, Any, Dict
import logging
import uuid


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AICommand(BaseModel):
    """
    Canonical AI Command.

    ROLE MODEL (NON-NEGOTIABLE):
    - initiator: ko je IZAZVAO zahtjev (CEO / human)
    - owner: ko POSJEDUJE semantiku (SYSTEM)
    - executor: ko IZVRŠAVA (system_worker | agent)
    """

    # ========================================================
    # CORE SIGNALS
    # ========================================================
    command: str = Field(
        ...,
        description="Canonical system directive label (READ or WRITE category)"
    )

    intent: Optional[str] = Field(
        None,
        description="Semantic intent for WRITE execution (domain-level)"
    )

    read_only: bool = Field(
        default=False,
        description="Explicit READ / WRITE flag. True = READ, False = WRITE"
    )

    validated: bool = Field(
        default=False,
        description="Set ONLY by COOTranslationService after hard validation"
    )

    # ========================================================
    # ROLE SEPARATION (CRITICAL)
    # ========================================================
    initiator: str = Field(
        default="ceo",
        description="Who initiated the request (human)"
    )

    owner: str = Field(
        default="system",
        description="Who owns the command semantics (SYSTEM)"
    )

    executor: Optional[str] = Field(
        None,
        description="Who executes the command (resolved later)"
    )

    # ========================================================
    # PAYLOAD
    # ========================================================
    input: Optional[Any] = Field(
        None,
        description="Business payload (domain data)"
    )

    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Execution modifiers"
    )

    # ========================================================
    # EXECUTION METADATA
    # ========================================================
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Routing / tracing metadata"
    )

    approval_id: Optional[str] = Field(
        default=None,
        description="Approval ID required for WRITE commands"
    )

    # ========================================================
    # REQUEST CONTEXT
    # ========================================================
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Global request identifier"
    )

    identity_snapshot: Optional[Dict[str, Any]] = None
    state_snapshot: Optional[Dict[str, Any]] = None
    mode_snapshot: Optional[Dict[str, Any]] = None

    execution_state: Optional[str] = None

    awareness_flags: Dict[str, Any] = Field(
        default_factory=dict,
        description="Awareness hints"
    )

    # ========================================================
    # NORMALIZATION (KANONSKI)
    # ========================================================
    @root_validator(pre=True)
    def normalize(cls, values):
        metadata = values.get("metadata") or {}

        # request_id propagation
        if "request_id" in metadata and "request_id" not in values:
            values["request_id"] = metadata["request_id"]

        # owner is ALWAYS system
        values["owner"] = "system"

        # executor resolved later
        if "executor" not in values:
            values["executor"] = None

        # approval_id may come via metadata
        if not values.get("approval_id"):
            values["approval_id"] = metadata.get("approval_id")

        # READ / WRITE MUST BE EXPLICIT (NO INFERENCE)
        if "read_only" not in values:
            values["read_only"] = False

        return values

    # ========================================================
    # CONFIG
    # ========================================================
    class Config:
        extra = "forbid"
        validate_assignment = True

    # ========================================================
    # LOGGING
    # ========================================================
    @classmethod
    def log(cls, command: "AICommand"):
        logger.info(
            f"[AICommand] command={command.command} | intent={command.intent} "
            f"| read_only={command.read_only} | request_id={command.request_id} "
            f"| initiator={command.initiator} | owner={command.owner} | executor={command.executor}"
        )
