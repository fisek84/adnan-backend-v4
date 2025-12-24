from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

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

    result: Optional[Any] = Field(None, description="Main output of the AI operation")

    message: Optional[str] = Field(
        None, description="Human-readable message or explanation of the result"
    )

    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional AI-generated metadata (tokens, time, routing, etc.)",
    )

    error: Optional[str] = Field(None, description="Error message if operation failed")

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @classmethod
    def log_success(cls, response: "AIResponse") -> None:
        if response.success:
            logger.info("AI operation succeeded: %s", response.message)
            logger.debug("AI result: %s", response.result)
            logger.debug("AI metadata: %s", response.metadata)

    @classmethod
    def log_failure(cls, response: "AIResponse") -> None:
        if not response.success:
            logger.error("AI operation failed: %s", response.message)
            if response.error:
                logger.error("Error details: %s", response.error)
            logger.debug("Failed AI result: %s", response.result)
            logger.debug("AI metadata: %s", response.metadata)
