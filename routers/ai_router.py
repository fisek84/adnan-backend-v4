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

    NOTE (FAZA 4):
    - This router is UX/proposal-only and MUST NOT execute writes.
    - command_service is accepted for compatibility, but is not used for execution here.
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
    Make command payload JSON-friendly (never return raw object).
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

    if isinstance(cmd, dict):
        return cmd

    # last resort: safe string
    return {"_type": type(cmd).__name__, "_repr": str(cmd)}


def _proposal_v2_from_ai_command(ai_cmd_serialized: Any) -> Dict[str, Any]:
    """
    Kanonski proposal shape (kompatibilan sa ProposedCommand),
    ali ovdje vraćen kao dict radi backwards-compat response-a.
    """
    return {
        "command": "ai.execute.propose",
        "args": {"ai_command": ai_cmd_serialized},
        "reason": "UX endpoint produced a translation; proposing for approval/execution pipeline.",
        "dry_run": True,
        "requires_approval": True,
        "risk": "MED",
    }


def _map_confidence_to_score(confidence: Optional[str]) -> float:
    """
    Canon mapping: categorical confidence -> float score (0.0–1.0)

    NOTE:
    - Additive only; existing clients still read `confidence`.
    - This is a deterministic mapping (no ML/LLM inference).
    """
    key = (confidence or "").strip().upper()
    mapping = {
        "LOW": 0.35,
        "MED": 0.60,
        "MEDIUM": 0.60,
        "HIGH": 0.85,
    }
    return float(mapping.get(key, 0.60))


def _normalize_risk_level(risk: Optional[str]) -> str:
    """
    Canon normalization: risk -> risk_level in {low, medium, high}
    """
    key = (risk or "").strip().upper()
    mapping = {
        "LOW": "low",
        "MED": "medium",
        "MEDIUM": "medium",
        "HIGH": "high",
    }
    return mapping.get(key, "medium")


def _ensure_int_ge_0(value: Any) -> int:
    try:
        n = int(value)
    except Exception:  # noqa: BLE001
        return 0
    return n if n >= 0 else 0


def _compute_confidence_risk(
    *,
    text: str,
    convo_type: Optional[str],
    proposed_commands: Any,
    gating_override: bool,
) -> Dict[str, Any]:
    """
    Deterministic, low-assumption contract:
      - always returns dict with backward compatible fields:
          {"confidence": <str>, "risk": <str>, "signals": {...}}
      - plus canon enterprise fields:
          confidence_score: float (0.0–1.0)
          risk_level: "low"|"medium"|"high"
          assumption_count: int (>=0)
      - does NOT execute; only metadata for UX/debug.

    Rules (legacy behavior preserved):
      - confidence: HIGH if we produced proposals, otherwise MEDIUM/LOW depending on gate
      - risk: LOW unless proposals exist (then MED); if proposal indicates approval/write, keep MED
    """
    pcs = proposed_commands if isinstance(proposed_commands, list) else []
    has_proposals = len(pcs) > 0

    # Assumptions used by this deterministic scoring layer (not LLM assumptions).
    assumptions: list[str] = []
    if convo_type is None:
        assumptions.append("convo_type_missing_defaulted")
    if not isinstance(proposed_commands, list):
        assumptions.append("proposed_commands_non_list_defaulted_to_empty")
    if (text or "").strip() == "":
        assumptions.append("empty_text_in_scoring_layer")

    # Confidence (legacy)
    confidence = "MEDIUM"
    if has_proposals:
        confidence = "HIGH"
    else:
        # If gate not ready and no proposals, we're basically advisory
        if convo_type and convo_type != "ready_for_translation":
            confidence = "LOW"
        else:
            confidence = "MEDIUM"

    # Risk (legacy)
    risk = "LOW"
    if has_proposals:
        risk = "MED"

    # If proposals explicitly flag approval/write, keep at least MED
    for p in pcs:
        if not isinstance(p, dict):
            assumptions.append("proposal_non_dict_ignored")
            continue
        if p.get("required_approval") is True or p.get("requires_approval") is True:
            risk = "MED"
            break
        intent = p.get("intent")
        if isinstance(intent, str) and intent.strip().lower() in {
            "notion_write",
            "write",
            "execute",
        }:
            risk = "MED"
            break

    # Canon enterprise fields
    confidence_score = _map_confidence_to_score(confidence)
    risk_level = _normalize_risk_level(risk)
    assumption_count = _ensure_int_ge_0(len(assumptions))

    return {
        # Backwards-compatible fields (do not remove)
        "confidence": confidence,
        "risk": risk,
        # Canon enterprise fields (additive)
        "confidence_score": float(confidence_score),
        "risk_level": risk_level,  # low|medium|high
        "assumption_count": assumption_count,
        "signals": {
            "convo_type": convo_type,
            "gating_override": bool(gating_override),
            "has_proposals": bool(has_proposals),
            "looks_like_action": _looks_like_action_command(text),
            # auditability: what this scoring layer assumed
            "assumptions": assumptions,
        },
    }


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
        meta = {
            "reason": "ai_services_not_initialized",
            "endpoint": "/ai/run",
            "canon": "read_propose_only",
        }
        meta["confidence_risk"] = _compute_confidence_risk(
            text=(req.text or "").strip(),
            convo_type="unavailable",
            proposed_commands=[],
            gating_override=False,
        )
        return {
            "ok": True,
            "read_only": True,
            "type": "unavailable",
            "text": "AI services not initialized; returning no-op proposal.",
            "next_actions": [],
            "proposed_commands": [],
            "proposed_commands_v2": [],
            "meta": meta,
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
                serialized = _serialize_command(command)

                # Legacy proposal (existing clients)
                proposed_legacy = {
                    "status": "BLOCKED",
                    "command": serialized,
                    "required_approval": True,
                }

                # v2 proposal (compatible with ProposedCommand)
                proposed_v2 = _proposal_v2_from_ai_command(serialized)

                meta = {
                    "gating_override": True,
                    "convo_type": convo_type,
                    "endpoint": "/ai/run",
                    "canon": "read_propose_only",
                }
                meta["confidence_risk"] = _compute_confidence_risk(
                    text=text,
                    convo_type=convo_type,
                    proposed_commands=[proposed_legacy],
                    gating_override=True,
                )

                return {
                    "ok": True,
                    "read_only": True,
                    "type": "proposal",
                    "text": "Akcija je prepoznata (fallback) i spremna za approval i dalju obradu.",
                    "next_actions": [
                        "Review proposal, then execute via /api/execute if approved."
                    ],
                    "proposed_commands": [proposed_legacy],
                    "proposed_commands_v2": [proposed_v2],
                    "meta": meta,
                }

        meta = {
            "endpoint": "/ai/run",
            "canon": "read_propose_only",
        }
        meta["confidence_risk"] = _compute_confidence_risk(
            text=text,
            convo_type=convo_type,
            proposed_commands=[],
            gating_override=False,
        )

        return {
            "ok": True,
            "read_only": True,
            "type": convo_type or "unknown",
            "text": getattr(convo, "text", "") or "",
            "next_actions": getattr(convo, "next_actions", []) or [],
            "proposed_commands": [],
            "proposed_commands_v2": [],
            "meta": meta,
        }

    # 2) TRANSLATION (PROPOSE AICommand)
    command = coo_translation_service.translate(
        raw_input=text,
        source="user",
        context=context,
    )

    if not command:
        meta = {
            "endpoint": "/ai/run",
            "canon": "read_propose_only",
        }
        meta["confidence_risk"] = _compute_confidence_risk(
            text=text,
            convo_type=convo_type,
            proposed_commands=[],
            gating_override=False,
        )

        return {
            "ok": True,
            "read_only": True,
            "type": "rejected",
            "text": "Input cannot be translated into a command. Clarify intent and try again.",
            "next_actions": [
                "Clarify the request with concrete scope, constraints, and desired outcome.",
            ],
            "proposed_commands": [],
            "proposed_commands_v2": [],
            "meta": meta,
        }

    serialized = _serialize_command(command)

    # 3) PROPOSAL ONLY (NO EXECUTION HERE)
    proposed_legacy = {
        "status": "BLOCKED",
        "command": serialized,
        "required_approval": True,
    }
    proposed_v2 = _proposal_v2_from_ai_command(serialized)

    meta = {
        "endpoint": "/ai/run",
        "canon": "read_propose_only",
    }
    meta["confidence_risk"] = _compute_confidence_risk(
        text=text,
        convo_type=convo_type,
        proposed_commands=[proposed_legacy],
        gating_override=False,
    )

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
        "proposed_commands": [proposed_legacy],
        "proposed_commands_v2": [proposed_v2],
        "meta": meta,
    }


# Export alias (style kao ostali routeri)
ai_router = router
