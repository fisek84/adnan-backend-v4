from pydantic import BaseModel, Field
from typing import Optional, Any, Dict
import logging  # Dodajemo logovanje

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class AICommand(BaseModel):
    """
    Universal command structure for AI operations.
    This model is used to drive AI agents, processors, and
    command pipelines across the entire Evolia system.
    """

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

    params: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional parameters / modifiers for the command"
    )

    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Execution metadata: routing, tokens, context flags, etc."
    )

    class Config:
        extra = "forbid"
        validate_assignment = True

    # Logovanje komandi
    @classmethod
    def log_command(cls, command: "AICommand"):
        logger.info(f"Received AI command: {command.command}")
        logger.debug(f"Command input: {command.input}")
        logger.debug(f"Command agent: {command.agent}")
        logger.debug(f"Command params: {command.params}")
        logger.debug(f"Command metadata: {command.metadata}")

    # Logovanje grešaka pri izvršenju komandi
    @classmethod
    def log_command_error(cls, command: "AICommand", error: str):
        logger.error(f"Error executing AI command: {command.command}")
        logger.error(f"Error details: {error}")
        logger.debug(f"Failed command input: {command.input}")
        logger.debug(f"Command agent: {command.agent}")
        logger.debug(f"Command params: {command.params}")
        logger.debug(f"Command metadata: {command.metadata}")
