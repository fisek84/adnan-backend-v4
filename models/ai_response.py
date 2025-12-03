from pydantic import BaseModel, Field
from typing import Optional, Any, Dict


class AIResponse(BaseModel):
    """
    Standardized response wrapper for all AI operations.
    Ensures a consistent structure for commands, agents,
    transformers, and processing pipelines.
    """

    success: bool = Field(
        ..., description="True if the AI operation completed successfully"
    )

    result: Optional[Any] = Field(
        None, description="Main output of the AI operation"
    )

    message: Optional[str] = Field(
        None,
        description="Human-readable message or explanation of the result"
    )

    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional AI-generated metadata (tokens, time, routing, etc.)"
    )

    error: Optional[str] = Field(
        None, description="Error message if operation failed"
    )

    class Config:
        extra = "forbid"
        validate_assignment = True