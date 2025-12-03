from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

load_dotenv()


# ROUTERS
from routers.goals_router import router as goals_router
from routers.tasks_router import router as tasks_router
from routers.projects_router import router as projects_router
from routers.sync_router import router as sync_router
from routers.ai_ops_router import ai_ops_router

# EXT ROUTERS
from ext.tasks.router import router as ext_tasks_router
from ext.notion.router import router as ext_notion_router
from ext.documents.router import router as ext_documents_router
from ext.agents.router import router as ext_agents_router

# NOTION OPS
from services.notion_ops.ops_router import notion_ops_router

# EXT DB
from ext.tasks.db import init_db

# SERVICES
from services.ai_command_service import AICommandService
from services.agents_service import AgentsService

# DEPENDENCIES
from dependencies import (
    init_services,
    get_notion_service,
    get_goals_service,
    get_tasks_service,
    get_projects_service,
    get_sync_service  # <- ovo dodano
)

from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Serve .well-known
app.mount("/.well-known", StaticFiles(directory=".well-known"), name="well-known")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====================================================================================
# STARTUP
# ====================================================================================
@app.on_event("startup")
async def startup_event():
    print("🔵 Starting backend services...")

    # 1) Init SQLite queue
    init_db()
    print("🟦 SQLite Task Queue initialized")

    # 2) Init all services (includes NotionSyncService)
    init_services()

    # 3) Retrieve instances
    notion_service = get_notion_service()
    goals_service = get_goals_service()
    tasks_service = get_tasks_service()
    projects_service = get_projects_service()
    sync_service = get_sync_service()  # ✅ ISPRAVNO: uzmi već postojeći

    print("✅ NotionService initialized")
    print("✅ GoalsService initialized")
    print("✅ TasksService initialized")
    print("✅ ProjectsService initialized")
    print("🔗 ProjectsService linked to NotionSyncService")

    # 4) Connect sync router
    import routers.sync_router as sync_router_module
    sync_router_module.set_sync_service(sync_service)
    print("🔗 Sync router connected to NotionSyncService")

    # 5) Load Notion → backend
    await sync_service.load_projects_into_backend()
    print("📁 Projects loaded from Notion → backend OK")

    # 6) AI Command System
    ai_command_service = AICommandService()
    print("✅ AICommandService initialized")

    # 7) Agents System
    agents_service = AgentsService(
        notion_token=os.getenv("NOTION_API_KEY"),
        exchange_db_id=os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
        projects_db_id=os.getenv("NOTION_AGENT_PROJECTS_DB_ID"),
    )
    print("✅ AgentsService initialized")

    print("🔥 Backend fully initialized")

# ROUTERS
app.include_router(goals_router)
app.include_router(tasks_router)
app.include_router(projects_router)
app.include_router(sync_router)

app.include_router(ext_tasks_router, prefix="/ext")
app.include_router(ext_notion_router, prefix="/ext")
app.include_router(ext_documents_router, prefix="/ext")
app.include_router(ext_agents_router, prefix="/ext")

app.include_router(ai_ops_router)
app.include_router(notion_ops_router, prefix="/ext")

from routers.adnan_ai_router import router as adnan_ai_router
app.include_router(adnan_ai_router)

# HEALTH
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "Backend running"}
