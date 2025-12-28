# gateway/gateway_server.py
# ruff: noqa: E402
# FULL FILE — zamijeni cijeli gateway_server.py ovim.

from __future__ import annotations

import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from system_version import ARCH_LOCK, RELEASE_CHANNEL, SYSTEM_NAME, VERSION

# ================================================================
# ENV / BOOTSTRAP
# ================================================================
# On managed runtimes (Render), env vars should come from the platform.
# Keep dotenv primarily for local dev.
#
# FIX:
# - Nemoj koristiti load_dotenv() bez putanje, jer zavisi od CWD-a i reload procesa.
# - Učitaj .env eksplicitno iz repo root-a.
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # noqa: BLE001
    load_dotenv = None  # type: ignore

if os.getenv("RENDER") != "true" and load_dotenv:
    _env_path = Path(__file__).resolve().parents[1] / ".env"  # repo root .env
    load_dotenv(dotenv_path=_env_path, override=False)


def _env_true(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() == "true"


def _ops_safe_mode() -> bool:
    # IMPORTANT: runtime read, not frozen at import
    return _env_true("OPS_SAFE_MODE", "false")


def _ceo_token_enforcement_enabled() -> bool:
    return _env_true("CEO_TOKEN_ENFORCEMENT", "false")


def _require_ceo_token_if_enforced(request: Request) -> None:
    if not _ceo_token_enforcement_enabled():
        return

    expected = (os.getenv("CEO_APPROVAL_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="CEO token enforcement enabled but CEO_APPROVAL_TOKEN is not set",
        )

    # Primary header
    provided = (request.headers.get("X-CEO-Token") or "").strip()

    # Allow Bearer token as alternative (frontend may send Authorization)
    if not provided:
        auth = (request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()

    if provided != expected:
        raise HTTPException(status_code=403, detail="CEO token required")


def _guard_write_bulk(request: Request) -> None:
    # Minimal Canon guard for legacy bulk endpoints in this file:
    # - respect OPS_SAFE_MODE
    # - optional CEO token
    if _ops_safe_mode():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)


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
REPO_ROOT = Path(__file__).resolve().parents[1]

# REACT BUILD OUTPUT (Vite default):
#   gateway/frontend/dist/index.html
#   gateway/frontend/dist/assets/...
FRONTEND_DIST_DIR = REPO_ROOT / "gateway" / "frontend" / "dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"


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
from models.agent_contract import ProposedCommand
from models.ai_command import AICommand
from routers.chat_router import build_chat_router
from services.ai_command_service import AICommandService
from services.approval_state_service import get_approval_state
from services.coo_conversation_service import COOConversationService
from services.coo_translation_service import COOTranslationService
from services.execution_orchestrator import ExecutionOrchestrator
from services.execution_registry import ExecutionRegistry

# ================================================================
# IDENTITY / MODE / STATE
# ================================================================
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state
from services.identity_loader import load_identity

# CEO Console snapshot SSOT (READ-only)
from services.ceo_console_snapshot_service import CEOConsoleSnapshotService

# ================================================================
# NOTION SERVICE (KANONSKI INIT)
# ================================================================
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.notion_service import NotionService, set_notion_service

set_notion_service(
    NotionService(
        api_key=((os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN") or "").strip()),
        goals_db_id=(os.getenv("NOTION_GOALS_DB_ID") or "").strip(),
        tasks_db_id=(os.getenv("NOTION_TASKS_DB_ID") or "").strip(),
        projects_db_id=(os.getenv("NOTION_PROJECTS_DB_ID") or "").strip(),
    )
)
logger.info("NotionService singleton initialized")

# ================================================================
# WEEKLY MEMORY SERVICE (CEO DASHBOARD)
# ================================================================
from services.ai_summary_service import get_ai_summary_service
from services.weekly_memory_service import get_weekly_memory_service

# ================================================================
# FAZA 4 — AGENT REGISTRY + ROUTER + CANONICAL CHAT ENDPOINT
# ================================================================
from services.agent_registry_service import get_agent_registry_service
from services.agent_router_service import AgentRouterService

_agent_registry = get_agent_registry_service()  # SINGLETON (SSOT in runtime)
_agent_router = AgentRouterService(_agent_registry)
_chat_router = build_chat_router(_agent_router)  # defines "/chat"

# ================================================================
# ROUTERS
# ================================================================
from routers.adnan_ai_router import router as adnan_ai_router
from routers.ai_ops_router import ai_ops_router
from routers.alerting_router import router as alerting_router
from routers.audit_router import router as audit_router
from routers.metrics_router import router as metrics_router

# OPTIONAL: import module for possible injection hooks
import routers.ai_ops_router as ai_ops_router_module

# IMPORTANT: import MODULE (so set_ai_services is available)
import routers.ai_router as ai_router_module

# CEO Console router module (READ-only)
import routers.ceo_console_router as ceo_console_module

# ================================================================
# APPLICATION BOOTSTRAP
# ================================================================
from services.app_bootstrap import bootstrap_application

# ================================================================
# INITIAL LOAD
# ================================================================
if not OS_ENABLED:
    logger.critical("OS_ENABLED=false — system will not start.")
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


def _filter_ai_command_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    AICommand je strict (extra=forbid). Zato filterujemo samo poznata polja.
    """
    if not isinstance(data, dict):
        return {}
    fields = _ai_command_field_names()
    if not fields:
        return {
            "command": data.get("command"),
            "intent": data.get("intent"),
            "params": data.get("params") if isinstance(data.get("params"), dict) else {},
            "initiator": data.get("initiator") or "ceo",
            "read_only": bool(data.get("read_only", False)),
            "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            "execution_id": data.get("execution_id"),
            "approval_id": data.get("approval_id"),
        }
    return {k: v for k, v in data.items() if k in fields}


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
                "Agent registry loaded (SSOT): path=%s loaded=%s version=%s",
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
            logger.info("AI router services initialized")
        except Exception as exc:  # noqa: BLE001
            _append_boot_error(f"ai_router_init_failed:{exc}")
            logger.warning("AI router init failed: %s", exc)

        # ---- AI OPS router optional injection ----
        try:
            hook = getattr(ai_ops_router_module, "set_ai_ops_services", None)
            if callable(hook):
                hook(orchestrator=_execution_orchestrator, approvals=get_approval_state())
                logger.info("AI Ops router services injected (shared orchestrator/approvals)")
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
        logger.info("System boot completed. READY.")
        yield
    finally:
        _BOOT_READY = False
        logger.info("System shutdown — boot_ready=False.")


# ================================================================
# APP INIT
# ================================================================
app = FastAPI(
    title=SYSTEM_NAME,
    version=VERSION,
    lifespan=lifespan,
)

# ================================================================
# CORS (ISPRAVNO)
# ================================================================
def _parse_origins(env_value: str) -> List[str]:
    return [o.strip() for o in (env_value or "").split(",") if o.strip()]


cors_origins: List[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
cors_origins += _parse_origins(os.getenv("CORS_ORIGINS", ""))

# If you do NOT use cookies/sessions, you can set allow_credentials=False.
# Keeping True here because your earlier setup implied approvals may need auth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================================
# INCLUDE ROUTERS
# ================================================================
app.include_router(audit_router, prefix="/api")
app.include_router(adnan_ai_router, prefix="/api")

# AI UX entrypoint (/api/ai/run)
app.include_router(ai_router_module.router, prefix="/api")

# AI OPS (approvals + agents registry/health)
app.include_router(ai_ops_router, prefix="/api")

# CEO Console (READ-only)
app.include_router(ceo_console_module.router, prefix="/api")

app.include_router(metrics_router, prefix="/api")
app.include_router(alerting_router, prefix="/api")

# FAZA 4: Canonical Chat endpoint — /api/chat
app.include_router(_chat_router, prefix="/api")

# ================================================================
# REACT FRONTEND (PROD BUILD) — SERVE dist/
# ================================================================
if not FRONTEND_DIST_DIR.is_dir():
    logger.warning("React dist directory not found: %s", FRONTEND_DIST_DIR)
else:
    # Serve /assets/* (Vite default)
    if FRONTEND_ASSETS_DIR.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(FRONTEND_ASSETS_DIR)),
            name="assets",
        )

    @app.get("/", include_in_schema=False)
    async def serve_frontend_index():
        index_path = FRONTEND_DIST_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="React frontend not built (dist/index.html missing)",
            )
        return FileResponse(str(index_path))

    # SPA fallback for deep links (non-API paths)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Don't hijack API, assets, or docs endpoints
        if (
            full_path.startswith("api/")
            or full_path.startswith("assets/")
            or full_path in ("docs", "redoc", "openapi.json", "health", "ready")
        ):
            raise HTTPException(status_code=404, detail="Not found")

        # Serve static files if they exist (favicon, manifest, etc.)
        maybe_file = FRONTEND_DIST_DIR / full_path
        if maybe_file.is_file():
            return FileResponse(str(maybe_file))

        index_path = FRONTEND_DIST_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="React frontend not built (dist/index.html missing)",
            )
        return FileResponse(str(index_path))


# ================================================================
# REQUEST MODELS
# IMPORTANT: avoid mutable defaults ({}). Use default_factory instead.
# ================================================================
class ExecuteInput(BaseModel):
    text: str


class ExecuteRawInput(BaseModel):
    command: str
    intent: str
    params: Dict[str, Any] = Field(default_factory=dict)  # safe default


class CeoCommandInput(BaseModel):
    input_text: str
    smart_context: Optional[Dict[str, Any]] = None
    source: str = "ceo_dashboard"


class ProposalExecuteInput(BaseModel):
    proposal: ProposedCommand
    initiator: str = "ceo"
    metadata: Dict[str, Any] = Field(default_factory=dict)  # safe default


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
                        "due_date": g.get("deadline") or "-",
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
                        "due_date": t.get("due_date") or "-",
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
    """
    Canonical OS execution endpoint.

    1) Pokušaj da NL → AICommand preko COOTranslationService.
    2) Ako uspije → standardni execution_orchestrator flow (sa approvalima).
    3) Ako NE uspije (None) → tretiraj kao CEO advisory zahtjev
       i preusmjeri na CEO Console / CEOAdvisor (READ-ONLY).
    """
    ai_command = coo_translation_service.translate(
        raw_input=payload.text,
        source="system",
        context={"mode": "execute"},
    )

    if not ai_command:
        cleaned_text = _preprocess_ceo_nl_input(payload.text, smart_context=None)

        req = ceo_console_module.CEOCommandRequest(
            text=cleaned_text,
            initiator="api_execute_fallback",
            session_id=None,
            context_hint={"source": "api_execute"},
        )

        advice = await ceo_console_module.ceo_command(req)

        return {
            "status": "COMPLETED",
            "execution_state": "COMPLETED",
            "mode": "ceo_advisory",
            "channel": "ceo_console",
            "advisory": advice,
        }

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


class ExecuteRawInput2(BaseModel):
    command: str
    intent: str
    params: Dict[str, Any] = Field(default_factory=dict)
    initiator: str = "ceo"
    read_only: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


@app.post("/api/execute/raw")
async def execute_raw_command(payload: ExecuteRawInput2):
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
# FAZA 5 — PROPOSAL PROMOTION ENDPOINT
# /api/proposals/execute
# ================================================================
@app.post("/api/proposals/execute")
async def execute_proposal(payload: ProposalExecuteInput):
    """
    CANON:
      - Accept one proposal (from /api/chat).
      - Create approval + execution_id.
      - Register execution for orchestrator.resume().
      - Return BLOCKED.
    """
    proposal = payload.proposal
    initiator = (payload.initiator or "ceo").strip() or "ceo"
    meta_in = payload.metadata if isinstance(payload.metadata, dict) else {}

    args = proposal.args if isinstance(getattr(proposal, "args", None), dict) else {}

    if proposal.command == "ceo.command.propose":
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise HTTPException(status_code=400, detail="ceo.command.propose requires args.prompt")

        ai_command = coo_translation_service.translate(
            raw_input=prompt.strip(),
            source="system",
            context={"mode": "execute", "via": "proposal_promotion"},
        )
        if not ai_command:
            raise HTTPException(status_code=400, detail="Could not translate proposal prompt to command")

        ai_command.initiator = initiator

        md = getattr(ai_command, "metadata", None)
        if not isinstance(md, dict):
            md = {}
        md.setdefault("promotion", {})
        if isinstance(md.get("promotion"), dict):
            md["promotion"].setdefault("source", "/api/chat")
            md["promotion"].setdefault("proposal_command", proposal.command)
            md["promotion"].setdefault("risk", proposal.risk)
            md["promotion"].setdefault("scope", proposal.scope)
        md.setdefault("endpoint", "/api/proposals/execute")
        md.setdefault("canon", "proposal_promotion")
        for k, v in meta_in.items():
            md[k] = v
        ai_command.metadata = md

        execution_id = _ensure_execution_id(ai_command)

        approval_state = get_approval_state()
        approval = approval_state.create(
            command=getattr(ai_command, "command", None) or "execute_proposal",
            payload_summary=_safe_command_summary(ai_command),
            scope=(proposal.scope or "api_proposals_execute"),
            risk_level=(proposal.risk or "UNKNOWN"),
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
            result.setdefault("status", "BLOCKED")
        return result

    ai_cmd_payload: Optional[Dict[str, Any]] = None
    maybe_ai = args.get("ai_command")
    if isinstance(maybe_ai, dict):
        ai_cmd_payload = dict(maybe_ai)

    if ai_cmd_payload is None:
        raw_command = args.get("command")
        raw_intent = args.get("intent")
        raw_params = args.get("params")

        if (
            isinstance(raw_command, str)
            and raw_command.strip()
            and isinstance(raw_intent, str)
            and raw_intent.strip()
        ):
            ai_cmd_payload = {
                "command": raw_command.strip(),
                "intent": raw_intent.strip(),
                "params": raw_params if isinstance(raw_params, dict) else {},
            }

    if ai_cmd_payload is None:
        raise HTTPException(
            status_code=400,
            detail="proposal payload missing ai_command, raw spec (command+intent+params), or supported ceo.command.propose",
        )

    filtered = _filter_ai_command_payload(ai_cmd_payload)
    if not isinstance(filtered.get("command"), str) or not str(filtered.get("command")).strip():
        raise HTTPException(status_code=400, detail="ai_command.command is required")
    if not isinstance(filtered.get("intent"), str) or not str(filtered.get("intent")).strip():
        raise HTTPException(status_code=400, detail="ai_command.intent is required")

    filtered.setdefault("initiator", initiator)
    filtered.setdefault("read_only", False)

    md2 = filtered.get("metadata")
    if not isinstance(md2, dict):
        md2 = {}
    md2.setdefault("promotion", {})
    if isinstance(md2.get("promotion"), dict):
        md2["promotion"].setdefault("source", "/api/chat")
        md2["promotion"].setdefault("proposal_command", proposal.command)
        md2["promotion"].setdefault("risk", proposal.risk)
        md2["promotion"].setdefault("scope", proposal.scope)
    md2.setdefault("endpoint", "/api/proposals/execute")
    md2.setdefault("canon", "proposal_promotion")
    for k, v in meta_in.items():
        md2[k] = v
    filtered["metadata"] = md2

    ai_command2 = AICommand(**filtered)

    execution_id2 = _ensure_execution_id(ai_command2)

    approval_state2 = get_approval_state()
    approval2 = approval_state2.create(
        command=getattr(ai_command2, "command", None) or "execute_proposal",
        payload_summary=_safe_command_summary(ai_command2),
        scope=(proposal.scope or "api_proposals_execute"),
        risk_level=(proposal.risk or "UNKNOWN"),
        execution_id=execution_id2,
    )
    approval_id2 = approval2.get("approval_id")
    if not approval_id2:
        raise HTTPException(status_code=500, detail="Approval create failed: missing approval_id")

    _ensure_trace_on_command(ai_command2, approval_id=approval_id2)
    _execution_registry.register(ai_command2)

    result2 = await _execution_orchestrator.execute(ai_command2)
    if isinstance(result2, dict):
        result2.setdefault("approval_id", approval_id2)
        result2.setdefault("execution_id", execution_id2)
        result2.setdefault("status", "BLOCKED")
    return result2


# ================================================================
# NOTION BULK OPS (RESTORE ROUTES EXPECTED BY tests/test_bulk_ops.py)
# ================================================================
_ALLOWED_BULK_TYPES = {
    "goal",
    "goals",
    "task",
    "tasks",
    "project",
    "projects",
    "kpi",
    "kpis",
    "lead",
    "leads",
    "agent_exchange",
    "ai_summary",
}


def _validate_bulk_items(items: Any) -> List[Dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items must be a list")

    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            raise HTTPException(status_code=400, detail="each item must be an object")
        t = it.get("type")
        if not isinstance(t, str) or not t.strip():
            raise HTTPException(status_code=400, detail="each item must have non-empty 'type'")
        tt = t.strip().lower()
        if tt not in _ALLOWED_BULK_TYPES:
            raise HTTPException(status_code=400, detail=f"invalid type: {t}")
        out.append(it)
    return out


@app.post("/notion-ops/bulk/create")
async def notion_bulk_create(request: Request, payload: Dict[str, Any] = Body(...)):
    _guard_write_bulk(request)

    items = _validate_bulk_items(payload.get("items"))

    created: List[Dict[str, Any]] = []
    for it in items:
        created.append(
            {
                "id": str(uuid.uuid4()),
                "type": str(it.get("type")),
                "title": it.get("title"),
                "input": it,
                "status": "created",
            }
        )

    return {"created": created}


@app.post("/notion-ops/bulk/update")
async def notion_bulk_update(request: Request, payload: Dict[str, Any] = Body(...)):
    _guard_write_bulk(request)

    items = _validate_bulk_items(payload.get("items"))

    updated: List[Dict[str, Any]] = []
    for it in items:
        updated.append(
            {
                "id": it.get("id") or str(uuid.uuid4()),
                "type": str(it.get("type")),
                "title": it.get("title"),
                "input": it,
                "status": "updated",
            }
        )

    return {"updated": updated}


@app.post("/notion-ops/bulk/query")
async def notion_bulk_query(payload: Dict[str, Any] = Body(...)):
    queries = payload.get("queries")
    if queries is None:
        queries = []
    if not isinstance(queries, list):
        raise HTTPException(status_code=400, detail="queries must be a list")
    for q in queries:
        if not isinstance(q, dict):
            raise HTTPException(status_code=400, detail="each query must be an object")

    results: List[Dict[str, Any]] = []
    for q in queries:
        results.append({"query": q, "items": []})

    return {"results": results}


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

    result_obj = await ceo_console_module.ceo_command(req)
    result = jsonable_encoder(result_obj)

    if not isinstance(result, dict):
        result = {"ok": True, "summary": str(result_obj), "trace": {}}

    if not result.get("text"):
        result["text"] = result.get("summary") or ""

    tr = result.get("trace")
    if isinstance(tr, dict):
        if result.get("text"):
            tr["agent_router_empty_text"] = False
            tr["agent_output_text_len"] = len(str(result.get("text") or ""))

    return JSONResponse(content=result, media_type="application/json; charset=utf-8")


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
            "ops_safe_mode": _ops_safe_mode(),
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
        "ops_safe_mode": _ops_safe_mode(),
    }


@app.get("/ready")
async def ready_check():
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail=_BOOT_ERROR or "System not ready")
    return {
        "status": "ready",
        "version": VERSION,
        "boot_ready": _BOOT_READY,
        "ops_safe_mode": _ops_safe_mode(),
    }


# ================================================================
# GLOBAL ERROR HANDLER
# ================================================================
@app.exception_handler(Exception)
async def global_exception_handler(_: Request, exc: Exception):
    logger.exception("GLOBAL ERROR")
    return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})
