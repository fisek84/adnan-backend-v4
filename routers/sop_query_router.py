from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from services.sop_knowledge_registry import SOPKnowledgeRegistry
from services.conversation_state_service import ConversationStateService

router = APIRouter(
    prefix="/sop",
    tags=["SOP"],
)

_registry = SOPKnowledgeRegistry()
_csi = ConversationStateService()

# ============================================================
# LIST SOPs (READ-ONLY)
# ============================================================
@router.get("/list")
async def list_sops():
    """
    Vraća listu svih SOP-ova (metadata).
    READ-ONLY.
    """
    sops = _registry.list_sops()

    # CSI → SOP_LIST
    _csi.set_sop_list(sops)

    return {
        "success": True,
        "sops": sops,
    }

# ============================================================
# GET SOP (READ-ONLY)
# ============================================================
@router.get("/get")
async def get_sop(
    sop_id: str = Query(..., description="SOP ID"),
    mode: Optional[str] = Query("summary", description="summary | full"),
):
    """
    Dohvata SOP po ID-u.
    READ-ONLY.
    """
    sop = _registry.get_sop(sop_id=sop_id, mode=mode)
    if sop is None:
        raise HTTPException(status_code=404, detail="SOP not found")

    # CSI → SOP_ACTIVE
    _csi.set_sop_active(sop_id)

    return {
        "success": True,
        "sop": sop,
    }
