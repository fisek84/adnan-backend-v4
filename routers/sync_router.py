from fastapi import APIRouter, HTTPException
from typing import Optional
from services.notion_sync_service import NotionSyncService

# Injected from main.py
sync_service_global: Optional[NotionSyncService] = None

# NEW — SAFE setter function
def set_sync_service(service: NotionSyncService):
    global sync_service_global
    sync_service_global = service


router = APIRouter(prefix="/sync", tags=["Sync"])


def check_sync():
    if sync_service_global is None:
        raise HTTPException(500, "SyncService not initialized")


# ============================================================
# FRIENDLY ENDPOINTS
# ============================================================

@router.post("/goals")
async def sync_goals():
    check_sync()
    await sync_service_global.sync_goals_up()
    return {"status": "ok", "synced": "goals"}


@router.post("/tasks")
async def sync_tasks():
    check_sync()
    await sync_service_global.sync_tasks_up()
    return {"status": "ok", "synced": "tasks"}


@router.post("/full")
async def sync_full():
    check_sync()
    await sync_service_global.sync_goals_up()
    await sync_service_global.sync_tasks_up()
    return {"status": "ok", "synced": "full"}


# ============================================================
# RAW ENDPOINTS (KEEP)
# ============================================================

@router.post("/goals/up")
async def sync_goals_up():
    check_sync()
    await sync_service_global.sync_goals_up()
    return {"status": "ok", "action": "goals_sync_up"}


@router.post("/goals/down")
async def sync_goals_down():
    check_sync()
    await sync_service_global.sync_goals_down()
    return {"status": "ok", "action": "goals_sync_down"}


@router.post("/tasks/up")
async def sync_tasks_up():
    check_sync()
    await sync_service_global.sync_tasks_up()
    return {"status": "ok", "action": "tasks_sync_up"}


@router.post("/tasks/down")
async def sync_tasks_down():
    check_sync()
    await sync_service_global.sync_tasks_down()
    return {"status": "ok", "action": "tasks_sync_down"}


@router.post("/all/up")
async def sync_all_up():
    check_sync()
    await sync_service_global.sync_goals_up()
    await sync_service_global.sync_tasks_up()
    return {"status": "ok", "action": "all_sync_up"}


@router.post("/all/down")
async def sync_all_down():
    check_sync()
    await sync_service_global.sync_goals_down()
    await sync_service_global.sync_tasks_down()
    return {"status": "ok", "action": "all_sync_down"}