# routers/audit_router.py

from fastapi import APIRouter
from services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["Audit"])

audit_service = AuditService()


@router.get("/export")
def export_audit():
    """
    READ-ONLY Audit Export
    """
    return {
        "ok": True,
        "data": audit_service.get_full_audit_snapshot(),
    }
