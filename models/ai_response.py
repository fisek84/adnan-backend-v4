from pydantic import BaseModel, Field
from typing import Optional, Any, Dict
import logging  # Dodajemo logovanje

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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

    @classmethod
    def log_success(cls, response: "AIResponse"):
        if response.success:
            logger.info(f"AI operation succeeded: {response.message}")
            logger.debug(f"AI result: {response.result}")
            logger.debug(f"AI metadata: {response.metadata}")

    @classmethod
    def log_failure(cls, response: "AIResponse"):
        if not response.success:
            logger.error(f"AI operation failed: {response.message}")
            if response.error:
                logger.error(f"Error details: {response.error}")
            logger.debug(f"Failed AI result: {response.result}")
            logger.debug(f"AI metadata: {response.metadata}")
