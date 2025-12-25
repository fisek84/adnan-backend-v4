# gateway/gateway_server.py
# ruff: noqa: E402
# FULL FILE — zamijeni cijeli gateway_server.py ovim.

from __future__ import annotations

import os
import logging
import uuid
import re
import json
from pathlib import Path
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
load_dotenv(override=False)


def _env_true(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() == "true"


def _ops_safe_mode() -> bool:
    # IMPORTANT: runtime read, not frozen at import
    return _env_true("OPS_SAFE_MODE", "false")


OS_ENABLED = _env_true("OS_ENABLED", "true")

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
    _BOOT_ERROR = f"{_BOOT_ERROR}; {msg}"


# ================================================================
# PATHS (repo-root aware)
# ================================================================
REPO_ROOT = Path(__file__).resolve().parents[1]  # .../gateway/gateway_server.py -> repo root
FRONTEND_DIR = REPO_ROOT / "gateway" / "frontend"


def _agents_registry_path() -> Path:
    """
    SSOT registry path.
    Default: <repo_root>/config/agents.json

    Env overrides (priority):
      1) AGENTS_JSON_PATH (canonical; shared with AgentRegistryService resolver)
      2) AGENTS_REGISTRY_PATH (legacy gateway override)
    """
    p = (os.getenv("AGENTS_JSON_PATH") or "").strip()
    if p:
        return Path(p)

    p2 = (os.getenv("AGENTS_REGISTRY_PATH") or "").strip()
    if p2:
        return Path(p2)

    return REPO_ROOT / "config" / "agents.json"


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
from services.execution_orchestrator import ExecutionOrchestrator
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
# FAZA 4 — AGENT REGISTRY + ROUTER + CANONICAL CHAT ENDPOINT
# ================================================================
from services.agent_registry_service import get_agent_registry_service
from services.agent_router_service import AgentRouterService
from routers.chat_router import build_chat_router

_agent_registry = get_agent_registry_service()  # SINGLETON (SSOT in runtime)
_agent_router = AgentRouterService(_agent_registry)
_chat_router = build_chat_router(_agent_router)  # defines "/chat"

# ================================================================
# ROUTERS
# ================================================================
from routers.audit_router import router as audit_router
from routers.adnan_ai_router import router as adnan_ai_router
from routers.ai_ops_router import ai_ops_router

# OPTIONAL: import module for possible injection hooks
import routers.ai_ops_router as ai_ops_router_module

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
_execution_orchestrator = ExecutionOrchestrator()


def _ai_command_field_names() -> set[str]:
    model_fields = getattr(AICommand, "model_fields", None)
    if isinstance(model_fields, dict):
        return set(model_fields.keys())
    v1_fields = getattr(AICommand, "__fields__", None)
    if isinstance(v1_fields, dict):
        return set(v1_fields.keys())
    return set()


def _ensure_execution_id(ai_command: AICommand) -> str:
    """
    Guarantee da komanda ima execution_id, jer approval correlation često zavisi od toga.
    """
    existing = getattr(ai_command, "execution_id", None)
    if isinstance(existing, str) and existing.strip():
        return existing

    new_id = str(uuid.uuid4())
    try:
        ai_command.execution_id = new_id  # type: ignore[attr-defined]
    except Exception:
        md = getattr(ai_command, "metadata", None)
        if not isinstance(md, dict):
            md = {}
        md["execution_id"] = new_id
        ai_command.metadata = md
    return new_id


def _ensure_trace_on_command(ai_command: AICommand, *, approval_id: str) -> None:
    md = getattr(ai_command, "metadata", None)
    if not isinstance(md, dict):
        md = {}
    md["approval_id"] = approval_id
    ai_command.metadata = md

    fields = _ai_command_field_names()
    if "approval_id" in fields:
        try:
            ai_command.approval_id = approval_id  # type: ignore[attr-defined]
        except Exception:
            pass


def _safe_command_summary(ai_command: AICommand) -> Dict[str, Any]:
    try:
        if hasattr(ai_command, "model_dump"):
            out = ai_command.model_dump()
            return out if isinstance(out, dict) else {}
    except Exception:
        pass
    try:
        if hasattr(ai_command, "dict"):
            out = ai_command.dict()
            return out if isinstance(out, dict) else {}
    except Exception:
        pass

    params = getattr(ai_command, "params", None)
    intent = getattr(ai_command, "intent", None)
    cmd = getattr(ai_command, "command", None)

    return {
        "command": cmd,
        "intent": intent,
        "params": params if isinstance(params, dict) else {},
    }


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
        except Exception:
            pass
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
# LIFESPAN
# ================================================================
@asynccontextmanager
async def lifespan(_: FastAPI):
    global _BOOT_READY, _BOOT_ERROR

    _BOOT_READY = False
    _BOOT_ERROR = None

    try:
        bootstrap_application()

        # ---- FAZA 4: load agents.json (SSOT) ----
        try:
            p = _agents_registry_path()
            load_result = _agent_registry.load_from_agents_json(str(p), clear=True)
            logger.info(
                "✅ Agent registry loaded (SSOT): path=%s loaded=%s version=%s",
                load_result.get("path"),
                load_result.get("loaded"),
                load_result.get("version"),
            )
        except Exception as exc:  # noqa: BLE001
            _append_boot_error(f"agents_registry_load_failed:{exc}")
            logger.warning("Agent registry load failed: %s", exc)

        # ---- AI router init (CANON) ----
        try:
            if not hasattr(ai_router_module, "set_ai_services"):
                raise RuntimeError("ai_router_init_hook_not_found")

            ai_router_module.set_ai_services(
                command_service=ai_command_service,
                conversation_service=coo_conversation_service,
                translation_service=coo_translation_service,
            )
            logger.info("✅ AI router services initialized")
        except Exception as exc:  # noqa: BLE001
            _append_boot_error(f"ai_router_init_failed:{exc}")
            logger.warning("AI router init failed: %s", exc)

        # ---- AI OPS router optional injection ----
        try:
            hook = getattr(ai_ops_router_module, "set_ai_ops_services", None)
            if callable(hook):
                hook(orchestrator=_execution_orchestrator, approvals=get_approval_state())
                logger.info("✅ AI Ops router services injected (shared orchestrator/approvals)")
        except Exception as exc:  # noqa: BLE001
            _append_boot_error(f"ai_ops_injection_failed:{exc}")
            logger.warning("AI Ops services injection failed: %s", exc)

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
if not FRONTEND_DIR.is_dir():
    logger.warning("Frontend directory not found: %s", FRONTEND_DIR)
else:
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="static",
    )

    @app.get("/style.css", include_in_schema=False)
    async def serve_style_css():
        path = FRONTEND_DIR / "style.css"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="style.css not found")
        return FileResponse(str(path))

    @app.get("/script.js", include_in_schema=False)
    async def serve_script_js():
        path = FRONTEND_DIR / "script.js"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="script.js not found")
        return FileResponse(str(path))


# ================================================================
# INCLUDE ROUTERS
# ================================================================
app.include_router(audit_router, prefix="/api")
app.include_router(adnan_ai_router, prefix="/api")

# AI UX entrypoint (/api/ai/run)
app.include_router(ai_router_module.router, prefix="/api")

# AI OPS (approvals + agents registry/health)
app.include_router(ai_ops_router, prefix="/api")

# CEO Console
app.include_router(ceo_console_module.router, prefix="/api")

app.include_router(metrics_router, prefix="/api")
app.include_router(alerting_router, prefix="/api")

# FAZA 4: Canonical Chat endpoint — /api/chat
app.include_router(_chat_router, prefix="/api")


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


def _preprocess_ceo_nl_input(raw_text: str, smart_context: Optional[Dict[str, Any]]) -> str:
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
        dashboard = ceo_dash_snapshot.get("dashboard") if isinstance(ceo_dash_snapshot, dict) else None
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
    except Exception:
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

    if not getattr(ai_command, "initiator", None):
        ai_command.initiator = "ceo"

    execution_id = _ensure_execution_id(ai_command)

    approval_state = get_approval_state()
    approval = approval_state.create(
        command=getattr(ai_command, "command", None) or "execute",
        payload_summary=_safe_command_summary(ai_command),
        scope="api_execute",
        risk_level="unknown",
        execution_id=execution_id,
    )
    approval_id = approval.get("approval_id")
    if not approval_id:
        raise HTTPException(status_code=500, detail="Approval create failed: missing approval_id")

    _ensure_trace_on_command(ai_command, approval_id=approval_id)
    _execution_registry.register(ai_command)

    result = await _execution_orchestrator.execute(ai_command)

    if isinstance(result, dict):
        result.setdefault("approval_id", approval_id)
        result.setdefault("execution_id", execution_id)

    return result


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

    execution_id = _ensure_execution_id(ai_command)

    approval_state = get_approval_state()
    approval = approval_state.create(
        command=payload.command or "execute_raw",
        payload_summary=_safe_command_summary(ai_command),
        scope="api_execute_raw",
        risk_level="unknown",
        execution_id=execution_id,
    )
    approval_id = approval.get("approval_id")
    if not approval_id:
        raise HTTPException(status_code=500, detail="Approval create failed: missing approval_id")

    _ensure_trace_on_command(ai_command, approval_id=approval_id)
    _execution_registry.register(ai_command)

    return {
        "status": "BLOCKED",
        "execution_state": "BLOCKED",
        "approval_id": approval_id,
        "execution_id": execution_id,
        "command": ai_command.model_dump() if hasattr(ai_command, "model_dump") else _to_serializable(ai_command),
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

    ceo_dash = CEOConsoleSnapshotService().snapshot()
    legacy = _derive_legacy_goal_task_summaries_from_ceo_snapshot(ceo_dash)

    snapshot: Dict[str, Any] = {
        "system": {
            "name": SYSTEM_NAME,
            "version": VERSION,
            "release_channel": RELEASE_CHANNEL,
            "arch_lock": ARCH_LOCK,
            "os_enabled": OS_ENABLED,
            "ops_safe_mode": _ops_safe_mode(),  # runtime
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
    except Exception as exc:
        logger.exception("Failed to load Weekly Priority Memory from AI SUMMARY DB")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load Weekly Priority Memory from AI SUMMARY DB: {exc}",
        ) from exc
    return {"items": [i.model_dump() for i in items]}


@app.get("/")
async def serve_frontend():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(str(index_path))


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
        "ops_safe_mode": _ops_safe_mode(),  # runtime
    }


@app.get("/ready")
async def ready_check():
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail=_BOOT_ERROR or "System not ready")
    return {
        "status": "ready",
        "version": VERSION,
        "boot_ready": _BOOT_READY,
        "ops_safe_mode": _ops_safe_mode(),  # runtime
    }


# ================================================================
# GLOBAL ERROR HANDLER + CORS
# ================================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("GLOBAL ERROR")
    return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
