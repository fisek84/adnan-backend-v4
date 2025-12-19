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
OPS_SAFE_MODE = os.getenv("OPS_SAFE_MODE", "false").lower() == "false"

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
from services.knowledge_snapshot_service import KnowledgeSnapshotService

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
# FRONTEND (CEO DASHBOARD)
# ================================================================
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

if not os.path.isdir(FRONTEND_DIR):
    logger.warning("Frontend directory not found: %s", FRONTEND_DIR)
else:
    # /static -> sve iz gateway/frontend (style.css, script.js, slike...)
    app.mount(
        "/static",
        StaticFiles(directory=FRONTEND_DIR),
        name="static",
    )

    # Direktni routeovi za postojeće linkove /style.css i /script.js
    @app.get("/style.css", include_in_schema=False)
    async def serve_style_css():
        path = os.path.join(FRONTEND_DIR, "style.css")
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="style.css not found")
        return FileResponse(path)

    @app.get("/script.js", include_in_schema=False)
    async def serve_script_js():
        path = os.path.join(FRONTEND_DIR, "script.js")
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="script.js not found")
        return FileResponse(path)


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


# ================================================================
# /api/execute — CEO → COO (NL INPUT)
# ================================================================
@app.post("/api/execute")
async def execute_command(payload: ExecuteInput):
    """
    Kanonski CEO → COO ulaz (natural language).

    - CEO daje tekstualnu komandu
    - COO Translation pretvara u AICommand
    - AICommand se REGISTRUJE i BLOKUJE (BLOCKED)
    - Approval ide kroz /api/ai-ops/approval/approve
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


# ================================================================
# /api/execute/raw — DIREKTAN AICommand (AGENT / SYSTEM)
# ================================================================
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
    - samo vraća već postojeće stanje sistema (identity/mode/state + approvals + goals/tasks summary)
    - sve je auditabilno i determinističko
    """
    approval_state = get_approval_state()
    approvals_map: Dict[str, Dict[str, Any]] = getattr(
        approval_state, "_approvals", {}
    )

    approvals_list = list(approvals_map.values())

    # deriviramo cijevovod po statusima (čisto čitanje)
    pending = [a for a in approvals_list if a.get("status") == "pending"]
    approved = [a for a in approvals_list if a.get("status") == "approved"]
    rejected = [a for a in approvals_list if a.get("status") == "rejected"]
    failed = [a for a in approvals_list if a.get("status") == "failed"]
    completed = [a for a in approvals_list if a.get("status") == "completed"]

    # Knowledge snapshot (goals/tasks agregati + AI summary) — čist READ
    ks = KnowledgeSnapshotService.get_snapshot()
    ks_dbs = ks.get("databases") or {}
    goals_summary_raw = ks_dbs.get("goals_summary")
    tasks_summary_raw = ks_dbs.get("tasks_summary")
    ai_summary_raw = ks_dbs.get("ai_summary")

    weekly_memory = None

    # Izvučemo najnoviji AI summary (best-effort, bez pisanja)
    if isinstance(ai_summary_raw, list) and ai_summary_raw:
        latest_item = ai_summary_raw[0]

        title = None
        week_range = None
        short_summary = None
        notion_page_id = None
        notion_url = None

        if isinstance(latest_item, dict):
            title = (
                latest_item.get("title")
                or latest_item.get("Name")
            )
            week_range = (
                latest_item.get("week")
                or latest_item.get("Week")
                or latest_item.get("period")
                or latest_item.get("Period")
                or latest_item.get("date")
                or latest_item.get("Date")
            )
            short_summary = (
                latest_item.get("summary")
                or latest_item.get("Summary")
                or latest_item.get("description")
                or latest_item.get("Description")
            )
            notion_page_id = latest_item.get("id") or latest_item.get("page_id")
            notion_url = latest_item.get("url") or latest_item.get("notion_url")

            latest_raw = _to_serializable(latest_item)
        else:
            latest_raw = _to_serializable(latest_item)

        weekly_memory = {
            "latest_ai_summary": {
                "title": title,
                "week_range": week_range,
                "short_summary": short_summary,
                "notion_page_id": notion_page_id,
                "notion_url": notion_url,
                "raw": latest_raw,
            }
        }

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
            # kompatibilnost + precizniji statusi
            "completed_count": len(completed),
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "failed_count": len(failed),
            "pending": pending,
        },
        "knowledge_snapshot": {
            "ready": ks.get("ready"),
            "last_sync": ks.get("last_sync"),
        },
        # novi blok za CEO Weekly Memory (AI summary)
        "weekly_memory": _to_serializable(weekly_memory)
        if weekly_memory is not None
        else None,
        # postojeći ključevi za CEO Goals/Tasks panel
        "goals_summary": _to_serializable(goals_summary_raw)
        if goals_summary_raw is not None
        else None,
        "tasks_summary": _to_serializable(tasks_summary_raw)
        if tasks_summary_raw is not None
        else None,
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

    # READ-ONLY sync znanja iz Notiona (goals/tasks agregati)
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
