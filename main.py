from fastapi import FastAPI
import logging
from dotenv import load_dotenv

load_dotenv()

from dependencies import init_services

from routers.goals_router import router as goals_router
from routers.tasks_router import router as tasks_router
from routers.projects_router import router as projects_router
from routers.sync_router import router as sync_router
from routers.ai_ops_router import router as ai_ops_router
from routers.adnan_ai_router import router as adnan_ai_router
from routers.adnan_ai_data_router import router as adnan_ai_data_router
from routers.adnan_ai_query_router import router as adnan_ai_query_router   # ← DODANO


app = FastAPI()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@app.on_event("startup")
async def startup_event():
    logger.info("🔵 Starting backend services...")
    init_services()
    logger.info("🟩 All services initialized successfully.")


app.include_router(goals_router)
app.include_router(tasks_router)
app.include_router(projects_router)
app.include_router(sync_router)
app.include_router(ai_ops_router)
app.include_router(adnan_ai_router)
app.include_router(adnan_ai_data_router)
app.include_router(adnan_ai_query_router)     # ← DODANO


@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Backend is healthy"}


@app.get("/")
async def root():
    return {"message": "Backend is running"}
