from fastapi import APIRouter, HTTPException
from typing import Optional
import logging

from services.notion_sync_service import NotionSyncService

# Global instance injected in main.py
sync_service_global: Optional[NotionSyncService] = None


def set_sync_service(service: NotionSyncService):
    """
    Safe setter used in main.py during startup.
    """
    global sync_service_global
    sync_service_global = service


router = APIRouter(prefix="/sync", tags=["Sync"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def require_sync():
    if sync_service_global is None:
        logger.error("SyncService not initialized")
        raise HTTPException(status_code=500, detail="SyncService not initialized")


# ============================================================
# STATUS ENDPOINT (ADDED)
# ============================================================

@router.get("/status")
async def sync_status():
    """
    Returns basic sync metadata if available.
    Safe fallback: returns minimal structure even if backend does not track sync info.
    """
    if sync_service_global is None:
        return {"status": "not_initialized"}

    status = {}

    # Safe-access "last sync" timestamps if the service maintains them
    if hasattr(sync_service_global, "last_goals_sync"):
        status["goals"] = sync_service_global.last_goals_sync

    if hasattr(sync_service_global, "last_tasks_sync"):
        status["tasks"] = sync_service_global.last_tasks_sync

    if hasattr(sync_service_global, "last_projects_sync"):
        status["projects"] = sync_service_global.last_projects_sync

    if not status:
        # fallback when service doesn't track timestamps
        return {"status": "no_sync_metadata"}

    return {"status": "ok", "metadata": status}


# ============================================================
# FRIENDLY SYNC ENDPOINTS
# ============================================================

@router.post("/goals")
async def sync_goals():
    require_sync()
    logger.info("Manual sync: GOALS")
    await sync_service_global.sync_goals_up()
    return {"status": "ok", "synced": "goals"}


@router.post("/tasks")
async def sync_tasks():
    require_sync()
    logger.info("Manual sync: TASKS")
    await sync_service_global.sync_tasks_up()
    return {"status": "ok", "synced": "tasks"}


@router.post("/projects")
async def sync_projects():
    require_sync()
    logger.info("Manual sync: PROJECTS")
    await sync_service_global.sync_projects_up()
    return {"status": "ok", "synced": "projects"}


@router.post("/full")
async def sync_full():
    require_sync()
    logger.info("Manual FULL SYNC triggered")
    await sync_service_global.sync_goals_up()
    await sync_service_global.sync_tasks_up()
    await sync_service_global.sync_projects_up()
    return {"status": "ok", "synced": "full"}


# ============================================================
# RAW UPLOAD ENDPOINTS (KEEP)
# ============================================================

@router.post("/goals/up")
async def sync_goals_up():
    require_sync()
    logger.info("Sync UP: GOALS")
    await sync_service_global.sync_goals_up()
    return {"status": "ok", "action": "goals_sync_up"}


@router.post("/tasks/up")
async def sync_tasks_up():
    require_sync()
    logger.info("Sync UP: TASKS")
    await sync_service_global.sync_tasks_up()
    return {"status": "ok", "action": "tasks_sync_up"}


@router.post("/projects/up")
async def sync_projects_up():
    require_sync()
    logger.info("Sync UP: PROJECTS")
    await sync_service_global.sync_projects_up()
    return {"status": "ok", "action": "projects_sync_up"}


@router.post("/all/up")
async def sync_all_up():
    require_sync()
    logger.info("Sync UP: ALL (goals + tasks + projects)")
    await sync_service_global.sync_goals_up()
    await sync_service_global.sync_tasks_up()
    await sync_service_global.sync_projects_up()
    return {"status": "ok", "action": "all_sync_up"}
