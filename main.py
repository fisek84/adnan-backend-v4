from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService
from services.notion_sync_service import NotionSyncService
from services.ai_command_service import AICommandService
from services.agents_service import AgentsService

from routers.goals_router import router as goals_router
from routers.tasks_router import router as tasks_router

import os

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GLOBAL INSTANCES
notion_service: NotionService = None
goals_service: GoalsService = None
tasks_service: TasksService = None
notion_sync_service = None
ai_command_service = None
agents_service = None


# ============================================================
# DEPENDENCIES
# ============================================================

def get_goals_service():
    return goals_service

def get_tasks_service():
    return tasks_service

def get_notion_service():
    return notion_service


# ============================================================
# STARTUP EVENT
# ============================================================

@app.on_event("startup")
async def startup_event():
    global notion_service, goals_service, tasks_service
    global notion_sync_service, ai_command_service, agents_service

    print("🔵 Starting backend services...")

    # 1. NOTION CORE
    notion_service = NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID")
    )
    print("✅ NotionService initialized")

    # 2. LOCAL DB SERVICES
    goals_service = GoalsService()
    tasks_service = TasksService()
    print("✅ GoalsService initialized")
    print("✅ TasksService initialized")

    # 3. SYNC LAYER
    notion_sync_service = NotionSyncService(
        notion_service,
        goals_service,
        tasks_service,
        os.getenv("NOTION_GOALS_DB_ID"),
        os.getenv("NOTION_TASKS_DB_ID")
    )
    print("✅ NotionSyncService initialized")

    # 4. AI + AGENTS
    ai_command_service = AICommandService()

    agents_service = AgentsService(
        notion_token=os.getenv("NOTION_API_KEY"),
        exchange_db_id=os.getenv("NOTION_EXCHANGE_DB_ID"),
        projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID")
    )
    print("✅ AICommandService initialized")
    print("✅ AgentsService initialized")

    print("🔥 Backend fully initialized")


# ROUTERS
app.include_router(goals_router)
app.include_router(tasks_router)


@app.get("/health")
def health():
    return {"status": "ok"}
