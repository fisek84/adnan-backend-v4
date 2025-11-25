from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.goals_router import router as goals_router, goals_service_global
from routers.tasks_router import router as tasks_router, tasks_service_global

from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_sync_service import NotionService

import os

app = FastAPI()

# CORS (dozvoljeni frontovi)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GLOBAL SERVICES (inicijalno None)
notion_service = None
goals_service = None
tasks_service = None


# -------------------------------------------------------------
# APP STARTUP → KREIRAMO SERVISE
# -------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    global notion_service, goals_service, tasks_service
    global goals_service_global, tasks_service_global

    print("🔵 Starting backend services...")

    # 1) INIT NOTION SERVICE
    notion_service = NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID")
    )

    print("✅ NotionService initialized")

    # 2) LOCAL SERVICES
    goals_service = GoalsService()
    tasks_service = TasksService()

    print("✅ GoalsService initialized")
    print("✅ TasksService initialized")

    # 3) CONNECT TO ROUTERS
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