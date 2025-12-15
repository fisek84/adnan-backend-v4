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
    Canonical AI Request Context.
    This object travels through the entire pipeline:
    API → UX → COO → Safety → Execution → Response
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

    source: str = Field(
        ...,
        description="Command source (user, voice, agent, system)"
    )

    validated: bool = Field(
        default=False,
        description="Set to True ONLY by COO Translator after full validation"
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
        description="Agent responsible for execution"
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Routing, tracing, and technical metadata (NO request_id here)"
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
        description="Execution lifecycle state (IDLE, WAITING_APPROVAL, EXECUTING, COMPLETED, FAILED)"
    )

    awareness_flags: Dict[str, Any] = Field(
        default_factory=dict,
        description="Awareness hints (waiting_for_confirmation, clarification_needed, etc.)"
    )

    # --------------------------------------------------------
    # NORMALIZATION
    # --------------------------------------------------------

    @root_validator(pre=True)
    def normalize_request_id(cls, values):
        """
        If request_id is mistakenly passed via metadata,
        normalize it into the canonical field.
        """
        metadata = values.get("metadata") or {}
        if "request_id" in metadata and "request_id" not in values:
            values["request_id"] = metadata.pop("request_id")
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
            f"[AICommand] {command.command} | request_id={command.request_id} | source={command.source}"
        )
        logger.debug(f"[AICommand] intent={command.intent}")
        logger.debug(f"[AICommand] validated={command.validated}")
        logger.debug(f"[AICommand] input={command.input}")
        logger.debug(f"[AICommand] agent={command.agent}")
        logger.debug(f"[AICommand] params={command.params}")
        logger.debug(f"[AICommand] metadata={command.metadata}")
        logger.debug(f"[AICommand] execution_state={command.execution_state}")
        logger.debug(f"[AICommand] awareness_flags={command.awareness_flags}")

    @classmethod
    def log_command_error(cls, command: "AICommand", error: str):
        logger.error(
            f"[AICommand ERROR] {command.command} | request_id={command.request_id}"
        )
        logger.error(f"[AICommand ERROR] details={error}")
        logger.debug(f"[AICommand ERROR] intent={command.intent}")
        logger.debug(f"[AICommand ERROR] source={command.source}")
        logger.debug(f"[AICommand ERROR] validated={command.validated}")
        logger.debug(f"[AICommand ERROR] input={command.input}")
        logger.debug(f"[AICommand ERROR] agent={command.agent}")
        logger.debug(f"[AICommand ERROR] params={command.params}")
        logger.debug(f"[AICommand ERROR] metadata={command.metadata}")
