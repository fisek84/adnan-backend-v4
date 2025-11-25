from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.goals_router import router as goals_router, goals_service_global
from routers.tasks_router import router as tasks_router, tasks_service_global

from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.ai_command_service import AICommandService
from services.notion_service import NotionService
from services.notion_sync_service import NotionSyncService
from services.agents_service import AgentsService

import os

app = FastAPI()

# CORS – dopuštamo sve origin-e (privremeno)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GLOBAL SERVICE INSTANCES
notion_service = None
notion_sync_service = None
goals_service = None
tasks_service = None
ai_command_service = None
agents_service = None


# -------------------------------------------------------------
# STARTUP — inicijalizacija svih servisa
# -------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    global (
        notion_service,
        notion_sync_service,
        goals_service,
        tasks_service,
        ai_command_service,
        agents_service,
        goals_service_global,
        tasks_service_global
    )

    print("🔵 Starting backend services...")

    # 1) INIT NOTION SERVICE
    notion_service = NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
    )
    print("✅ NotionService initialized")

    # 2) LOCAL GOALS / TASKS SERVICES
    goals_service = GoalsService()
    tasks_service = TasksService()
    print("✅ GoalsService initialized")
    print("✅ TasksService initialized")

    # 3) NOTION SYNC SERVICE
    notion_sync_service = NotionSyncService(
        notion_service=notion_service,
        goals_service=goals_service,
        tasks_service=tasks_service,
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID")
    )
    print("✅ NotionSyncService initialized")

    # 4) AI COMMAND SERVICE
    ai_command_service = AICommandService(goals_service, tasks_service)
    print("✅ AICommandService initialized")

    # 5) Agents service (if required)
    agents_service = AgentsService()
    print("✅ AgentsService initialized")

    # 6) CONNECT TO ROUTERS — global injection
    goals_service_global = goals_service
    tasks_service_global = tasks_service

    print("🔥 Backend fully initialized")


# -------------------------------------------------------------
# ROUTERS
# -------------------------------------------------------------
app.include_router(goals_router)
app.include_router(tasks_router)


# -------------------------------------------------------------
# HEALTH CHECK
# -------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}