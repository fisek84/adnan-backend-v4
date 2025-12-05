from fastapi import FastAPI
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import DI initialization
from dependencies import init_services

# Import routers
from routers.goals_router import router as goals_router
from routers.tasks_router import router as tasks_router
from routers.projects_router import router as projects_router
from routers.sync_router import router as sync_router
from routers.ai_ops_router import router as ai_ops_router
from routers.adnan_ai_router import router as adnan_ai_router

# App init
app = FastAPI()

# Logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@app.on_event("startup")
async def startup_event():
    logger.info("🔵 Starting backend services...")

    # Central initialization → dependencies.py
    init_services()

    logger.info("🟩 All services initialized successfully.")


# Routers
app.include_router(goals_router)
app.include_router(tasks_router)
app.include_router(projects_router)
app.include_router(sync_router)
app.include_router(ai_ops_router)
app.include_router(adnan_ai_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": "Backend is running"}
