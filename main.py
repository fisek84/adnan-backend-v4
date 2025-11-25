from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# ROUTERS
from routers.goals_router import router as goals_router
from routers.tasks_router import router as tasks_router

# SERVICES
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService
from services.notion_sync_service import NotionSyncService
from services.ai_command_service import AICommandService
from services.agents_service import AgentsService

# DEPENDENCIES
from dependencies import (
    get_goals_service,
    get_tasks_service,
    get_notion_service,
    set_notion_service
)

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SERVICE INSTANCES
notion_service: NotionService = None
goals_service: GoalsService = None
tasks_service: TasksService = None
notion_sync_service: NotionSyncService = None
ai_command_service: AICommandService = None
agents_service: AgentsService = None


@app.on_event("startup")
async def startup_event():
    global notion_service, goals_service, tasks_service
    global notion_sync_service, ai_command_service, agents_service

    print("🔵 Starting backend services...")

    # ========================
    # NOTION SERVICE INIT
    # ========================
    notion_service = NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID")
    )

    # REGISTER INTO GLOBAL DEPENDENCIES
    set_notion_service(notion_service)

    print("✅ NotionService initialized")

    # ========================
    # LOCAL DB SERVICES
    # ========================
    goals_service = GoalsService()
    tasks_service = TasksService()

    print("✅ GoalsService initialized")
    print("✅ TasksService initialized")

    # ========================
    # SYNC SERVICE
    # ========================
    notion_sync_service = NotionSyncService(
        notion_service,
        goals_service,
        tasks_service,
        os.getenv("NOTION_GOALS_DB_ID"),
        os.getenv("NOTION_TASKS_DB_ID")
    )
    print("✅ NotionSyncService initialized")

    # AI COMMANDS
    ai_command_service = AICommandService()
    print("✅ AICommandService initialized")

    # AGENTS SERVICE
    agents_service = AgentsService(
        notion_token=os.getenv("NOTION_API_KEY"),
        exchange_db_id=os.getenv("NOTION_EXCHANGE_DB_ID"),
        projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID")
    )
    print("✅ AgentsService initialized")

    print("🔥 Backend fully initialized")


# ROUTERS
app.include_router(goals_router)
app.include_router(tasks_router)


@app.get("/health")
def health():
    return {"status": "ok"}
