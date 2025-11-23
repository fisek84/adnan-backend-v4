from fastapi import APIRouter, HTTPException, status
from services.notion_sync_service import NotionSyncService

router = APIRouter(prefix="/sync", tags=["Sync"])

# Global sync service instance (injected via main.py)
sync_service_global: NotionSyncService | None = None


# ============================================================
# INTERNAL VALIDATION
# ============================================================
def _require_sync_service() -> NotionSyncService:
    if sync_service_global is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="NotionSyncService is not initialized"
        )
    return sync_service_global


# ============================================================
# SYNC: GOALS
# ============================================================
@router.post(
    "/goals",
    summary="Full sync for Goals (Notion ↔ Backend)",
    status_code=status.HTTP_200_OK
)
async def sync_goals():
    service = _require_sync_service()

    try:
        # Step 1: Notion → Backend
        await service.sync_goals_down()

        # Step 2: Backend → Notion
        await service.sync_goals_up()

        return {
            "status": "success",
            "synced": "goals",
            "direction": "down + up",
            "message": "Goals synchronized successfully"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Goal sync failed: {str(e)}"
        )


# ============================================================
# SYNC: TASKS
# ============================================================
@router.post(
    "/tasks",
    summary="Full sync for Tasks (Notion ↔ Backend)",
    status_code=status.HTTP_200_OK
)
async def sync_tasks():
    service = _require_sync_service()

    try:
        # Step 1: Notion → Backend
        await service.sync_tasks_down()

        # Step 2: Backend → Notion
        await service.sync_tasks_up()

        return {
            "status": "success",
            "synced": "tasks",
            "direction": "down + up",
            "message": "Tasks synchronized successfully"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Task sync failed: {str(e)}"
        )