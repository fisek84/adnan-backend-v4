from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.ai_command_service import AICommandService
from services.coo_conversation_service import COOConversationService
from services.coo_translation_service import COOTranslationService

# Injected via gateway_server.py (or main bootstrap)
ai_command_service: Optional[AICommandService] = None
coo_conversation_service: Optional[COOConversationService] = None
coo_translation_service: Optional[COOTranslationService] = None


def set_ai_services(
    *,
    command_service: AICommandService,
    conversation_service: COOConversationService,
    translation_service: COOTranslationService,
) -> None:
    """
    Canon injection hook. Must be called during app bootstrap.
    """
    global ai_command_service
    global coo_conversation_service
    global coo_translation_service

    ai_command_service = command_service
    coo_conversation_service = conversation_service
    coo_translation_service = translation_service


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/ai", tags=["AI"])


# ============================================================
# REQUEST MODEL (UX INPUT ONLY)
# ============================================================


class AIRequest(BaseModel):
    text: str = Field(..., min_length=1)
    context: Optional[Dict[str, Any]] = None


# ============================================================
# HEURISTICS (READ-ONLY; SAFE FALLBACK)
# ============================================================


_ACTION_PREFIX_RE = re.compile(
    r"^\s*(dodaj|kreiraj|napravi|create|add)\s+",
    flags=re.IGNORECASE,
)

_TASK_KEYWORD_RE = re.compile(
    r"\b(task|zadatak|todo|to-do)\b",
    flags=re.IGNORECASE,
)

_GOAL_KEYWORD_RE = re.compile(
    r"\b(cilj|goal)\b",
    flags=re.IGNORECASE,
)

_STRUCT_HINT_RE = re.compile(
    r"\b(due|rok|deadline|prioritet|priority|status)\b",
    flags=re.IGNORECASE,
)


def _looks_like_action_command(text: str) -> bool:
    """
    Minimal, deterministic signal:
    - starts with an action verb (dodaj/kreiraj/...)
    - mentions task/zadatak or cilj/goal
    - has at least one struct hint (due/rok/prioritet/status)
    This avoids accidentally translating normal questions.
    """
    t = (text or "").strip()
    if not t:
        return False

    if not _ACTION_PREFIX_RE.search(t):
        return False

    is_taskish = bool(_TASK_KEYWORD_RE.search(t))
    is_goalish = bool(_GOAL_KEYWORD_RE.search(t))
    if not (is_taskish or is_goalish):
        return False

    if not _STRUCT_HINT_RE.search(t):
        return False

    return True


def _serialize_command(cmd: Any) -> Any:
    """
    Make command payload JSON-friendly.
    """
    if cmd is None:
        return None
    if hasattr(cmd, "model_dump"):
        try:
            return cmd.model_dump()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(cmd, "dict"):
        try:
            return cmd.dict()
        except Exception:  # noqa: BLE001
            pass
    return cmd


# ============================================================
# RUN AI — UX ENTRYPOINT (CANON: READ-ONLY)
# ============================================================


@router.post("/run")
async def run_ai(req: AIRequest) -> Dict[str, Any]:
    """
    CANON:
    - This endpoint is a chat/UX entrypoint and MUST NOT execute writes.
    - It may only: read context, produce advice, and propose AICommand(s).
    - Execution (side-effects) must happen through the dedicated execution path (/api/execute),
      followed by governance approval.

    Compatibility:
    - If mounted under /api, the full path is: /api/ai/run
    - If mounted without /api, the full path is: /ai/run
    """
    logger.info("[AI] UX request received")

    # READ-ONLY FALLBACK UMJESTO 500:
    if (
        ai_command_service is None
        or coo_conversation_service is None
        or coo_translation_service is None
    ):
        return {
            "ok": True,
            "read_only": True,
            "type": "unavailable",
            "text": "AI services not initialized; returning no-op proposal.",
            "next_actions": [],
            "proposed_commands": [],
            "meta": {"reason": "ai_services_not_initialized"},
        }

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    context: Dict[str, Any] = req.context or {}

    # 1) COO CONVERSATION (ADVICE / CLARIFY / STOP)
    convo = coo_conversation_service.handle_user_input(
        raw_input=text,
        source="user",
        context=context,
    )

    convo_type = getattr(convo, "type", None)
    logger.info("[AI] convo.type=%s", convo_type)

    # If not ready, normally return advisory response (READ-only)
    if convo_type != "ready_for_translation":
        # SAFE FALLBACK:
        # If conversation gating fails to recognize an action (common for task commands),
        # try translation ONLY when the text strongly looks like a structured command.
        if _looks_like_action_command(text):
            logger.info("[AI] gating_override=True (structured action detected)")
            command = coo_translation_service.translate(
                raw_input=text,
                source="user",
                context=context,
            )
            if command:
                proposed = {
                    "status": "BLOCKED",
                    "command": _serialize_command(command),
                    "required_approval": True,
                }
                return {
                    "ok": True,
                    "read_only": True,
                    "type": "proposal",
                    "text": (
                        "Akcija je prepoznata (fallback) i spremna za approval i dalju obradu."
                    ),
                    "next_actions": [
                        "Review proposal, then execute via /api/execute if approved."
                    ],
                    "proposed_commands": [proposed],
                    "meta": {"gating_override": True, "convo_type": convo_type},
                }

        return {
            "ok": True,
            "read_only": True,
            "type": convo_type or "unknown",
            "text": getattr(convo, "text", "") or "",
            "next_actions": getattr(convo, "next_actions", []) or [],
            "proposed_commands": [],
        }

    # 2) TRANSLATION (PROPOSE AICommand)
    command = coo_translation_service.translate(
        raw_input=text,
        source="user",
        context=context,
    )

    if not command:
        return {
            "ok": True,
            "read_only": True,
            "type": "rejected",
            "text": "Input cannot be translated into a command. Clarify intent and try again.",
            "next_actions": [
                "Clarify the request with concrete scope, constraints, and desired outcome.",
            ],
            "proposed_commands": [],
        }

    # 3) PROPOSAL ONLY (NO EXECUTION HERE)
    proposed = {
        "status": "BLOCKED",
        "command": _serialize_command(command),
        "required_approval": True,
    }

    return {
        "ok": True,
        "read_only": True,
        "type": "proposal",
        "text": (
            getattr(convo, "text", "")
            or "Proposed command is ready for approval/execution flow."
        ),
        "next_actions": (
            getattr(convo, "next_actions", [])
            or ["Review proposal, then execute via /api/execute if approved."]
        ),
        "proposed_commands": [proposed],
    }


# Export alias (style kao ostali routeri)
ai_router = router
