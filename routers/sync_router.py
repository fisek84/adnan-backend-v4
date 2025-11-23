from fastapi import APIRouter, HTTPException
from services.notion_sync_service import NotionSyncService

# Globalni sync service – biće postavljen iz main.py
sync_service_global: NotionSyncService | None = None

router = APIRouter(prefix="/sync", tags=["Sync"])


# ---------------------------------------------------------
# GOALS SYNC
# ---------------------------------------------------------
@router.post("/goals")
async def sync_goals():
    """
    Full goals sync:
    1. Notion → Backend (DOWN)
    2. Backend → Notion (UP)
    """
    if sync_service_global is None:
        raise HTTPException(500, "sync_service_global is not initialized")

    try:
        await sync_service_global.sync_goals_down()
        await sync_service_global.sync_goals_up()
    except Exception as e:
        raise HTTPException(500, f"Failed to sync goals: {str(e)}")

    return {"status": "success", "message": "Goals synced successfully"}


# ---------------------------------------------------------
# TASKS SYNC
# ---------------------------------------------------------
@router.post("/tasks")
async def sync_tasks():
    """
    Full tasks sync:
    1. Notion → Backend (DOWN)
    2. Backend → Notion (UP)
    """
    if sync_service_global is None:
        raise HTTPException(500, "sync_service_global is not initialized")

    try:
        await sync_service_global.sync_tasks_down()
        await sync_service_global.sync_tasks_up()
    except Exception as e:
        raise HTTPException(500, f"Failed to sync tasks: {str(e)}")

    return {"status": "success", "message": "Tasks synced successfully"}