import sys
import os
from pathlib import Path

# ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# ============================================================
# LOAD ENVIRONMENT (SAFE MODE)
# ============================================================
# Loads .env IF it exists – does NOT fail if it doesn't
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_GOALS_DB_ID = os.getenv("NOTION_GOALS_DB_ID")
NOTION_TASKS_DB_ID = os.getenv("NOTION_TASKS_DB_ID")
GPT_API_KEY = os.getenv("GPT_API_KEY")

# NEW ENV VARS FOR AGENTS
NOTION_AGENT_EXCHANGE_DB_ID = os.getenv("NOTION_AGENT_EXCHANGE_DB_ID")
NOTION_AGENT_PROJECTS_DB_ID = os.getenv("NOTION_AGENT_PROJECTS_DB_ID")

# Warn if important env vars are missing (does NOT crash backend)
missing = []
if not NOTION_API_KEY: missing.append("NOTION_API_KEY")
if not NOTION_GOALS_DB_ID: missing.append("NOTION_GOALS_DB_ID")
if not NOTION_TASKS_DB_ID: missing.append("NOTION_TASKS_DB_ID")

if missing:
    print(f"⚠ WARNING: Missing environment variables: {', '.join(missing)}")
    print("Backend will still run, but Notion sync may fail.")


# ============================================================
# IMPORT MODULES (routers + services)
# ============================================================
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.ai_command_service import AICommandService
from services.notion_service import NotionService
from services.notion_sync_service import NotionSyncService

# NEW IMPORTS FOR AGENTS
from services.agents_service import AgentsService
import routers.agents_router as agents_router_module

import routers.goals_router as goals_router_module
import routers.tasks_router as tasks_router_module
import routers.ai_router as ai_router_module
import routers.sync_router as sync_router_module

from core.master_engine import MasterEngine


# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(
    title="Evolia Backend v4",
    version="4.0",
    description="Evolia Core Backend + Notion Sync Engine"
)

# ============================================================
# SERVE .well-known FOR GPT PLUGIN / ACTIONS
# ============================================================
app.mount(
    "/.well-known",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), ".well-known")),
    name="well-known"
)


# ============================================================
# API KEY PROTECTION FOR GPT ACTIONS
# ============================================================
async def verify_api_key(x_api_key: str = Header(None)):
    """
    GPT Actions must send X-API-Key header.
    """
    if GPT_API_KEY is None:
        return True  # system unlocked (dev mode)
    if x_api_key != GPT_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return True


# ============================================================
# INITIALIZE CORE SERVICES
# ============================================================
goals_service = GoalsService()
tasks_service = TasksService()
ai_service = AICommandService()

# bi-directional Goal ↔ Task sync
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
    tasks_db_id=NOTION_TASKS_DB_ID
)


# ============================================================
# INITIALIZE AGENTS SERVICE
# ============================================================
agents_service = AgentsService(
    notion_token=NOTION_API_KEY,
    exchange_db_id=NOTION_AGENT_EXCHANGE_DB_ID,
    projects_db_id=NOTION_AGENT_PROJECTS_DB_ID
)


# ============================================================
# INJECT SERVICES INTO ROUTERS
# ============================================================
goals_router_module.goals_service_global = goals_service
tasks_router_module.tasks_service_global = tasks_service
ai_router_module.ai_service_global = ai_service
sync_router_module.sync_service_global = sync_service
agents_router_module.agents_service_global = agents_service


# ============================================================
# REGISTER ROUTERS (protected with API KEY)
# ============================================================
app.include_router(goals_router_module.router, dependencies=[Depends(verify_api_key)])
app.include_router(tasks_router_module.router, dependencies=[Depends(verify_api_key)])
app.include_router(ai_router_module.router, dependencies=[Depends(verify_api_key)])
app.include_router(sync_router_module.router, dependencies=[Depends(verify_api_key)])
app.include_router(agents_router_module.router, dependencies=[Depends(verify_api_key)])


# ============================================================
# ENGINE
# ============================================================
engine = MasterEngine()


# ============================================================
# SYSTEM ROUTES
# ============================================================
@app.get("/health")
def health():
    """Health check for Render + GPT Actions"""
    return {"status": "ok"}


@app.get("/")
def root():
    return {"status": "Evolia Backend v4 running"}


@app.get("/engine")
def engine_status():
    return engine.status()


@app.get("/engine/state")
def engine_check_state():
    return engine.check_state()


@app.get("/engine/progress")
def engine_check_progress():
    return engine.check_progress()