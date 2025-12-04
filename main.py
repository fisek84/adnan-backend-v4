import os
from fastapi import FastAPI
import logging
from pydantic import BaseModel

# Inicijalizacija loggera
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Kreiramo FastAPI aplikaciju
app = FastAPI()

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
    get_sync_service
)

# Uključivanje svih ruta
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
    logger.info("Health check received.")
    return {"status": "ok", "message": "Backend is healthy"}

@app.get("/")
def root():
    logger.info("Root endpoint hit.")
    return {"message": "Backend running"}

# DELETE TASK
@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    notion_service = get_notion_service()
    logger.info(f"Request received to delete task {task_id}")

    response = await notion_service.delete_task(task_id)

    if response["ok"]:
        return {"message": f"Task {task_id} successfully deleted"}
    else:
        return {"error": response["error"]}

# POST: ADD GOAL
class Goal(BaseModel):
    goal_name: str
    deadline: str

@app.post("/goals")
async def create_goal(goal: Goal):
    # Ovdje dodaj logiku za kreiranje cilja (npr. čuvanje u bazi)
    logger.info(f"Goal created: {goal.goal_name} with deadline {goal.deadline}")
    return {"goal_name": goal.goal_name, "deadline": goal.deadline}

# STARTUP
@app.on_event("startup")
async def startup_event():
    try:
        logger.info("🔵 Starting backend services...")

        # Init SQLite queue
        init_db()
        logger.info("🟦 SQLite Task Queue initialized")

        # Init core services
        init_services()
        logger.info("🟩 All services initialized.")

        # Retrieve instances
        notion_service = get_notion_service()
        goals_service = get_goals_service()
        tasks_service = get_tasks_service()
        projects_service = get_projects_service()
        sync_service = get_sync_service()

        # Log all services
        logger.info(f"✅ NotionService initialized: {notion_service}")
        logger.info(f"✅ GoalsService initialized: {goals_service}")
        logger.info(f"✅ TasksService initialized: {tasks_service}")
        logger.info(f"✅ ProjectsService initialized: {projects_service}")
        logger.info(f"✅ SyncService initialized: {sync_service}")

        # Bind services together
        tasks_service.bind_goals_service(goals_service)  # Add this line
        logger.info("✅ GoalsService bound to TasksService")

        logger.info("✅ NotionService initialized")
        logger.info("✅ GoalsService initialized")
        logger.info("✅ TasksService initialized")
        logger.info("✅ ProjectsService initialized")
        logger.info("🔗 ProjectsService linked to NotionSyncService")

        # Connect sync router
        import routers.sync_router as sync_router_module
        sync_router_module.set_sync_service(sync_service)
        logger.info("🔗 Sync router connected to NotionSyncService")

        # Load Notion → backend
        await sync_service.load_projects_into_backend()
        logger.info("📁 Projects loaded from Notion → backend OK")

        # AI Command System
        ai_command_service = AICommandService()
        logger.info("✅ AICommandService initialized")

        # Agents System
        agents_service = AgentsService(
            notion_token=os.getenv("NOTION_API_KEY"),
            exchange_db_id=os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
            projects_db_id=os.getenv("NOTION_AGENT_PROJECTS_DB_ID"),
        )
        logger.info("✅ AgentsService initialized")

        logger.info("🔥 Backend fully initialized")

    except Exception as e:
        logger.error(f"ERROR during startup: {e}")
        print(f"ERROR during startup: {e}")
        raise e
