from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# ROUTERS
from routers.goals_router import router as goals_router
from routers.tasks_router import router as tasks_router
from routers.projects_router import router as projects_router       # ✅ ADDED
from routers.sync_router import router as sync_router

# AI OPS ROUTER
from routers.ai_ops_router import ai_ops_router

# SERVICES
from services.notion_service import NotionService
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.projects_service import ProjectsService
from services.notion_sync_service import NotionSyncService
from services.ai_command_service import AICommandService
from services.agents_service import AgentsService

# DEPENDENCIES
from dependencies import (
    init_services,
    get_notion_service,
    get_goals_service,
    get_tasks_service,
    get_projects_service,                  # ✅ ADDED
)

# EXT ROUTERS
from ext.tasks.router import router as ext_tasks_router
from ext.notion.router import router as ext_notion_router
from ext.documents.router import router as ext_documents_router
from ext.agents.router import router as ext_agents_router

# EXT DB
from ext.tasks.db import init_db

# NOTION OPS (STRUCTURED)
from services.notion_ops.ops_router import notion_ops_router

from fastapi.staticfiles import StaticFiles


# ====================================================================================
# FASTAPI APP
# ====================================================================================
app = FastAPI()

# Serve .well-known for ChatGPT plugin
app.mount("/.well-known", StaticFiles(directory=".well-known"), name="well-known")


# ====================================================================================
# MIDDLEWARE
# ====================================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ====================================================================================
# STARTUP SEQUENCE
# ====================================================================================
@app.on_event("startup")
async def startup_event():
    print("🔵 Starting backend services...")

    # 1) INIT SQLITE QUEUE
    init_db()
    print("🟦 SQLite Task Queue initialized")

    # 2) INIT ALL CORE SERVICES (INCLUDING ProjectsService)
    init_services()

    # 3) RETRIEVE SERVICES THROUGH DEPENDENCY SYSTEM
    notion_service = get_notion_service()
    goals_service = get_goals_service()
    tasks_service = get_tasks_service()
    projects_service = get_projects_service()     # ✅ FIXED

    print("✅ NotionService initialized")
    print("✅ GoalsService initialized")
    print("✅ TasksService initialized")
    print("✅ ProjectsService initialized")

    # Bind relations
    projects_service.bind_goals_service(goals_service)
    projects_service.bind_tasks_service(tasks_service)

    # 4) INIT NOTION SYNC SERVICE
    notion_sync_service = NotionSyncService(
        notion_service,
        goals_service,
        tasks_service,
        projects_service,                    # ✅ FIXED
        os.getenv("NOTION_GOALS_DB_ID"),
        os.getenv("NOTION_TASKS_DB_ID"),
        os.getenv("NOTION_PROJECTS_DB_ID"),
    )

    import routers.sync_router as sync_router_module
    sync_router_module.set_sync_service(notion_sync_service)
    print("🔗 Sync router connected to NotionSyncService")

    # 5) LOAD PROJECTS FROM NOTION INTO BACKEND
    await notion_sync_service.load_projects_into_backend()
    print("📁 Projects loaded from Notion → backend OK")

    # 6) AI COMMAND SYSTEM
    ai_command_service = AICommandService()
    print("✅ AICommandService initialized")

    # 7) AGENTS SYSTEM
    agents_service = AgentsService(
        notion_token=os.getenv("NOTION_API_KEY"),
        exchange_db_id=os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
        projects_db_id=os.getenv("NOTION_AGENT_PROJECTS_DB_ID"),
    )
    print("✅ AgentsService initialized")

    print("🔥 Backend fully initialized")


# ====================================================================================
# ROUTERS
# ====================================================================================
app.include_router(goals_router)
app.include_router(tasks_router)
app.include_router(projects_router)     # ✅ IMPORTANT — NOW PROJECT API WORKS
app.include_router(sync_router)

# EXT ROUTERS
app.include_router(ext_tasks_router, prefix="/ext")
app.include_router(ext_notion_router, prefix="/ext")
app.include_router(ext_documents_router, prefix="/ext")
app.include_router(ext_agents_router, prefix="/ext")

# AI Modules
app.include_router(ai_ops_router)
app.include_router(notion_ops_router, prefix="/ext")

# Adnan.AI clone endpoint
from routers.adnan_ai_router import router as adnan_ai_router
app.include_router(adnan_ai_router)


# ====================================================================================
# HEALTH CHECK
# ====================================================================================
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Backend running"}
