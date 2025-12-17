# ================================================================
# SYSTEM VERSION (V1.1 — VERZIJA C)
# ================================================================
import os
import logging
import uuid
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel

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

# ================================================================
# LOGGING (KANONSKI)
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("gateway")

# ================================================================
# CORE SERVICES
# ================================================================
from services.ai_command_service import AICommandService
from services.coo_translation_service import COOTranslationService
from services.approval_state_service import get_approval_state
from services.execution_registry import ExecutionRegistry
from models.ai_command import AICommand

# ================================================================
# IDENTITY / MODE / STATE
# ================================================================
from services.identity_loader import load_identity
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state

# ================================================================
# NOTION SERVICE (KANONSKI INIT)
# ================================================================
from services.notion_service import (
    NotionService,
    set_notion_service,
)

set_notion_service(
    NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
        projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID"),
    )
)

logger.info("✅ NotionService singleton initialized")

# ================================================================
# ROUTERS
# ================================================================
from routers.audit_router import router as audit_router
from routers.adnan_ai_router import router as adnan_ai_router
from routers.ai_ops_router import ai_ops_router

# ================================================================
# APPLICATION BOOTSTRAP
# ================================================================
from services.app_bootstrap import bootstrap_application

# ================================================================
# INITIAL LOAD
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
# FRONTEND
# ================================================================
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

app.mount(
    "/frontend",
    StaticFiles(directory=FRONTEND_DIR),
    name="frontend",
)

# ================================================================
# INCLUDE ROUTERS
# ================================================================
app.include_router(audit_router, prefix="/api")
app.include_router(adnan_ai_router, prefix="/api")
app.include_router(ai_ops_router, prefix="/api")

# ================================================================
# KANONSKI EXECUTION ENTRYPOINT (INIT ONLY)
# ================================================================
ai_command_service = AICommandService()
coo_translation_service = COOTranslationService()
_execution_registry = ExecutionRegistry()


class ExecuteInput(BaseModel):
    text: str


class ExecuteRawInput(BaseModel):
    """
    RAW AICommand ulaz — za internu / agentsku upotrebu.

    - NE preskače governance/approval: i dalje BLOCKED → APPROVAL → EXECUTED
    - Kada već imaš strukturisan AICommand (npr. multi-DB Notion ops).
    """
    command: str
    intent: str
    params: Dict[str, Any] = {}
    initiator: str = "ceo"
    read_only: bool = False
    metadata: Dict[str, Any] = {}


def _to_serializable(obj: Any) -> Any:
    """
    Helper za CEO Console snapshot:
    - ne uvodi novi state
    - samo pretvara identity/mode/state u JSON-friendly oblik
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(v) for v in obj]
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return {k: _to_serializable(v) for k, v in obj.__dict__.items()}
        except Exception:
            pass
    return str(obj)


@app.post("/api/execute")
async def execute_command(payload: ExecuteInput):
    """
    Kanonski CEO → COO ulaz (natural language).
    """
    ai_command = coo_translation_service.translate(
        raw_input=payload.text,
        source="system",
        context={"mode": "execute"},
    )

    if not ai_command:
        raise HTTPException(400, "Could not translate input to command")

    # AICommand već ima request_id / execution_id (normalize_ids)
    _execution_registry.register(ai_command)

    approval_id = str(uuid.uuid4())

    approval_state = get_approval_state()
    approval_state._approvals[approval_id] = {
        "approval_id": approval_id,
        "execution_id": ai_command.execution_id,
        "status": "pending",
        "source": "system",
        "command": ai_command.dict(),
    }

    return {
        "status": "BLOCKED",
        "execution_state": "BLOCKED",
        "approval_id": approval_id,
        "execution_id": ai_command.execution_id,
        "command": ai_command.dict(),
    }


@app.post("/api/execute/raw")
async def execute_raw_command(payload: ExecuteRawInput):
    """
    Kanonski RAW ulaz: direktno kreira AICommand bez COO NLP-a.

    - i dalje: BLOCKED + approval_id
    - resume i EXECUTED idu kroz /api/ai-ops/approval/approve
    """
    ai_command = AICommand(
        command=payload.command,
        intent=payload.intent,
        params=payload.params,
        initiator=payload.initiator,
        read_only=payload.read_only,
        metadata=payload.metadata,
    )

    # execution_id je već generisan (request_id), ali ga možemo eksplicitno koristiti
    _execution_registry.register(ai_command)

    approval_id = str(uuid.uuid4())

    approval_state = get_approval_state()
    approval_state._approvals[approval_id] = {
        "approval_id": approval_id,
        "execution_id": ai_command.execution_id,
        "status": "pending",
        "source": "system",
        "command": ai_command.dict(),
    }

    return {
        "status": "BLOCKED",
        "execution_state": "BLOCKED",
        "approval_id": approval_id,
        "execution_id": ai_command.execution_id,
        "command": ai_command.dict(),
    }


# ================================================================
# CEO CONSOLE SNAPSHOT (READ-ONLY, BEZ EXECUTIONA)
# ================================================================
@app.get("/api/ceo/console/snapshot")
async def ceo_console_snapshot():
    """
    Read-only sistemski snapshot za CEO Console.

    Poštuje kanon:
    - NEMA execution-a, NEMA write-a
    - samo vraća već postojeće stanje sistema (identity/mode/state + approvals)
    - sve je auditabilno i deterministicno
    """
    approval_state = get_approval_state()
    approvals_map: Dict[str, Dict[str, Any]] = getattr(
        approval_state, "_approvals", {}
    )

    approvals_list = list(approvals_map.values())
    pending = [a for a in approvals_list if a.get("status") == "pending"]
    completed = [a for a in approvals_list if a.get("status") == "completed"]
    failed = [a for a in approvals_list if a.get("status") == "failed"]

    snapshot: Dict[str, Any] = {
        "system": {
            "name": SYSTEM_NAME,
            "version": VERSION,
            "release_channel": RELEASE_CHANNEL,
            "arch_lock": ARCH_LOCK,
            "os_enabled": OS_ENABLED,
            "ops_safe_mode": OPS_SAFE_MODE,
            "boot_ready": _BOOT_READY,
        },
        "identity": _to_serializable(identity),
        "mode": _to_serializable(mode),
        "state": _to_serializable(state),
        "approvals": {
            "total": len(approvals_list),
            "pending_count": len(pending),
            "completed_count": len(completed),
            "failed_count": len(failed),
            "pending": pending,
        },
    }

    return snapshot


# ================================================================
# ROOT
# ================================================================
@app.get("/")
async def serve_frontend():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.isfile(index_path):
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)

# ================================================================
# HEALTH
# ================================================================
@app.get("/health")
async def health_check():
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail="System not ready")
    return {"status": "ok"}

# ================================================================
# ERROR HANDLER
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

    bootstrap_application()

    from services.notion_service import get_notion_service
    notion_service = get_notion_service()

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
