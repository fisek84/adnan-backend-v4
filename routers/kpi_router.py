from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.kpi_adapter import KPIAdapter

router = APIRouter(prefix="/kpi", tags=["KPI"])


@router.get("/snapshot")
def kpi_snapshot() -> dict:
    """
    KPI snapshot (stub).

    Contract:
    - Returns 200 with stub data when adapter is available.
    - Returns 503 (not 500) if adapter fails.
    """
    try:
        data = KPIAdapter().fetch_data()
        if not isinstance(data, dict):
            raise RuntimeError("KPIAdapter.fetch_data() returned non-dict")
        return {"ok": True, "data": data}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"KPI snapshot not available: {exc}",
        ) from exc
