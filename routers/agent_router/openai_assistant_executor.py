# routers/agent_router/openai_assistant_executor.py
"""
Compatibility shim (router-layer import path).

CANON:
- Single source of truth for the executor implementation is:
  services.agent_router.openai_assistant_executor.OpenAIAssistantExecutor
- This module exists only to preserve import paths used by older code.
"""

from __future__ import annotations

from services.agent_router.openai_assistant_executor import OpenAIAssistantExecutor

__all__ = ["OpenAIAssistantExecutor"]
