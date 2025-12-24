# routers/approval_router.py
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException

from services.approval_state_service import get_approval_state
from services.approval_ux_service import ApprovalUXService
from services.execution_orchestrator import ExecutionOrchestrator


router = APIRouter(prefix="/approvals", tags=["Approvals"])

_ux = ApprovalUXService()
_orchestrator = ExecutionOrchestrator()
_state = get_approval_state()


@router.get("/pending")
def list_pending() -> Dict[str, Any]:
    return {
        "ok": True,
        "pending": _state.list_pending(),
        "read_only": True,
    }


@router.get("/{approval_id}")
def get_approval(approval_id: str) -> Dict[str, Any]:
    try:
        approval = _state.get(approval_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")

    return {
        "ok": True,
        "approval": approval,
        "read_only": True,
    }


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    """
    Approve + resume execution.

    Expected payload (minimal):
    - approved_by: str (required)
    - note: str (optional)
    """
    approved_by = payload.get("approved_by")
    note: Optional[str] = payload.get("note")

    if not isinstance(approved_by, str) or not approved_by.strip():
        raise HTTPException(status_code=400, detail="approved_by is required")

    try:
        ux_result = _ux.approve(
            approval_id=approval_id,
            approved_by=approved_by.strip(),
            note=note if isinstance(note, str) else None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    execution_id = ux_result.get("execution_id")
    if not execution_id:
        raise HTTPException(
            status_code=500, detail="Approved approval has no execution_id"
        )

    # CANON: resume existing registered execution after approval
    execution_result = await _orchestrator.resume(execution_id)

    return {
        "ok": True,
        "approval": ux_result,
        "execution": execution_result,
        "read_only": True,
    }


@router.post("/{approval_id}/reject")
def reject(
    approval_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    """
    Reject approval (no resume).

    Expected payload (minimal):
    - rejected_by: str (required)
    - note: str (optional)
    """
    rejected_by = payload.get("rejected_by")
    note: Optional[str] = payload.get("note")

    if not isinstance(rejected_by, str) or not rejected_by.strip():
        raise HTTPException(status_code=400, detail="rejected_by is required")

    try:
        ux_result = _ux.reject(
            approval_id=approval_id,
            rejected_by=rejected_by.strip(),
            note=note if isinstance(note, str) else None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "approval": ux_result,
        "read_only": True,
    }


# Export alias (style kao ostali routeri)
approval_router = router
