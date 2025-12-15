# ================================================================
# SYSTEM VERSION (V1.1 — VERZIJA C)
# ================================================================
import os
import time
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

from system_version import (
    SYSTEM_NAME,
    VERSION,
    ARCH_LOCK,
    RELEASE_CHANNEL,
)

# ================================================================
# ENV / BOOTSTRAP
# ================================================================
load_dotenv(".env")

OS_ENABLED = os.getenv("OS_ENABLED", "true").lower() == "true"
OPS_SAFE_MODE = os.getenv("OPS_SAFE_MODE", "false").lower() == "true"

_BOOT_READY = False
_LAST_CALL_TS = 0.0
MIN_INTERVAL_SECONDS = 0.5

# ================================================================
# LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("gateway")

# ================================================================
# CORE MODELS / SERVICES
# ================================================================
from services.conversation_state_service import ConversationStateService
from services.awareness_service import AwarenessService
from services.response_formatter import ResponseFormatter

# ================================================================
# IDENTITY / MODE / STATE
# ================================================================
from services.identity_loader import load_identity
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state

# ================================================================
# NOTION (READ-ONLY SNAPSHOT)
# ================================================================
from services.notion_service import NotionService

# ================================================================
# ROUTERS
# ================================================================
from routers.audit_router import router as audit_router
from routers.adnan_ai_router import router as adnan_ai_router

# ================================================================
# INITIAL LOAD (FAIL FAST)
# ================================================================
if not OS_ENABLED:
    logger.critical("❌ OS_ENABLED=false — system will not start.")
    raise RuntimeError("OS is disabled by configuration.")

identity = load_identity()
mode = load_mode()
state = load_state()

# ================================================================
# APP INIT
# ================================================================
app = FastAPI(
    title=SYSTEM_NAME,
    version=VERSION,
)

# ================================================================
# INCLUDE ROUTERS
# ================================================================
app.include_router(audit_router)
app.include_router(adnan_ai_router)

# ================================================================
# ROOT + HEALTH
# ================================================================
@app.get("/")
async def root():
    return {
        "status": "ok",
        "system": SYSTEM_NAME,
        "version": VERSION,
        "release_channel": RELEASE_CHANNEL,
        "arch_lock": ARCH_LOCK,
        "safe_mode": OPS_SAFE_MODE,
        "boot_ready": _BOOT_READY,
        "read_only": False,
    }

@app.get("/health")
async def health_check():
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail="System not ready")
    return {"status": "ok"}

# ================================================================
# SINGLETON SERVICES
# ================================================================
conversation_state_service = ConversationStateService()
awareness_service = AwarenessService()
response_formatter = ResponseFormatter()

# ================================================================
# NOTION SERVICE
# ================================================================
notion_service = NotionService(
    api_key=os.getenv("NOTION_API_KEY"),
    goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
    tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
    projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID"),
)

# ================================================================
# GLOBAL ERROR HANDLER
# ================================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("GLOBAL ERROR")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)},
    )

# ================================================================
# STARTUP
# ================================================================
@app.on_event("startup")
async def startup_event():
    global _BOOT_READY
    logger.info(">> Startup: syncing Notion knowledge snapshot")
    await notion_service.sync_knowledge_snapshot()
    _BOOT_READY = True
    logger.info("🟢 System boot completed. READY.")

# ================================================================
# CORS
# ================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
