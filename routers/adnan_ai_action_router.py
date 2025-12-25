# routers/adnan_ai_action_router.py
#
# CANONICAL PATCH (FAZA 4) — READ/PROPOSE ONLY
#
# Problem (old):
# - Endpoint je direktno interpretirao tekst i izvršavao akcije/workflow (side effects)
# - To je CANON rupa: “chat/AI text -> write/execute” bez approval pipeline-a
# - File je imao i sintaksnu grešku na kraju (trailing "\")
#
# Fix (FAZA 4):
# - Endpoint ostaje kao UX entrypoint, ali isključivo PROPOSAL:
#   - koristi decision engine + safety validation
#   - vraća proposed_directives / proposed_workflow
#   - NIKAD ne poziva ActionExecutionService ili ActionWorkflowService
# - read_only=True i action_executed=False su hard-coded
#
# Napomena:
# - Ako ikad želiš stvarno izvršavanje, to mora ići kroz /api/execute + approval/resume,
#   ne kroz ovaj router.

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.action_safety_service import ActionSafetyService

router = APIRouter(prefix="/adnan-ai/actions", tags=["AdnanAI Actions"])


# -------------------------------
# MODELS
# -------------------------------
class ActionRequest(BaseModel):
    text: str = Field(..., min_length=1)


class ProposedAction(BaseModel):
    kind: str = Field(..., description="action | workflow")
    directive: Optional[str] = Field(default=None, description="Primary directive (for action).")
    workflow: Optional[Dict[str, Any]] = Field(default=None, description="Workflow payload (for workflow).")
    params: Dict[str, Any] = Field(default_factory=dict, description="Context params computed by decision engine.")
    requires_approval: bool = Field(default=True, description="Always True for side effects.")
    allowed_by_safety: bool = Field(default=False, description="Safety validation result (advisory).")
    safety_reason: Optional[str] = Field(default=None, description="Why blocked/allowed by safety.")


class ActionProposalResponse(BaseModel):
    ok: bool = True
    read_only: bool = True

    action_executed: bool = False
    workflow_executed: bool = False

    proposed: List[ProposedAction] = Field(default_factory=list)

    decision: Dict[str, Any] = Field(default_factory=dict)
    trace: Dict[str, Any] = Field(default_factory=dict)


# -------------------------------
# MAIN ENDPOINT (PROPOSAL ONLY)
# -------------------------------
@router.post("/", response_model=ActionProposalResponse)
async def ai_action_endpoint(request: ActionRequest) -> ActionProposalResponse:
    """
    CANON: READ/PROPOSE ONLY

    Prima AI text → decision engine → safety validation → vraća prijedlog.
    Nema execution-a, nema workflow run-a, nema side-effect-a.
    """
    decision_service = AdnanAIDecisionService()
    safety_service = ActionSafetyService()

    decision = decision_service.process(request.text)
    directives = decision.get("directives", []) or []

    params: Dict[str, Any] = {
        "input": decision.get("input"),
        "state": decision.get("state"),
        "mode": decision.get("mode"),
        "priority_context": decision.get("priority_context"),
    }

    proposed: List[ProposedAction] = []

    # 1) Workflow proposal
    if isinstance(decision, dict) and "workflow" in decision and isinstance(decision.get("workflow"), dict):
        workflow = decision["workflow"]

        safety = safety_service.validate_workflow(workflow)
        allowed = bool(safety.get("allowed"))
        reason = safety.get("reason")

        proposed.append(
            ProposedAction(
                kind="workflow",
                workflow=workflow,
                params=params,
                requires_approval=True,
                allowed_by_safety=allowed,
                safety_reason=str(reason) if reason is not None else None,
            )
        )

        return ActionProposalResponse(
            ok=True,
            read_only=True,
            action_executed=False,
            workflow_executed=False,
            proposed=proposed,
            decision=decision,
            trace={
                "endpoint": "/adnan-ai/actions/",
                "canon": "read_propose_only",
                "decision_engine": "process",
                "proposal_kind": "workflow",
            },
        )

    # 2) Single-action proposal (primary directive)
    if directives:
        directive = directives[0]
        safety = safety_service.validate_action(directive, params)
        allowed = bool(safety.get("allowed"))
        reason = safety.get("reason")

        proposed.append(
            ProposedAction(
                kind="action",
                directive=str(directive),
                params=params,
                requires_approval=True,
                allowed_by_safety=allowed,
                safety_reason=str(reason) if reason is not None else None,
            )
        )

        return ActionProposalResponse(
            ok=True,
            read_only=True,
            action_executed=False,
            workflow_executed=False,
            proposed=proposed,
            decision=decision,
            trace={
                "endpoint": "/adnan-ai/actions/",
                "canon": "read_propose_only",
                "decision_engine": "process",
                "proposal_kind": "action",
            },
        )

    # 3) No directives => no proposal
    return ActionProposalResponse(
        ok=True,
        read_only=True,
        action_executed=False,
        workflow_executed=False,
        proposed=[],
        decision=decision,
        trace={
            "endpoint": "/adnan-ai/actions/",
            "canon": "read_propose_only",
            "reason": "no_action_detected",
        },
    )
