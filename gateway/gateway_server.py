# ruff: noqa: E402
# gateway/gateway_server.py
# FULL FILE — zamijeni cijeli gateway_server.py ovim.
# Canon fixes:
# - init AI router services inside lifespan (keyword-only set_ai_services)
# - keep health/ready semantics
# - keep existing routers + Notion snapshot sync best-effort

from __future__ import annotations

import os
import logging
import uuid
import re
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List

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
_BOOT_ERROR: Optional[str] = None


def _append_boot_error(msg: str) -> None:
    global _BOOT_ERROR
    msg = (msg or "").strip()
    if not msg:
        return
    if not _BOOT_ERROR:
        _BOOT_ERROR = msg
        return
    # Append (preserve first failure context)
    _BOOT_ERROR = f"{_BOOT_ERROR}; {msg}"


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
from services.coo_conversation_service import COOConversationService
from services.approval_state_service import get_approval_state
from services.execution_registry import ExecutionRegistry
from models.ai_command import AICommand

# ================================================================
# IDENTITY / MODE / STATE
# ================================================================
from services.identity_loader import load_identity
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state

# CEO Console snapshot SSOT (READ-only)
from services.ceo_console_snapshot_service import CEOConsoleSnapshotService

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
        api_key=os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
        projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID"),
    )
)
logger.info("… NotionService singleton initialized")

# ================================================================
# WEEKLY MEMORY SERVICE (CEO DASHBOARD)
# ================================================================
from services.weekly_memory_service import get_weekly_memory_service
from services.ai_summary_service import get_ai_summary_service

# ================================================================
# ROUTERS
# ================================================================
from routers.audit_router import router as audit_router
from routers.adnan_ai_router import router as adnan_ai_router
from routers.ai_ops_router import ai_ops_router

# IMPORTANT: import MODULE (so set_ai_services is available)
import routers.ai_router as ai_router_module

# CEO Console router module (READ-only)
import routers.ceo_console_router as ceo_console_module

from routers.metrics_router import router as metrics_router
from routers.alerting_router import router as alerting_router

# ================================================================
# APPLICATION BOOTSTRAP
# ================================================================
from services.app_bootstrap import bootstrap_application

# ================================================================
# INITIAL LOAD
# ================================================================
if not OS_ENABLED:
    logger.critical("✖ OS_ENABLED=false — system will not start.")
    raise RuntimeError("OS is disabled by configuration.")

identity = load_identity()
mode = load_mode()
state = load_state()

# ================================================================
# KANONSKI EXECUTION ENTRYPOINT (INIT ONLY)
# ================================================================
ai_command_service = AICommandService()
coo_translation_service = COOTranslationService()
coo_conversation_service = COOConversationService()
_execution_registry = ExecutionRegistry()


# ================================================================
# LIFESPAN (PHASE 11)
# ================================================================
@asynccontextmanager
async def lifespan(_: FastAPI):
    global _BOOT_READY, _BOOT_ERROR

    _BOOT_READY = False
    _BOOT_ERROR = None

    try:
        # Core bootstrap (fatal ako ovdje pukne)
        bootstrap_application()

        # ---- AI router init (CANON) ----
        try:
            if not hasattr(ai_router_module, "set_ai_services"):
                raise RuntimeError("ai_router_init_hook_not_found")

            # set_ai_services is keyword-only — MUST use keyword args
            ai_router_module.set_ai_services(
                command_service=ai_command_service,
                conversation_service=coo_conversation_service,
                translation_service=coo_translation_service,
            )
            logger.info("✅ AI router services initialized")
        except Exception as exc:  # noqa: BLE001
            _append_boot_error(f"ai_router_init_failed:{exc}")
            logger.warning("AI router init failed: %s", exc)

        # Notion snapshot sync — best-effort (nije fatalno)
        try:
            from services.notion_service import get_notion_service

            notion_service = get_notion_service()
            await notion_service.sync_knowledge_snapshot()
        except Exception as exc:  # noqa: BLE001
            _append_boot_error(f"notion_sync_failed:{exc}")
            logger.warning("Notion knowledge snapshot sync failed: %s", exc)

        _BOOT_READY = True
        logger.info("✅ System boot completed. READY.")
        yield
    finally:
        _BOOT_READY = False
        logger.info("🛑 System shutdown — boot_ready=False.")


# ================================================================
# APP INIT
# ================================================================
app = FastAPI(
    title=SYSTEM_NAME,
    version=VERSION,
    lifespan=lifespan,
)

# ================================================================
# FRONTEND (CEO DASHBOARD)
# ================================================================
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

if not os.path.isdir(FRONTEND_DIR):
    logger.warning("Frontend directory not found: %s", FRONTEND_DIR)
else:
    app.mount(
        "/static",
        StaticFiles(directory=FRONTEND_DIR),
        name="static",
    )

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

# AI UX entrypoint (/api/ai/run)
app.include_router(ai_router_module.router, prefix="/api")

app.include_router(ai_ops_router, prefix="/api")
app.include_router(ceo_console_module.router, prefix="/api")

app.include_router(metrics_router, prefix="/api")
app.include_router(alerting_router, prefix="/api")


# ================================================================
# REQUEST MODELS
# ================================================================
class ExecuteInput(BaseModel):
    text: str


class ExecuteRawInput(BaseModel):
    command: str
    intent: str
    params: Dict[str, Any] = {}
    initiator: str = "ceo"
    read_only: bool = False
    metadata: Dict[str, Any] = {}


class CeoCommandInput(BaseModel):
    input_text: str
    smart_context: Optional[Dict[str, Any]] = None
    source: str = "ceo_dashboard"


def _to_serializable(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(obj, "__dict__"):
        try:
            return {k: _to_serializable(v) for k, v in obj.__dict__.items()}
        except Exception:  # noqa: BLE001
            pass
    return str(obj)


def _preprocess_ceo_nl_input(
    raw_text: str, smart_context: Optional[Dict[str, Any]]
) -> str:
    text = (raw_text or "").strip()
    if not text:
        return text

    if smart_context:
        command_type = smart_context.get("command_type")
        goal_ctx = smart_context.get("goal") or {}
        goal_name = (goal_ctx.get("name") or "").strip()
        priority = (goal_ctx.get("priority") or "").strip()
        status = (goal_ctx.get("status") or "").strip()
        due = (goal_ctx.get("due") or "").strip()
        project = (goal_ctx.get("project") or "").strip()

        if command_type == "create_goal" and goal_name:
            parts: List[str] = [goal_name]
            if priority:
                parts.append(f"prioritet {priority}")
            if status:
                parts.append(f"status {status}")
            if due:
                parts.append(f"due {due}")
            if project:
                parts.append(f"projekt {project}")
            return ", ".join(parts)

    cleaned = re.sub(
        r"^(kreiraj|napravi|create)\s+cilj[a]?\s*[:\-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or text


def _derive_legacy_goal_task_summaries_from_ceo_snapshot(
    ceo_dash_snapshot: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    goals_summary: List[Dict[str, Any]] = []
    tasks_summary: List[Dict[str, Any]] = []

    try:
        dashboard = (
            ceo_dash_snapshot.get("dashboard")
            if isinstance(ceo_dash_snapshot, dict)
            else None
        )
        if not isinstance(dashboard, dict):
            return {"goals_summary": goals_summary, "tasks_summary": tasks_summary}

        goals = dashboard.get("goals") or []
        tasks = dashboard.get("tasks") or []

        if isinstance(goals, list):
            for g in goals:
                if not isinstance(g, dict):
                    continue
                goals_summary.append(
                    {
                        "name": g.get("name") or "(bez naziva)",
                        "status": g.get("status") or "-",
                        "priority": g.get("priority") or "-",
                        "due_date": (g.get("deadline") or "-"),
                    }
                )

        if isinstance(tasks, list):
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                tasks_summary.append(
                    {
                        "title": t.get("title") or "(bez naziva)",
                        "status": t.get("status") or "-",
                        "priority": t.get("priority") or "-",
                        "due_date": (t.get("due_date") or "-"),
                    }
                )
    except Exception:  # noqa: BLE001
        pass

    return {"goals_summary": goals_summary, "tasks_summary": tasks_summary}


# ================================================================
# /api/execute — EXECUTION PATH (NL INPUT)
# ================================================================
@app.post("/api/execute")
async def execute_command(payload: ExecuteInput):
    ai_command = coo_translation_service.translate(
        raw_input=payload.text,
        source="system",
        context={"mode": "execute"},
    )
    if not ai_command:
        raise HTTPException(400, "Could not translate input to command")

    _execution_registry.register(ai_command)

    approval_id = str(uuid.uuid4())
    approval_state = get_approval_state()
    approval_state._approvals[approval_id] = {  # type: ignore[attr-defined]
        "approval_id": approval_id,
        "execution_id": ai_command.execution_id,
        "status": "pending",
        "source": "system",
        "command": ai_command.model_dump(),
    }

    return {
        "status": "BLOCKED",
        "execution_state": "BLOCKED",
        "approval_id": approval_id,
        "execution_id": ai_command.execution_id,
        "command": ai_command.model_dump(),
    }


@app.post("/api/execute/raw")
async def execute_raw_command(payload: ExecuteRawInput):
    ai_command = AICommand(
        command=payload.command,
        intent=payload.intent,
        params=payload.params,
        initiator=payload.initiator,
        read_only=payload.read_only,
        metadata=payload.metadata,
    )

    _execution_registry.register(ai_command)

    approval_id = str(uuid.uuid4())
    approval_state = get_approval_state()
    approval_state._approvals[approval_id] = {  # type: ignore[attr-defined]
        "approval_id": approval_id,
        "execution_id": ai_command.execution_id,
        "status": "pending",
        "source": "system",
        "command": ai_command.model_dump(),
    }

    return {
        "status": "BLOCKED",
        "execution_state": "BLOCKED",
        "approval_id": approval_id,
        "execution_id": ai_command.execution_id,
        "command": ai_command.model_dump(),
    }


# ================================================================
# LEGACY CEO COMMAND ENDPOINTS (READ-ONLY WRAPPERS)
# ================================================================
@app.post("/api/ceo/command")
async def ceo_dashboard_command_api(payload: CeoCommandInput):
    cleaned_text = _preprocess_ceo_nl_input(payload.input_text, payload.smart_context)

    req = ceo_console_module.CEOCommandRequest(
        text=cleaned_text,
        initiator=payload.source or "ceo_dashboard",
        session_id=None,
        context_hint=payload.smart_context,
    )
    return await ceo_console_module.ceo_command(req)


@app.post("/ceo/command")
async def ceo_dashboard_command_public(payload: CeoCommandInput):
    return await ceo_dashboard_command_api(payload)


# ================================================================
# CEO CONSOLE SNAPSHOT (READ-ONLY)
# ================================================================
@app.get("/api/ceo/console/snapshot")
async def ceo_console_snapshot():
    approval_state = get_approval_state()
    approvals_map: Dict[str, Dict[str, Any]] = getattr(approval_state, "_approvals", {})
    approvals_list = list(approvals_map.values())

    pending = [a for a in approvals_list if a.get("status") == "pending"]
    approved = [a for a in approvals_list if a.get("status") == "approved"]
    rejected = [a for a in approvals_list if a.get("status") == "rejected"]
    failed = [a for a in approvals_list if a.get("status") == "failed"]
    completed = [a for a in approvals_list if a.get("status") == "completed"]

    ks = KnowledgeSnapshotService.get_snapshot()

    # SSOT: CEOConsoleSnapshotService (never raises)
    ceo_dash = CEOConsoleSnapshotService().snapshot()
    legacy = _derive_legacy_goal_task_summaries_from_ceo_snapshot(ceo_dash)

    snapshot: Dict[str, Any] = {
        "system": {
            "name": SYSTEM_NAME,
            "version": VERSION,
            "release_channel": RELEASE_CHANNEL,
            "arch_lock": ARCH_LOCK,
            "os_enabled": OS_ENABLED,
            "ops_safe_mode": OPS_SAFE_MODE,
            "boot_ready": _BOOT_READY,
            "boot_error": _BOOT_ERROR,
        },
        "identity": _to_serializable(identity),
        "mode": _to_serializable(mode),
        "state": _to_serializable(state),
        "approvals": {
            "total": len(approvals_list),
            "pending_count": len(pending),
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
        "ceo_dashboard_snapshot": _to_serializable(ceo_dash),
        "goals_summary": legacy["goals_summary"],
        "tasks_summary": legacy["tasks_summary"],
    }
    return snapshot


@app.get("/ceo/console/snapshot")
async def ceo_console_snapshot_public():
    return await ceo_console_snapshot()


@app.get("/api/ceo/console/weekly-memory")
async def ceo_weekly_memory():
    wm_snapshot = get_weekly_memory_service().get_snapshot()
    return {"weekly_memory": _to_serializable(wm_snapshot)}


@app.get("/ceo/weekly-priority-memory")
async def ceo_weekly_priority_memory():
    try:
        items = get_ai_summary_service().get_this_week_priorities()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to load Weekly Priority Memory from AI SUMMARY DB")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load Weekly Priority Memory from AI SUMMARY DB: {exc}",
        ) from exc
    return {"items": [i.model_dump() for i in items]}


@app.get("/")
async def serve_frontend():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.isfile(index_path):
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


# ================================================================
# HEALTH / READY
# ================================================================
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": VERSION,
        "boot_ready": _BOOT_READY,
        "boot_error": _BOOT_ERROR,
        "ops_safe_mode": OPS_SAFE_MODE,
    }


@app.get("/ready")
async def ready_check():
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail=_BOOT_ERROR or "System not ready")
    return {
        "status": "ready",
        "version": VERSION,
        "boot_ready": _BOOT_READY,
        "ops_safe_mode": OPS_SAFE_MODE,
    }


# ================================================================
# GLOBAL ERROR HANDLER + CORS
# ================================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("GLOBAL ERROR")
    return JSONResponse(
        status_code=500, content={"status": "error", "message": str(exc)}
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
