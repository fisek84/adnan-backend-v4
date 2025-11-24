from fastapi import APIRouter, HTTPException

# Injected iz main.py
sync_service_global = None

router = APIRouter(prefix="/sync", tags=["Sync"])


# ============================================================
# MANUAL SYNC — GOALS & TASKS (ASYNC)
# ============================================================
@router.post("/goals/up")
async def sync_goals_up():
    if sync_service_global is None:
        raise HTTPException(500, "SyncService not initialized")

    await sync_service_global.sync_goals_up()
    return {"status": "ok", "action": "goals_sync_up"}


@router.post("/goals/down")
async def sync_goals_down():
    if sync_service_global is None:
        raise HTTPException(500, "SyncService not initialized")

    await sync_service_global.sync_goals_down()
    return {"status": "ok", "action": "goals_sync_down"}


@router.post("/tasks/up")
async def sync_tasks_up():
    if sync_service_global is None:
        raise HTTPException(500, "SyncService not initialized")

    await sync_service_global.sync_tasks_up()
    return {"status": "ok", "action": "tasks_sync_up"}


@router.post("/tasks/down")
async def sync_tasks_down():
    if sync_service_global is None:
        raise HTTPException(500, "SyncService not initialized")

    await sync_service_global.sync_tasks_down()
    return {"status": "ok", "action": "tasks_sync_down"}


# ============================================================
# COMBINED SYNC
# ============================================================
@router.post("/all/up")
async def sync_all_up():
    if sync_service_global is None:
        raise HTTPException(500, "SyncService not initialized")

    await sync_service_global.sync_goals_up()
    await sync_service_global.sync_tasks_up()
    return {"status": "ok", "action": "all_sync_up"}


@router.post("/all/down")
async def sync_all_down():
    if sync_service_global is None:
        raise HTTPException(500, "SyncService not initialized")

    await sync_service_global.sync_goals_down()
    await sync_service_global.sync_tasks_down()
    return {"status": "ok", "action": "all_sync_down"}