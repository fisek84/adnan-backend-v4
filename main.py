from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.goals_router import router as goals_router, goals_service_global
from routers.tasks_router import router as tasks_router, tasks_service_global

from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService
from services.notion_sync_service import NotionSyncService
from services.ai_command_service import AICommandService
from services.agents_service import AgentsService

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

# GLOBALS
notion_service = None
goals_service = None
tasks_service = None
notion_sync_service = None
ai_command_service = None
agents_service = None


@app.on_event("startup")
async def startup_event():
    global notion_service, goals_service, tasks_service, notion_sync_service
    global ai_command_service, agents_service
    global goals_service_global, tasks_service_global

    print("🔵 Starting backend services...")

    notion_service = NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID")
    )
    print("✅ NotionService initialized")

    goals_service = GoalsService()
    tasks_service = TasksService()
    print("✅ GoalsService initialized")
    print("✅ TasksService initialized")

    notion_sync_service = NotionSyncService(
        notion_service,
        goals_service,
        tasks_service,
        os.getenv("NOTION_GOALS_DB_ID"),
        os.getenv("NOTION_TASKS_DB_ID")
    )
    print("✅ NotionSyncService initialized")

    ai_command_service = AICommandService()
    agents_service = AgentsService()
    print("✅ AICommandService initialized")
    print("✅ AgentsService initialized")

    goals_service_global = goals_service
    tasks_service_global = tasks_service

    print("🔥 Backend fully initialized")


app.include_router(goals_router)
app.include_router(tasks_router)


@app.get("/health")
def health():
    return {"status": "ok"}
