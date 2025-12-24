# routers/audit_router.py

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["Audit"])

audit_service = AuditService()


# ============================================================
# FULL COMPLIANCE EXPORT
# ============================================================
@router.get("/export")
def export_audit() -> Dict[str, Any]:
    return {
        "ok": True,
        "data": audit_service.get_full_audit_snapshot(),
        "read_only": True,
    }


# ============================================================
# EXECUTION AUDIT (RAW)
# ============================================================
@router.get("/execution")
def execution_audit() -> Dict[str, Any]:
    return {
        "ok": True,
        "data": audit_service.get_execution_audit(),
        "read_only": True,
    }


# ============================================================
# EXECUTION KPIs (AGGREGATED)
# ============================================================
@router.get("/kpis")
def execution_kpis() -> Dict[str, Any]:
    return {
        "ok": True,
        "data": audit_service.get_execution_kpis(),
        "read_only": True,
    }
