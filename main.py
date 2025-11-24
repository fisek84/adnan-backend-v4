import sys
import os
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import asyncio

# ============================================================
# PROJECT ROOT / CLEAN IMPORTS
# ============================================================
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ============================================================
# LOAD ENV
# ============================================================
load_dotenv()

def env(name: str, default=None):
    return os.getenv(name, default)

NOTION_API_KEY = env("NOTION_API_KEY")
NOTION_GOALS_DB_ID = env("NOTION_GOALS_DB_ID")
NOTION_TASKS_DB_ID = env("NOTION_TASKS_DB_ID")
GPT_API_KEY = env("GPT_API_KEY")

NOTION_AGENT_EXCHANGE_DB_ID = env("NOTION_AGENT_EXCHANGE_DB_ID")
NOTION_AGENT_PROJECTS_DB_ID = env("NOTION_AGENT_PROJECTS_DB_ID")

required_env = {
    "NOTION_API_KEY": NOTION_API_KEY,
    "NOTION_GOALS_DB_ID": NOTION_GOALS_DB_ID,
    "NOTION_TASKS_DB_ID": NOTION_TASKS_DB_ID,
}

missing = [k for k, v in required_env.items() if not v]
if missing:
    print("⚠ Missing ENV:", ", ".join(missing))

# ============================================================
# API KEY PROTECTION
# ============================================================
async def verify_api_key(
    x_api_key: str = Header(None, alias="X-API-Key"),
    x_api_key_lower: str = Header(None, alias="x-api-key")
):
    key = x_api_key or x_api_key_lower

    if GPT_API_KEY:
        if key is None:
            return True
        if key != GPT_API_KEY:
            raise HTTPException(status_code=403, detail="Invalid API Key")

    return True

# ============================================================
# IMPORT SERVICES
# ============================================================
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.ai_command_service import AICommandService
from services.notion_service import NotionService
from services.notion_sync_service import NotionSyncService
from services.agents_service import AgentsService

import routers.goals_router as goals_router_module
import routers.tasks_router as tasks_router_module      # ✅ FIXED
import routers.ai_router as ai_router_module
import routers.sync_router as sync_router_module
import routers.agents_router as agents_router_module

from core.master_engine import MasterEngine

# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(
    title="Evolia Backend v4",
    version="4.2",
    description="Evolia Backend + Notion Sync Engine (ASYNC STABLE)"
)

app.mount(
    "/.well-known",
    StaticFiles(directory=ROOT / ".well-known"),
    name="well-known",
)

# ============================================================
# INITIALIZE DOMAIN SERVICES
# ============================================================
goals_service = GoalsService()
tasks_service = TasksService()
ai_service = AICommandService()

goals_service.bind_tasks_service(tasks_service)
tasks_service.bind_goals_service(goals_service)

# ============================================================
# INITIALIZE NOTION SERVICES
# ============================================================
notion_service = NotionService(token=NOTION_API_KEY)

sync_service = NotionSyncService(
    notion_service=notion_service,
    goals_service=goals_service,
    tasks_service=tasks_service,
    goals_db_id=NOTION_GOALS_DB_ID,
    tasks_db_id=NOTION_TASKS_DB_ID,
)

agents_service = AgentsService(
    notion_token=NOTION_API_KEY,
    exchange_db_id=NOTION_AGENT_EXCHANGE_DB_ID,
    projects_db_id=NOTION_AGENT_PROJECTS_DB_ID,
)

# Bind sync services
goals_service.bind_sync_service(sync_service)
tasks_service.bind_sync_service(sync_service)

# ============================================================
# ROUTERS (Dependency Injection)
# ============================================================
goals_router_module.goals_service_global = goals_service
tasks_router_module.tasks_service_global = tasks_service
ai_router_module.ai_service_global = ai_service
sync_router_module.sync_service_global = sync_service
agents_router_module.agents_service_global = agents_service

protected = [Depends(verify_api_key)]

app.include_router(goals_router_module.router, dependencies=protected)
app.include_router(tasks_router_module.router, dependencies=protected)
app.include_router(ai_router_module.router, dependencies=protected)
app.include_router(sync_router_module.router, dependencies=protected)
app.include_router(agents_router_module.router, dependencies=protected)

# ============================================================
# ENGINE
# ============================================================
engine = MasterEngine()

# ============================================================
# BASIC ROUTES
# ============================================================
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"status": "Evolia Backend v4 async running"}

@app.get("/engine")
def engine_status():
    return engine.status()

@app.get("/engine/state")
def engine_state():
    return engine.check_state()

@app.get("/engine/progress")
def engine_progress():
    return engine.check_progress()

# ============================================================
# SHUTDOWN EVENT
# ============================================================
@app.on_event("shutdown")
async def shutdown_event():
    await notion_service.close()