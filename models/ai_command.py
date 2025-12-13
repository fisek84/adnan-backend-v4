from pydantic import BaseModel, Field
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
    API → Intent → CSI → Decision → Awareness → Execution → Response
    """

    # --------------------------------------------------------
    # CORE COMMAND
    # --------------------------------------------------------

    command: str = Field(
        ...,
        description="Primary name/type of the AI command (e.g., 'summarize', 'plan', 'analyze')",
    )

    input: Optional[Any] = Field(
        None,
        description="Main input payload for the command (text, JSON, dict, list, etc.)"
    )

    agent: Optional[str] = Field(
        None,
        description="Agent executing the command (e.g., 'Adnan.AI', 'Planner', 'SyncBot')"
    )

    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional parameters / modifiers for the command"
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Execution metadata: routing, tokens, context flags, etc."
    )

    # --------------------------------------------------------
    # REQUEST CONTEXT (V0.1 FOUNDATION)
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
            f"[AICommand] {command.command} | request_id={command.request_id}"
        )
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
        logger.debug(f"[AICommand ERROR] input={command.input}")
        logger.debug(f"[AICommand ERROR] agent={command.agent}")
        logger.debug(f"[AICommand ERROR] params={command.params}")
        logger.debug(f"[AICommand ERROR] metadata={command.metadata}")
