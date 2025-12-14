# routers/audit_router.py

from fastapi import APIRouter
from services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["Audit"])

audit_service = AuditService()


# ============================================================
# FULL COMPLIANCE EXPORT
# ============================================================
@router.get("/export")
def export_audit():
    return {
        "ok": True,
        "data": audit_service.get_full_audit_snapshot(),
    }


# ============================================================
# EXECUTION AUDIT (RAW)
# ============================================================
@router.get("/execution")
def execution_audit():
    return {
        "ok": True,
        "data": audit_service.get_execution_audit(),
    }


# ============================================================
# EXECUTION KPIs (AGGREGATED)
# ============================================================
@router.get("/kpis")
def execution_kpis():
    return {
        "ok": True,
        "data": audit_service.get_execution_kpis(),
    }
