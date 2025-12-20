# routers/ceo_console_router.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Optional
import logging

from services.ceo_console_snapshot_service import (
    CeoConsoleSnapshotService,
    CeoDashboardSnapshot,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(
    prefix="/ceo/console",
    tags=["CEO Console"],
)

# Injektuje se iz main.py / gateway_server.py
_ceo_snapshot_service: Optional[CeoConsoleSnapshotService] = None


def set_ceo_console_services(*, snapshot_service: CeoConsoleSnapshotService) -> None:
    """
    CANON: DI iz bootstrap sloja.
    Ovaj modul NE kreira svoje servise, samo ih prima.
    """
    global _ceo_snapshot_service
    _ceo_snapshot_service = snapshot_service
    logger.info("[CEO CONSOLE] Snapshot service injected")


@router.get("/snapshot")
def get_ceo_console_snapshot() -> dict:
    """
    CEO Dashboard READ-only snapshot.

    Ruta je dizajnirana da ide pod /api/ceo/console/snapshot
    (pretpostavka: app.include_router(ceo_console_router, prefix="/api")).

    NEMA side efekata:
    - ne mijenja goals/tasks/approvals
    - ne pokreće workflowe
    - ne šalje komande agentima
    """
    if _ceo_snapshot_service is None:
        raise HTTPException(
            status_code=500,
            detail="CEO console snapshot service not initialized",
        )

    logger.info("[CEO CONSOLE] Snapshot requested via API")
    snapshot: CeoDashboardSnapshot = _ceo_snapshot_service.build_snapshot()
    return {
        "snapshot": snapshot,
        "read_only": True,
    }


# Export za main.py / gateway_server.py
ceo_console_router = router
