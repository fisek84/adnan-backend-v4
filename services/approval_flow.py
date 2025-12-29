# services/approval_flow.py

"""
approval_flow.py
----------------
Centralni sloj za kontrolu odobravanja (approval) svih AI komandi i radnji.

Canon:
- Nijedna WRITE / side-effect akcija se ne izvršava bez eksplicitnog odobrenja.
- Ovdje ne kreiramo approval; samo provjeravamo status.
- SSOT: ovaj modul je jedino mjesto za approval provjeru.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NOT_REQUIRED = "not_required"


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _extract_approval_id(ctx: Dict[str, Any]) -> Optional[str]:
    """
    Podrži više mjesta gdje može doći approval_id:
    - ctx["approval_id"]
    - ctx["metadata"]["approval_id"]
    """
    approval_id = ctx.get("approval_id")
    if isinstance(approval_id, str) and approval_id.strip():
        return approval_id.strip()

    md = _as_dict(ctx.get("metadata"))
    approval_id = md.get("approval_id")
    if isinstance(approval_id, str) and approval_id.strip():
        return approval_id.strip()

    return None


def check_approval(
    command_id: str, command_type: str, context: Optional[dict] = None
) -> ApprovalStatus:
    """
    Pravila:
    1) Ako je eksplicitno read_only => NOT_REQUIRED.
    2) Ako postoji approval_id => verifikuj preko approval_state_service.
    3) Inače => PENDING.
    """
    _ = command_id  # command_id je dio API-ja; trenutno se ne koristi u logici.
    ctx = _as_dict(context)

    # 1) eksplicitni read_only bypass (deterministički)
    if ctx.get("read_only") is True:
        return ApprovalStatus.NOT_REQUIRED

    # 2) approval_id verifikacija
    approval_id = _extract_approval_id(ctx)
    if approval_id:
        # Lazy import da izbjegnemo cikluse
        from services.approval_state_service import get_approval_state

        approvals = get_approval_state()
        if approvals.is_fully_approved(approval_id) is True:
            return ApprovalStatus.APPROVED
        return ApprovalStatus.PENDING

    # 3) default: blokiraj dok se ne dobije approval_id (upstream)
    return ApprovalStatus.PENDING


def require_approval_or_block(
    command_id: str, command_type: str, context: Optional[dict] = None
) -> None:
    """
    Hard gate: baca PermissionError ako komanda nije odobrena.
    Poziva se prije bilo kakvog pisanja ili agent_execute koji može imati side-effect.
    """
    status = check_approval(command_id, command_type, context)

    if status in (ApprovalStatus.APPROVED, ApprovalStatus.NOT_REQUIRED):
        return

    raise PermissionError(
        f"Command '{command_id}' of type '{command_type}' not approved: status = {status.value}"
    )
