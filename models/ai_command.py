from pydantic import BaseModel, Field, root_validator
from typing import Optional, Any, Dict
import logging
import uuid


# ============================================================
# LOGGER SETUP
# ============================================================

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================
# AI COMMAND / REQUEST CONTEXT (CANONICAL)
# ============================================================

class AICommand(BaseModel):
    """
    Canonical AI Command Context.

    ROLE MODEL (NON-NEGOTIABLE):
    - initiator: ko je IZAZVAO zahtjev (CEO / human)
    - owner: ko POSJEDUJE komandu (system / agent / integration)
    - executor: ko IZVRŠAVA komandu (agent / system worker)
    """

    # --------------------------------------------------------
    # CORE COMMAND (SYSTEM LANGUAGE)
    # --------------------------------------------------------

    command: str = Field(
        ...,
        description="Canonical system command name (must exist in action_dictionary)"
    )

    intent: Optional[str] = Field(
        None,
        description="High-level semantic intent extracted by COO (non-executable)"
    )

    validated: bool = Field(
        default=False,
        description="Set to True ONLY by COO Translator after full validation"
    )

    # --------------------------------------------------------
    # ROLE SEPARATION (CRITICAL)
    # --------------------------------------------------------

    initiator: Optional[str] = Field(
        None,
        description="Who requested the action (ceo, human)"
    )

    owner: Optional[str] = Field(
        None,
        description="Who owns the command semantics (system, agent, integration)"
    )

    executor: Optional[str] = Field(
        None,
        description="Who executes the command (agent or system worker)"
    )

    # --------------------------------------------------------
    # BUSINESS PAYLOAD
    # --------------------------------------------------------

    input: Optional[Any] = Field(
        None,
        description="Business payload for the command (domain-specific data)"
    )

    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Command modifiers and options (non-business logic)"
    )

    # --------------------------------------------------------
    # EXECUTION / ROUTING METADATA
    # --------------------------------------------------------

    agent: Optional[str] = Field(
        None,
        description="Agent responsible for execution (optional explicit routing)"
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Routing, tracing, and technical metadata"
    )

    # --------------------------------------------------------
    # REQUEST CONTEXT (FOUNDATION)
    # --------------------------------------------------------

    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique request identifier (traceable across entire system)"
    )

    identity_snapshot: Optional[Dict[str, Any]] = Field(
        None,
        description="Loaded identity snapshot at request time"
    )

    state_snapshot: Optional[Dict[str, Any]] = Field(
        None,
        description="Loaded system state snapshot at request time"
    )

    mode_snapshot: Optional[Dict[str, Any]] = Field(
        None,
        description="Active operating mode snapshot"
    )

    execution_state: Optional[str] = Field(
        None,
        description="Execution lifecycle state"
    )

    awareness_flags: Dict[str, Any] = Field(
        default_factory=dict,
        description="Awareness hints"
    )

    # --------------------------------------------------------
    # NORMALIZATION (CANONICAL ROLE FIX)
    # --------------------------------------------------------

    @root_validator(pre=True)
    def normalize_roles_and_request_id(cls, values):
        metadata = values.get("metadata") or {}

        # request_id normalization
        if "request_id" in metadata and "request_id" not in values:
            values["request_id"] = metadata.pop("request_id")

        # initiator defaults to CEO / human
        if not values.get("initiator"):
            values["initiator"] = "ceo"

        # owner is ALWAYS system unless explicitly overridden
        if not values.get("owner"):
            values["owner"] = "system"

        # executor resolved later by orchestrator
        if not values.get("executor"):
            values["executor"] = "agent"

        return values

    # --------------------------------------------------------
    # Pydantic config
    # --------------------------------------------------------

    class Config:
        extra = "forbid"
        validate_assignment = True

    # ========================================================
    # LOGGING HELPERS
    # ========================================================

    @classmethod
    def log_command(cls, command: "AICommand"):
        logger.info(
            f"[AICommand] {command.command} | request_id={command.request_id} "
            f"| initiator={command.initiator} | owner={command.owner} | executor={command.executor}"
        )
