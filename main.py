from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# ROUTERS
from routers.goals_router import router as goals_router
from routers.tasks_router import router as tasks_router
from routers.sync_router import router as sync_router

# NEW — AI OPS ROUTER (SMART MODE)
from routers.ai_ops_router import ai_ops_router

# SERVICES
from services.notion_service import NotionService
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.projects_service import ProjectsService      # ⬅️ DODANO
from services.notion_sync_service import NotionSyncService
from services.ai_command_service import AICommandService
from services.agents_service import AgentsService

# DEPENDENCIES
from dependencies import (
    init_services,
    get_notion_service,
    get_goals_service,
    get_tasks_service,
)

# EXT ROUTERS
from ext.tasks.router import router as ext_tasks_router
from ext.notion.router import router as ext_notion_router
from ext.documents.router import router as ext_documents_router
from ext.agents.router import router as ext_agents_router

# EXT DB
from ext.tasks.db import init_db

# NEW — NOTION OPS (STRUCTURED)
from services.notion_ops.ops_router import notion_ops_router

# ----------------------------------------------------------
# CREATE APP
# ----------------------------------------------------------
app = FastAPI()

from fastapi.staticfiles import StaticFiles

# SERVE .well-known FOR CHATGPT PLUGIN
app.mount("/.well-known", StaticFiles(directory=".well-known"), name="well-known")


# ----------------------------------------------------------
# MIDDLEWARE
# ----------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------
# STARTUP
# ----------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    print("🔵 Starting backend services...")

    # init sqlite queue
    init_db()
    print("🟦 SQLite Task Queue initialized")

    # init dependency-based services
    init_services()

    notion_service = get_notion_service()
    goals_service = get_goals_service()
    tasks_service = get_tasks_service()

    print("✅ NotionService initialized")
    print("✅ GoalsService initialized")
    print("✅ TasksService initialized")

    # -------------------------------------------------------
    # PROJECTS SERVICE — DODANO
    # -------------------------------------------------------
    projects_service = ProjectsService()
    print("✅ ProjectsService initialized")

    # Bind ProjectsService → goals_service + tasks_service
    projects_service.bind_goals_service(goals_service)
    projects_service.bind_tasks_service(tasks_service)

    # -------------------------------------------------------
    # NOTION SYNC SERVICE — EXTENDED
    # -------------------------------------------------------
    notion_sync_service = NotionSyncService(
        notion_service,
        goals_service,
        tasks_service,
        projects_service,                                         # ⬅️ NEW
        os.getenv("NOTION_GOALS_DB_ID"),
        os.getenv("NOTION_TASKS_DB_ID"),
        os.getenv("NOTION_PROJECTS_DB_ID"),                       # ⬅️ NEW
    )

    import routers.sync_router as sync_router_module
    sync_router_module.set_sync_service(notion_sync_service)
    print("🔗 Sync router connected to NotionSyncService")

    # -------------------------------------------------------
    # LOAD PROJECTS FROM NOTION → BACKEND
    # -------------------------------------------------------
    await notion_sync_service.load_projects_into_backend()
    print("📁 Projects loaded from Notion → backend sync OK")

    # -------------------------------------------------------
    # AI COMMAND SYSTEM
    # -------------------------------------------------------
    ai_command_service = AICommandService()
    print("✅ AICommandService initialized")

    # -------------------------------------------------------
    # AGENTS SYSTEM
    # -------------------------------------------------------
    agents_service = AgentsService(
        notion_token=os.getenv("NOTION_API_KEY"),
        exchange_db_id=os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
        projects_db_id=os.getenv("NOTION_AGENT_PROJECTS_DB_ID"),
    )
    print("✅ AgentsService initialized")

    print("🔥 Backend fully initialized")


# ----------------------------------------------------------
# ROUTERS (CORRECT ORDER)
# ----------------------------------------------------------
app.include_router(goals_router)
app.include_router(tasks_router)
app.include_router(sync_router)

# External routers
app.include_router(ext_tasks_router, prefix="/ext")
app.include_router(ext_notion_router, prefix="/ext")
app.include_router(ext_documents_router, prefix="/ext")
app.include_router(ext_agents_router, prefix="/ext")

# New AI features
app.include_router(ai_ops_router)
app.include_router(notion_ops_router, prefix="/ext")

# NEW — ADNAN.AI KLON ENDPOINT
from routers.adnan_ai_router import router as adnan_ai_router
app.include_router(adnan_ai_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Backend running"}
