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
from services.notion_sync_service import NotionSyncService
from services.ai_command_service import AICommandService
from services.agents_service import AgentsService

# DEPENDENCIES
from dependencies import init_services, get_notion_service, get_goals_service, get_tasks_service

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
# CREATE APP (THIS MUST COME BEFORE include_router)
# ----------------------------------------------------------
app = FastAPI()


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

    init_db()
    print("🟦 SQLite Task Queue initialized")

    # Init core services
    init_services()
    notion_service = get_notion_service()
    goals_service = get_goals_service()
    tasks_service = get_tasks_service()

    print("✅ NotionService initialized")
    print("✅ GoalsService initialized")
    print("✅ TasksService initialized")

    # Sync service
    notion_sync_service = NotionSyncService(
        notion_service,
        goals_service,
        tasks_service,
        os.getenv("NOTION_GOALS_DB_ID"),
        os.getenv("NOTION_TASKS_DB_ID")
    )

    import routers.sync_router as sync_router_module
    sync_router_module.sync_service_global = notion_sync_service
    print("🔗 Sync router connected to NotionSyncService")

    # AI command service
    ai_command_service = AICommandService()
    print("✅ AICommandService initialized")

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

# External
app.include_router(ext_tasks_router, prefix="/ext")
app.include_router(ext_notion_router, prefix="/ext")
app.include_router(ext_documents_router, prefix="/ext")
app.include_router(ext_agents_router, prefix="/ext")

# NEW — SMART AI OPS (natural language)
app.include_router(ai_ops_router)

# NEW — STRUCTURED OPS (technical)
app.include_router(notion_ops_router, prefix="/ext")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Backend running"}
