from fastapi import FastAPI, Depends
import logging

# Import services
from services.notion_service import NotionService
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.projects_service import ProjectsService
from services.notion_sync_service import NotionSyncService

# Import routers
from routers.goals_router import router as goals_router
from routers.tasks_router import router as tasks_router
from routers.projects_router import router as projects_router
from routers.sync_router import router as sync_router
from routers.ai_ops_router import router as ai_ops_router
from routers.adnan_ai_router import router as adnan_ai_router

# Import dependencies
from dependencies import (
    get_notion_service,
    get_goals_service,
    get_tasks_service,
    get_projects_service,
    get_sync_service,
)

# Initialize FastAPI app
app = FastAPI()

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize services
@app.on_event("startup")
async def startup_event():
    try:
        logger.info("🔵 Starting backend services...")

        # Initialize NotionService
        notion_service = NotionService(
            api_key="YOUR_NOTION_API_KEY",
            goals_db_id="YOUR_GOALS_DB_ID",
            tasks_db_id="YOUR_TASKS_DB_ID",
            projects_db_id="YOUR_PROJECTS_DB_ID"
        )
        # Initialize GoalsService, TasksService, ProjectsService
        goals_service = GoalsService()
        tasks_service = TasksService(notion_service)
        projects_service = ProjectsService()

        # Bind services to each other
        goals_service.bind_tasks_service(tasks_service)
        tasks_service.bind_goals_service(goals_service)
        projects_service.bind_goals_service(goals_service)

        # Initialize NotionSyncService
        notion_sync_service = NotionSyncService(
            notion_service,
            goals_service,
            tasks_service,
            projects_service,
            "YOUR_GOALS_DB_ID",
            "YOUR_TASKS_DB_ID",
            "YOUR_PROJECTS_DB_ID"
        )

        # Get sync service and check if it is initialized
        sync_service = get_sync_service()
        logger.info(f"Sync service: {sync_service}")  # Log the sync_service to check its value

        if sync_service is not None:
            sync_service.set_sync_service(notion_sync_service)
        else:
            logger.error("sync_service is not initialized.")
            raise Exception("Failed to initialize sync_service.")

        # Sync services with Notion
        await notion_sync_service.load_projects_into_backend()

        logger.info("🟩 All services initialized successfully.")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise e

# Include routers
app.include_router(goals_router)
app.include_router(tasks_router)
app.include_router(projects_router)
app.include_router(sync_router)
app.include_router(ai_ops_router)
app.include_router(adnan_ai_router)

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Backend is healthy"}

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to the backend!"}
