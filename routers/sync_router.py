from fastapi import APIRouter, HTTPException
from typing import Optional
import logging  # Dodajemo logovanje
from services.notion_sync_service import NotionSyncService

# Injected from main.py
sync_service_global: Optional[NotionSyncService] = None

# NEW — SAFE setter function
def set_sync_service(service: NotionSyncService):
    global sync_service_global
    sync_service_global = service


router = APIRouter(prefix="/sync", tags=["Sync"])

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def check_sync():
    if sync_service_global is None:
        logger.error("SyncService not initialized")
        raise HTTPException(500, "SyncService not initialized")


# ============================================================
# FRIENDLY ENDPOINTS
# ============================================================

@router.post("/goals")
async def sync_goals():
    check_sync()
    logger.info("Syncing goals...")
    await sync_service_global.sync_goals_up()
    logger.info("Goals synced successfully.")
    return {"status": "ok", "synced": "goals"}


@router.post("/tasks")
async def sync_tasks():
    check_sync()
    logger.info("Syncing tasks...")
    await sync_service_global.sync_tasks_up()
    logger.info("Tasks synced successfully.")
    return {"status": "ok", "synced": "tasks"}


@router.post("/full")
async def sync_full():
    check_sync()
    logger.info("Syncing all...")
    await sync_service_global.sync_goals_up()
    await sync_service_global.sync_tasks_up()
    logger.info("Full sync completed (goals and tasks).")
    return {"status": "ok", "synced": "full"}


# ============================================================
# RAW ENDPOINTS (KEEP)
# ============================================================

@router.post("/goals/up")
async def sync_goals_up():
    check_sync()
    logger.info("Syncing goals up...")
    await sync_service_global.sync_goals_up()
    logger.info("Goals synced up.")
    return {"status": "ok", "action": "goals_sync_up"}


@router.post("/goals/down")
async def sync_goals_down():
    check_sync()
    logger.info("Syncing goals down...")
    await sync_service_global.sync_goals_down()
    logger.info("Goals synced down.")
    return {"status": "ok", "action": "goals_sync_down"}


@router.post("/tasks/up")
async def sync_tasks_up():
    check_sync()
    logger.info("Syncing tasks up...")
    await sync_service_global.sync_tasks_up()
    logger.info("Tasks synced up.")
    return {"status": "ok", "action": "tasks_sync_up"}


@router.post("/tasks/down")
async def sync_tasks_down():
    check_sync()
    logger.info("Syncing tasks down...")
    await sync_service_global.sync_tasks_down()
    logger.info("Tasks synced down.")
    return {"status": "ok", "action": "tasks_sync_down"}


@router.post("/all/up")
async def sync_all_up():
    check_sync()
    logger.info("Syncing all (goals and tasks) up...")
    await sync_service_global.sync_goals_up()
    await sync_service_global.sync_tasks_up()
    logger.info("Full sync up completed (goals and tasks).")
    return {"status": "ok", "action": "all_sync_up"}


@router.post("/all/down")
async def sync_all_down():
    check_sync()
    logger.info("Syncing all (goals and tasks) down...")
    await sync_service_global.sync_goals_down()
    await sync_service_global.sync_tasks_down()
    logger.info("Full sync down completed (goals and tasks).")
    return {"status": "ok", "action": "all_sync_down"}
