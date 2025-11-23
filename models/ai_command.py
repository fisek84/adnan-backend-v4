from pydantic import BaseModel, Field
from typing import Optional, Any, Dict


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