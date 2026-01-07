# gateway/gateway_server.py
# ruff: noqa: E402
# FULL FILE — replace the whole gateway_server.py with this.

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from system_version import ARCH_LOCK, RELEASE_CHANNEL, SYSTEM_NAME, VERSION
from models.canon import PROPOSAL_WRAPPER_INTENT

# ================================================================
# ENV / BOOTSTRAP
# ================================================================
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

    provided = (request.headers.get("X-CEO-Token") or "").strip()

    if not provided:
        auth = (request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()

    if provided != expected:
        raise HTTPException(status_code=403, detail="CEO token required")


def _guard_write_bulk(request: Request) -> None:
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
FRONTEND_DIST_DIR = REPO_ROOT / "gateway" / "frontend" / "dist"


def _agents_registry_path() -> Path:
    p = (os.getenv("AGENTS_JSON_PATH") or "").strip()
    if p:
        return Path(p)

    p2 = (os.getenv("AGENTS_REGISTRY_PATH") or "").strip()
    if p2:
        return Path(p2)

    return REPO_ROOT / "config" / "agents.json"


# ================================================================
# LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("gateway")


# ================================================================
# RUNTIME ENV VALIDATION (SSOT when starting via gateway_server:app)
# ================================================================
REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "NOTION_API_KEY",
    "NOTION_GOALS_DB_ID",
    "NOTION_TASKS_DB_ID",
    "NOTION_PROJECTS_DB_ID",
]

# NOTE:
# - NOTION_OPS_ASSISTANT_ID (LLM ops agent) je sada opcioni / legacy.
# - Canonical CEO Console + Notion Ops Executor (NotionService) NE zavise od njega za boot.


def validate_runtime_env_or_raise() -> None:
    missing = [k for k in REQUIRED_ENV_VARS if not (os.getenv(k) or "").strip()]
    if missing:
        logger.critical("Missing ENV vars: %s", ", ".join(missing))
        raise RuntimeError(f"Missing ENV vars: {', '.join(missing)}")
    logger.info("Environment variables validated.")


# ================================================================
# CORE SERVICES
# ================================================================
from models.ai_command import AICommand
from routers.chat_router import build_chat_router
from services.ai_command_service import AICommandService
from services.approval_state_service import get_approval_state
from services.coo_conversation_service import COOConversationService
from services.coo_translation_service import COOTranslationService
from services.execution_orchestrator import ExecutionOrchestrator
from services.execution_registry import get_execution_registry

# ================================================================
# IDENTITY / MODE / STATE
# ================================================================
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state
from services.identity_loader import load_identity

from services.ceo_console_snapshot_service import CEOConsoleSnapshotService

# ================================================================
# NOTION SERVICE (KANONSKI INIT)
# ================================================================
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.notion_service import NotionService, set_notion_service

set_notion_service(
    NotionService(
        api_key=(
            (os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN") or "").strip()
        ),
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
# AGENT REGISTRY + ROUTER + CHAT
# ================================================================
from services.agent_registry_service import get_agent_registry_service
from services.agent_router_service import AgentRouterService

_agent_registry = get_agent_registry_service()
_agent_router = AgentRouterService(_agent_registry)
_chat_router = build_chat_router(_agent_router)

# ================================================================
# ROUTERS (OTHER)
# ================================================================
from routers.adnan_ai_router import router as adnan_ai_router
from routers.ai_ops_router import ai_ops_router
from routers.alerting_router import router as alerting_router
from routers.audit_router import router as audit_router
from routers.metrics_router import router as metrics_router

import routers.ai_ops_router as ai_ops_router_module
import routers.ai_router as ai_router_module
import routers.ceo_console_router as ceo_console_module

# ================================================================
# APPLICATION BOOTSTRAP
# ================================================================
from services.app_bootstrap import bootstrap_application

# ================================================================
# INITIAL LOAD
# ================================================================
if not OS_ENABLED:
    logger.critical("OS_ENABLED=false â€” system will not start.")
    raise RuntimeError("OS is disabled by configuration.")

identity = load_identity()
mode = load_mode()
state = load_state()

# ================================================================
# EXECUTION ENTRYPOINT (INIT ONLY)
# ================================================================
ai_command_service = AICommandService()
coo_translation_service = COOTranslationService()
coo_conversation_service = COOConversationService()

_execution_registry = get_execution_registry()
_execution_orchestrator = ExecutionOrchestrator()


# ================================================================
# META-COMMANDS MUST NOT ENTER EXECUTION/APPROVAL
# ================================================================
# NOTE:
# - In execution endpoints (/api/execute/raw, /api/proposals/execute) we accept params (and back-compat args),
#   but the stable "proposal contract" shape is:
#     command, args, dry_run, requires_approval, risk, reason, intent?, scope?, payload_summary?
def _ai_command_field_names() -> set[str]:
    model_fields = getattr(AICommand, "model_fields", None)
    if isinstance(model_fields, dict):
        return set(model_fields.keys())
    v1_fields = getattr(AICommand, "__fields__", None)
    if isinstance(v1_fields, dict):
        return set(v1_fields.keys())
    return set()


def _ensure_execution_id(ai_command: AICommand) -> str:
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


def _noop_executable_from_wrapper(
    *,
    wrapper_command: str,
    wrapper_intent: str,
    prompt: str,
    initiator: str,
    metadata: Dict[str, Any],
) -> AICommand:
    md = dict(metadata or {})
    md.setdefault("canon", "execute_raw_wrapper_noop")
    md.setdefault("endpoint", "/api/execute/raw")
    md.setdefault("wrapper", {})
    if isinstance(md.get("wrapper"), dict):
        md["wrapper"].setdefault("command", wrapper_command)
        md["wrapper"].setdefault("intent", wrapper_intent)
        md["wrapper"].setdefault("prompt", (prompt or "").strip())

    return AICommand(
        command="ceo_console.next_step",
        intent="ceo_console.next_step",
        params={"prompt": (prompt or "").strip()},
        initiator=initiator,
        read_only=False,
        metadata=md,
    )


def _unwrap_proposal_wrapper_or_raise(
    *,
    command: str,
    intent: str,
    params: Dict[str, Any],
    initiator: str,
    read_only: bool,
    metadata: Dict[str, Any],
) -> AICommand:
    is_wrapper = (intent == PROPOSAL_WRAPPER_INTENT) or (
        command == PROPOSAL_WRAPPER_INTENT
    )
    if not is_wrapper:
        # Execute/raw is a write-path: it must not execute now, but it must create an approval for a real AICommand.
        return AICommand(
            command=command,
            intent=intent,
            params=params,
            initiator=initiator,
            read_only=read_only,
            metadata=metadata,
        )

    prompt = None
    if isinstance(params, dict):
        prompt = params.get("prompt")

    if not isinstance(prompt, str) or not prompt.strip():
        raise HTTPException(
            status_code=400,
            detail="ceo.command.propose cannot enter execution. Missing params.prompt for unwrap/translation.",
        )

    ai_command = None
    try:
        ai_command = coo_translation_service.translate(
            raw_input=prompt.strip(),
            source="system",
            context={"mode": "execute", "via": "execute_raw_unwrap"},
        )
    except Exception:
        ai_command = None

    if ai_command and getattr(ai_command, "intent", None) == PROPOSAL_WRAPPER_INTENT:
        ai_command = None

    if not ai_command:
        return _noop_executable_from_wrapper(
            wrapper_command=command,
            wrapper_intent=intent,
            prompt=prompt,
            initiator=initiator,
            metadata=metadata,
        )

    ai_command.initiator = initiator
    ai_command.read_only = False

    md = getattr(ai_command, "metadata", None)
    if not isinstance(md, dict):
        md = {}
    md.setdefault("canon", "execute_raw_unwrap")
    md.setdefault("endpoint", "/api/execute/raw")
    md.setdefault("wrapper", {})
    if isinstance(md.get("wrapper"), dict):
        md["wrapper"].setdefault("command", command)
        md["wrapper"].setdefault("intent", intent)
        md["wrapper"].setdefault("prompt", prompt.strip())

    if isinstance(metadata, dict):
        for k, v in metadata.items():
            md[k] = v
    ai_command.metadata = md

    return ai_command


# ================================================================
# LIFESPAN
# ================================================================
@asynccontextmanager
async def lifespan(_: FastAPI):
    global _BOOT_READY, _BOOT_ERROR

    _BOOT_READY = False
    _BOOT_ERROR = None

    try:
        try:
            validate_runtime_env_or_raise()
        except Exception as exc:  # noqa: BLE001
            _append_boot_error(f"env_invalid:{exc}")
            logger.critical("Boot aborted due to invalid env: %s", exc)
            raise

        bootstrap_application()

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

        try:
            hook = getattr(ai_ops_router_module, "set_ai_ops_services", None)
            if callable(hook):
                hook(
                    orchestrator=_execution_orchestrator,
                    approvals=get_approval_state(),
                )
                logger.info(
                    "AI Ops router services injected (shared orchestrator/approvals)"
                )
        except Exception as exc:  # noqa: BLE001
            _append_boot_error(f"ai_ops_injection_failed:{exc}")
            logger.warning("AI Ops services injection failed: %s", exc)

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
        try:
            from services.notion_service import get_notion_service

            ns = get_notion_service()
            close_fn = getattr(ns, "aclose", None)
            if callable(close_fn):
                await close_fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("NotionService shutdown close failed: %s", exc)

        _BOOT_READY = False
        logger.info("System shutdown â€” boot_ready=False.")


# ================================================================
# APP INIT
# ================================================================
app = FastAPI(
    title=SYSTEM_NAME,
    version=VERSION,
    lifespan=lifespan,
)


# ================================================================
# REQUEST TRACE
# ================================================================
@app.middleware("http")
async def request_trace_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.req_id = req_id
    try:
        resp = await call_next(request)
        resp.headers["X-Request-ID"] = req_id
        return resp
    except Exception:
        logger.exception("REQ_FAIL req_id=%s path=%s", req_id, request.url.path)
        raise


# ================================================================
# CORS
# ================================================================
def _parse_origins(env_value: str) -> List[str]:
    return [o.strip() for o in (env_value or "").split(",") if o.strip()]


cors_origins: List[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
cors_origins += _parse_origins(os.getenv("CORS_ORIGINS", ""))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================================================================
# REQUEST MODELS
# ================================================================
class ExecuteInput(BaseModel):
    text: str


class ExecuteRawInput(BaseModel):
    command: str
    intent: str
    params: Dict[str, Any] = Field(default_factory=dict)


class CeoCommandInput(BaseModel):
    input_text: str
    smart_context: Optional[Dict[str, Any]] = None
    source: str = "ceo_dashboard"


class ProposalExecuteInput(BaseModel):
    proposal: Any
    initiator: str = "ceo"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecuteRawInput2(BaseModel):
    command: str
    intent: str
    params: Dict[str, Any] = Field(default_factory=dict)
    initiator: str = "ceo"
    read_only: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ================================================================
# HELPERS
# ================================================================
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
        r"^(kreiraj|napravi|create)\s+cilj[a]?(?:\s+u\s+notionu)?\s*[:\-]?\s*",
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
                        "name": g.get("name") or g.get("title") or "(bez naziva)",
                        "status": g.get("status") or "-",
                        "priority": g.get("priority") or "-",
                        "due_date": g.get("deadline")
                        or g.get("due_date")
                        or g.get("due")
                        or "-",
                    }
                )

        if isinstance(tasks, list):
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                tasks_summary.append(
                    {
                        "title": t.get("title") or t.get("name") or "(bez naziva)",
                        "status": t.get("status") or "-",
                        "priority": t.get("priority") or "-",
                        "due_date": t.get("due_date")
                        or t.get("deadline")
                        or t.get("due")
                        or "-",
                    }
                )
    except Exception:
        pass

    return {"goals_summary": goals_summary, "tasks_summary": tasks_summary}


def _ensure_list(x: Any) -> List[Any]:
    return x if isinstance(x, list) else []


def _ensure_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _proposal_wrapper_dict(*, prompt: str, source: str) -> Dict[str, Any]:
    """
    Stable proposal contract shape (no initiator/read_only/metadata inside proposed_commands).
    Keep 'args' as SSOT field for read/propose surfaces.
    """
    safe_prompt = (prompt or "").strip() or "noop"
    return {
        "command": PROPOSAL_WRAPPER_INTENT,
        "args": {"prompt": safe_prompt},
        "intent": None,
        "reason": "Notion write intent ide kroz approval pipeline; predlaĹľem komandu za promotion/execute.",
        "dry_run": True,
        "requires_approval": True,
        "risk": "LOW",
        "scope": "api_execute_raw",
        "payload_summary": {
            "endpoint": "/api/execute/raw",
            "canon": "CEO_CONSOLE_EXECUTION_FLOW",
            "source": source,
        },
    }


def _normalize_gateway_proposed_commands(pcs: Any) -> List[Dict[str, Any]]:
    """
    Normalize proposed_commands to list[dict] using SSOT field-names (args).
    - Accept dict items
    - Accept pydantic BaseModel items via model_dump(by_alias=False)
    - Drop invalid items
    """
    items = _ensure_list(pcs)
    out: List[Dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            out.append(it)
            continue
        if hasattr(it, "model_dump"):
            try:
                d = it.model_dump(by_alias=False)  # type: ignore[attr-defined]
                if isinstance(d, dict):
                    out.append(d)
                    continue
            except Exception:
                pass
        if hasattr(it, "dict"):
            try:
                d = it.dict()  # type: ignore[attr-defined]
                if isinstance(d, dict):
                    out.append(d)
                    continue
            except Exception:
                pass
    return out


def _inject_fallback_proposed_commands(result: Dict[str, Any], *, prompt: str) -> None:
    """
    Ensure proposed_commands exists and conforms to the stable proposal contract.

    IMPORTANT:
    - proposed_commands must be a list of *proposal contract* objects
      (command/args/dry_run/requires_approval/risk/reason/intent?/scope?/payload_summary?)
    - Do NOT embed execution payload fields (initiator/read_only/metadata) inside proposed_commands.
    """
    pcs = result.get("proposed_commands")
    pcs_list = _normalize_gateway_proposed_commands(pcs)

    if len(pcs_list) > 0:
        result["proposed_commands"] = pcs_list
        tr0 = _ensure_dict(result.get("trace"))
        tr0.setdefault("fallback_proposed_commands", False)
        tr0.setdefault("router_version", "gateway-proposed-commands-normalize-v1")
        result["trace"] = tr0
        return

    # Inject a canonical wrapper proposal
    result["proposed_commands"] = [
        _proposal_wrapper_dict(prompt=(prompt or "").strip(), source="ceo_console")
    ]

    tr = _ensure_dict(result.get("trace"))
    tr["fallback_proposed_commands"] = True
    tr["router_version"] = "gateway-fallback-proposed-commands-v3-stable-contract"
    result["trace"] = tr


def _normalize_execute_raw_payload_dict(body: Dict[str, Any]) -> ExecuteRawInput2:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    cmd = body.get("command") or body.get("command_type") or body.get("type") or ""
    if not isinstance(cmd, str) or not cmd.strip():
        raise HTTPException(status_code=422, detail="Field 'command' is required")
    cmd = cmd.strip()

    intent_val = body.get("intent")
    if isinstance(intent_val, str) and intent_val.strip():
        intent = intent_val.strip()
    else:
        intent = cmd

    params = body.get("params")
    if not isinstance(params, dict):
        params = {}

    # Back-compat: accept args for wrapper prompt
    if intent == PROPOSAL_WRAPPER_INTENT and "prompt" not in params:
        args = body.get("args")
        if isinstance(args, dict):
            prompt = args.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                params["prompt"] = prompt.strip()

    initiator = body.get("initiator")
    if not isinstance(initiator, str) or not initiator.strip():
        initiator = "ceo"
    else:
        initiator = initiator.strip()

    read_only = bool(body.get("read_only") or False)

    metadata = body.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    payload_summary = body.get("payload_summary")
    if isinstance(payload_summary, dict):
        merged = dict(payload_summary)
        merged.update(metadata)
        metadata = merged

    metadata.setdefault("canon", "CEO_CONSOLE_EXECUTION_FLOW")
    metadata.setdefault("endpoint", "/api/execute/raw")
    metadata.setdefault("source", metadata.get("source") or "ceo_console")

    return ExecuteRawInput2(
        command=cmd,
        intent=intent,
        params=params,
        initiator=initiator,
        read_only=read_only,
        metadata=metadata,
    )


# ================================================================
# /api/execute â€” EXECUTION PATH (NL INPUT)
# ================================================================
@app.post("/api/execute")
async def execute_command(payload: ExecuteInput):
    cleaned_text = _preprocess_ceo_nl_input(payload.text, smart_context=None)

    ai_command = coo_translation_service.translate(
        raw_input=cleaned_text,
        source="system",
        context={"mode": "execute"},
    )

    if not ai_command:
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
        raise HTTPException(
            status_code=500, detail="Approval create failed: missing approval_id"
        )

    _ensure_trace_on_command(ai_command, approval_id=approval_id)

    _execution_orchestrator.registry.register(ai_command)
    _execution_registry.register(ai_command)

    result = await _execution_orchestrator.execute(ai_command)

    if isinstance(result, dict):
        result.setdefault("approval_id", approval_id)
        result.setdefault("execution_id", execution_id)

    return result


@app.post("/api/execute/raw")
async def execute_raw_command(payload: Dict[str, Any] = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    normalized = _normalize_execute_raw_payload_dict(payload)

    ai_command = _unwrap_proposal_wrapper_or_raise(
        command=normalized.command,
        intent=normalized.intent,
        params=normalized.params if isinstance(normalized.params, dict) else {},
        initiator=normalized.initiator,
        read_only=normalized.read_only,
        metadata=normalized.metadata if isinstance(normalized.metadata, dict) else {},
    )

    execution_id = _ensure_execution_id(ai_command)

    approval_state = get_approval_state()
    approval = approval_state.create(
        command=getattr(ai_command, "command", None) or "execute_raw",
        payload_summary=_safe_command_summary(ai_command),
        scope=(payload.get("scope") or "api_execute_raw"),
        risk_level=(payload.get("risk") or "unknown"),
        execution_id=execution_id,
    )
    approval_id = approval.get("approval_id")
    if not approval_id:
        raise HTTPException(
            status_code=500, detail="Approval create failed: missing approval_id"
        )

    _ensure_trace_on_command(ai_command, approval_id=approval_id)

    _execution_orchestrator.registry.register(ai_command)
    _execution_registry.register(ai_command)

    return {
        "status": "BLOCKED",
        "execution_state": "BLOCKED",
        "approval_id": approval_id,
        "execution_id": execution_id,
        "command": (
            ai_command.model_dump()
            if hasattr(ai_command, "model_dump")
            else _to_serializable(ai_command)
        ),
    }


# ================================================================
# /api/proposals/execute
# ================================================================
@app.post("/api/proposals/execute")
async def execute_proposal(payload: ProposalExecuteInput):
    proposal = payload.proposal
    initiator = (payload.initiator or "ceo").strip() or "ceo"
    meta_in = payload.metadata if isinstance(payload.metadata, dict) else {}

    proposal_cmd: Optional[str] = None
    proposal_intent: Optional[str] = None
    proposal_params: Dict[str, Any] = {}
    proposal_meta: Dict[str, Any] = {}

    if isinstance(proposal, dict):
        proposal_cmd = (
            proposal.get("command")
            or proposal.get("command_type")
            or proposal.get("type")
        )
        proposal_intent = proposal.get("intent") or proposal_cmd

        p_params = proposal.get("params")
        if isinstance(p_params, dict):
            proposal_params = dict(p_params)

        if not proposal_params:
            p_args = proposal.get("args")
            if isinstance(p_args, dict):
                proposal_params = dict(p_args)
        if not proposal_params:
            p_payload = proposal.get("payload")
            if isinstance(p_payload, dict):
                proposal_params = dict(p_payload)

        p_md = proposal.get("metadata")
        if isinstance(p_md, dict):
            proposal_meta = dict(p_md)

        proposal_scope = proposal.get("scope")
        proposal_risk = proposal.get("risk") or proposal.get("risk_hint")
    else:
        proposal_cmd = (
            getattr(proposal, "command", None)
            or getattr(proposal, "command_type", None)
            or getattr(proposal, "type", None)
        )
        proposal_intent = getattr(proposal, "intent", None) or proposal_cmd

        p2 = getattr(proposal, "params", None)
        if isinstance(p2, dict):
            proposal_params = dict(p2)
        if not proposal_params:
            a2 = getattr(proposal, "args", None)
            if isinstance(a2, dict):
                proposal_params = dict(a2)
        if not proposal_params:
            pl2 = getattr(proposal, "payload", None)
            if isinstance(pl2, dict):
                proposal_params = dict(pl2)

        m2 = getattr(proposal, "metadata", None)
        if isinstance(m2, dict):
            proposal_meta = dict(m2)

        proposal_scope = getattr(proposal, "scope", None)
        proposal_risk = getattr(proposal, "risk", None) or getattr(
            proposal, "risk_hint", None
        )

    proposal_cmd = (proposal_cmd or "").strip() or None
    proposal_intent = (proposal_intent or "").strip() or None

    if not proposal_cmd or not proposal_intent:
        raise HTTPException(
            status_code=400, detail="Invalid proposal: missing command/intent"
        )

    if (
        proposal_cmd != PROPOSAL_WRAPPER_INTENT
        and proposal_intent != PROPOSAL_WRAPPER_INTENT
    ):
        raise HTTPException(
            status_code=400,
            detail="Unsupported proposal payload (only ceo.command.propose)",
        )

    merged_md: Dict[str, Any] = {}
    if isinstance(proposal_meta, dict):
        merged_md.update(proposal_meta)
    if isinstance(meta_in, dict):
        merged_md.update(meta_in)

    ai_command = _unwrap_proposal_wrapper_or_raise(
        command=proposal_cmd,
        intent=proposal_intent,
        params=proposal_params if isinstance(proposal_params, dict) else {},
        initiator=initiator,
        read_only=False,
        metadata=merged_md,
    )

    md = getattr(ai_command, "metadata", None)
    if not isinstance(md, dict):
        md = {}
    md.setdefault("promotion", {})
    if isinstance(md.get("promotion"), dict):
        md["promotion"].setdefault("source", "/api/proposals/execute")
        md["promotion"].setdefault("proposal_command", proposal_cmd)
        md["promotion"].setdefault("proposal_intent", proposal_intent)
        md["promotion"].setdefault("risk", proposal_risk)
        md["promotion"].setdefault("scope", proposal_scope)
    md.setdefault("endpoint", "/api/proposals/execute")
    md.setdefault("canon", "proposal_promotion_v2_execute_raw_unwrap")
    ai_command.metadata = md

    execution_id = _ensure_execution_id(ai_command)

    approval_state = get_approval_state()
    approval = approval_state.create(
        command=getattr(ai_command, "command", None) or "execute_proposal",
        payload_summary=_safe_command_summary(ai_command),
        scope=(proposal_scope or "api_proposals_execute"),
        risk_level=(proposal_risk or "UNKNOWN"),
        execution_id=execution_id,
    )
    approval_id = approval.get("approval_id")
    if not approval_id:
        raise HTTPException(
            status_code=500, detail="Approval create failed: missing approval_id"
        )

    _ensure_trace_on_command(ai_command, approval_id=approval_id)
    _execution_orchestrator.registry.register(ai_command)
    _execution_registry.register(ai_command)

    result = await _execution_orchestrator.execute(ai_command)
    if isinstance(result, dict):
        result.setdefault("approval_id", approval_id)
        result.setdefault("execution_id", execution_id)
        result.setdefault("status", "BLOCKED")
    return result


# ================================================================
# NOTION OPS â€” LIST DATABASES (READ ONLY)
# ================================================================
@app.get("/api/notion-ops/databases")
@app.get("/notion-ops/databases")
async def notion_ops_list_databases():
    from services.notion_service import get_notion_service

    ns = get_notion_service()

    dbs: Dict[str, str] = {}
    if isinstance(getattr(ns, "db_ids", None), dict):
        for k, v in ns.db_ids.items():
            if isinstance(k, str) and isinstance(v, str):
                kk = k.strip()
                vv = v.strip()
                if kk and vv:
                    dbs[kk] = vv

    return {
        "ok": True,
        "read_only": True,
        "ops_safe_mode": _ops_safe_mode(),
        "databases": dbs,
    }


@app.get("/databases")
async def databases_alias():
    return await notion_ops_list_databases()


@app.get("/api/databases")
async def databases_alias_api():
    return await notion_ops_list_databases()


# ================================================================
# NOTION BULK OPS
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
            raise HTTPException(
                status_code=400, detail="each item must have non-empty 'type'"
            )
        tt = t.strip().lower()
        if tt not in _ALLOWED_BULK_TYPES:
            raise HTTPException(status_code=400, detail=f"invalid type: {t}")
        out.append(it)
    return out


@app.post("/api/notion-ops/bulk/create")
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


@app.post("/api/notion-ops/bulk/update")
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


def _normalize_notion_query_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizuje query dio. Namjerno ignoriĹˇe db_key/database_id.
    PodrĹľava:
      - {"query": {...}}
      - ili flat: {"filter":..., "sorts":..., "start_cursor":..., "page_size":...}
    """
    q = payload.get("query")
    if isinstance(q, dict):
        return dict(q)

    out: Dict[str, Any] = {}
    if isinstance(payload.get("filter"), dict):
        out["filter"] = payload["filter"]
    if isinstance(payload.get("sorts"), list):
        out["sorts"] = payload["sorts"]
    if isinstance(payload.get("start_cursor"), str) and payload["start_cursor"].strip():
        out["start_cursor"] = payload["start_cursor"].strip()
    if isinstance(payload.get("page_size"), int):
        out["page_size"] = int(payload["page_size"])
    return out


def _looks_like_uuid(s: str) -> bool:
    try:
        uuid.UUID((s or "").strip())
        return True
    except Exception:
        return False


def _resolve_db_id_from_service(notion_service: Any, db_key: str) -> str:
    key = (db_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="db_key is required")

    if _looks_like_uuid(key):
        return key

    lk = key.lower()

    db_ids = getattr(notion_service, "db_ids", None)
    if isinstance(db_ids, dict):
        for candidate in (lk, lk.rstrip("s"), lk + "s"):
            v = db_ids.get(candidate)
            if isinstance(v, str) and v.strip():
                return v.strip()

    for candidate in (lk, lk.rstrip("s"), lk + "s"):
        if candidate == "goals":
            v = getattr(notion_service, "goals_db_id", None) or getattr(
                notion_service, "_goals_db_id", None
            )
            if isinstance(v, str) and v.strip():
                return v.strip()
        if candidate == "tasks":
            v = getattr(notion_service, "tasks_db_id", None) or getattr(
                notion_service, "_tasks_db_id", None
            )
            if isinstance(v, str) and v.strip():
                return v.strip()
        if candidate == "projects":
            v = getattr(notion_service, "projects_db_id", None) or getattr(
                notion_service, "_projects_db_id", None
            )
            if isinstance(v, str) and v.strip():
                return v.strip()

    raise HTTPException(status_code=400, detail=f"Unknown db_key: {db_key}")


def _extract_db_key_or_database_id(d: Dict[str, Any]) -> Optional[str]:
    """
    Back-compat: prihvati i db_key i database_id.
    """
    v = d.get("db_key")
    if isinstance(v, str) and v.strip():
        return v.strip()
    v2 = d.get("database_id")
    if isinstance(v2, str) and v2.strip():
        return v2.strip()
    return None


async def _call_maybe_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    out = fn(*args, **kwargs)
    if asyncio.iscoroutine(out):
        return await out
    return out


async def _query_notion_database(db_key: str, query: Dict[str, Any]) -> Dict[str, Any]:
    from services.notion_service import get_notion_service

    notion_service = get_notion_service()

    for name in ("query_database", "database_query", "query_db", "query"):
        fn = getattr(notion_service, name, None)
        if callable(fn):
            try:
                res = await _call_maybe_async(fn, db_key=db_key, query=query)
                if isinstance(res, dict):
                    return res
            except TypeError:
                pass
            try:
                res = await _call_maybe_async(fn, db_key=db_key, **query)
                if isinstance(res, dict):
                    return res
            except TypeError:
                pass
            try:
                res = await _call_maybe_async(fn, db_key, query)
                if isinstance(res, dict):
                    return res
            except TypeError:
                pass

    try:
        from notion_client import Client  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=(
                "Notion query failed: NotionService has no query method and notion_client "
                f"is unavailable: {exc}"
            ),
        ) from exc

    api_key = (
        getattr(notion_service, "api_key", None)
        or getattr(notion_service, "_api_key", None)
        or (os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN") or "").strip()
    )
    if not isinstance(api_key, str) or not api_key.strip():
        raise HTTPException(
            status_code=500, detail="NOTION_API_KEY/NOTION_TOKEN not set"
        )

    db_id = _resolve_db_id_from_service(notion_service, db_key)
    client = Client(auth=api_key.strip())

    try:
        res = await asyncio.to_thread(
            lambda: client.databases.query(database_id=db_id, **(query or {}))
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Notion databases.query failed: {exc}"
        ) from exc

    if not isinstance(res, dict):
        return {
            "results": [],
            "has_more": False,
            "next_cursor": None,
            "database_id": db_id,
        }

    res.setdefault("database_id", db_id)
    return res


@app.post("/api/notion-ops/bulk/query")
@app.post("/notion-ops/bulk/query")
async def notion_bulk_query(payload: Any = Body(None)):
    """
    Back/forward compatible bulk query endpoint.

    Accepts:
      1) Empty / null body -> 200 {"results":[]}
      2) Single query via {db_key|database_id, filter/sorts/page_size...} -> 200 {"results":[...]}
      3) Multi query via {queries:[{db_key|database_id,...}, ...]} -> 200 {"results":[...]}
    """
    if payload is None:
        return {"results": []}

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    # --- SINGLE: db_key or database_id on top-level ---
    top_db_key = _extract_db_key_or_database_id(payload)
    if isinstance(top_db_key, str) and top_db_key.strip():
        q = _normalize_notion_query_payload(payload)
        res = await _query_notion_database(top_db_key.strip(), q)
        items = res.get("results") if isinstance(res.get("results"), list) else []
        return {
            "results": [
                {
                    "query": {"db_key": top_db_key.strip(), **q},
                    "db_key": top_db_key.strip(),
                    "items": items,
                    "notion": res,
                    "response": res,  # legacy alias
                }
            ]
        }

    # --- MULTI: queries list (can be empty) ---
    queries = payload.get("queries")
    if queries is None:
        queries = []
    if not isinstance(queries, list):
        raise HTTPException(status_code=400, detail="queries must be a list")

    if len(queries) == 0:
        # This is exactly what tests expect: 200, not 422
        return {"results": []}

    out: List[Dict[str, Any]] = []
    for q0 in queries:
        if not isinstance(q0, dict):
            raise HTTPException(status_code=400, detail="each query must be an object")

        db_key = _extract_db_key_or_database_id(q0)
        if not isinstance(db_key, str) or not db_key.strip():
            out.append(
                {
                    "query": q0,
                    "db_key": None,
                    "items": [],
                    "notion": {"results": [], "has_more": False, "next_cursor": None},
                    "response": {"results": [], "has_more": False, "next_cursor": None},
                }
            )
            continue

        nq = _normalize_notion_query_payload(q0)
        res = await _query_notion_database(db_key.strip(), nq)
        items = res.get("results") if isinstance(res.get("results"), list) else []
        out.append(
            {
                "query": {"db_key": db_key.strip(), **nq},
                "db_key": db_key.strip(),
                "items": items,
                "notion": res,
                "response": res,  # legacy alias
            }
        )

    return {"results": out}


# ================================================================
# LEGACY CEO COMMAND ENDPOINTS (READ-ONLY WRAPPERS)
# ================================================================
def _extract_text_from_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    for key in ("input_text", "text", "message", "prompt"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("input_text", "text", "message", "prompt"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()

    return ""


def _extract_smart_context(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None

    def _pick(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sc = (
            d.get("smart_context")
            or d.get("context")
            or d.get("context_hint")
            or d.get("ui_context_hint")
        )
        return sc if isinstance(sc, dict) else None

    sc = _pick(payload)
    if sc is not None:
        return sc

    data = payload.get("data")
    if isinstance(data, dict):
        return _pick(data)

    return None


def _extract_source(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "ceo_dashboard"
    s = payload.get("source") or payload.get("initiator")
    if isinstance(s, str) and s.strip():
        return s.strip()
    return "ceo_dashboard"


async def _ceo_command_core(payload_dict: Dict[str, Any]) -> JSONResponse:
    raw_text = _extract_text_from_payload(payload_dict)
    smart_context = _extract_smart_context(payload_dict)
    source = _extract_source(payload_dict)

    cleaned_text = _preprocess_ceo_nl_input(raw_text, smart_context)

    if not isinstance(cleaned_text, str) or not cleaned_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Missing text. Provide one of: input_text | text | message | prompt (optionally under data).",
        )

    session_id = payload_dict.get("session_id")
    if session_id is None and isinstance(payload_dict.get("data"), dict):
        session_id = payload_dict["data"].get("session_id")

    req = ceo_console_module.CEOCommandRequest(
        text=cleaned_text.strip(),
        initiator=source,
        session_id=session_id,
        context_hint=smart_context,
        read_only=True,
        require_approval=False,
    )

    result_obj = await ceo_console_module.ceo_command(req)

    # CRITICAL: keep SSOT field-names (args) for proposed_commands on read-only surfaces.
    try:
        if hasattr(result_obj, "model_dump"):
            result = result_obj.model_dump(by_alias=False)  # type: ignore[attr-defined]
        else:
            result = jsonable_encoder(result_obj, by_alias=False)
    except Exception:
        result = jsonable_encoder(result_obj)

    if not isinstance(result, dict):
        result = {"ok": True, "summary": str(result_obj), "trace": {}}

    result["read_only"] = True

    if not result.get("text"):
        result["text"] = result.get("summary") or ""

    tr = result.get("trace")
    if isinstance(tr, dict):
        tr["normalized_input_text"] = cleaned_text.strip()
        tr["normalized_input_source"] = source
        tr["normalized_input_has_smart_context"] = bool(smart_context)
        tr["normalized_input_session_id_present"] = bool(session_id)
        if result.get("text"):
            tr["agent_router_empty_text"] = False
            tr["agent_output_text_len"] = len(str(result.get("text") or ""))

    _inject_fallback_proposed_commands(result, prompt=cleaned_text.strip())

    return JSONResponse(content=result, media_type="application/json; charset=utf-8")


@app.post("/api/ceo/command")
async def ceo_dashboard_command_api(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


@app.post("/api/ceo-console/command")
async def ceo_console_command_api(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


@app.post("/api/ceo-console/command/internal")
async def ceo_console_command_api_internal(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


@app.post("/ceo/command")
async def ceo_dashboard_command_public(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


@app.post("/ceo-console/command")
async def ceo_console_command_public(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


@app.post("/ceo-console/command/internal")
async def ceo_console_command_public_internal(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


# ================================================================
# CEO CONSOLE STATUS
# ================================================================
@app.get("/api/ceo-console/status")
async def ceo_console_status_api():
    ops_safe = _ops_safe_mode()
    return {
        "ok": True,
        "read_only": True,
        "system": SYSTEM_NAME,
        "version": VERSION,
        "boot_ready": _BOOT_READY,
        "boot_error": _BOOT_ERROR,
        "ops_safe_mode": ops_safe,
        "canon": {
            "chat_is_read_only": True,
            "no_side_effects": True,
            "ops_safe_mode": ops_safe,
            "boot_ready": _BOOT_READY,
        },
    }


@app.get("/ceo-console/status")
async def ceo_console_status_public():
    return await ceo_console_status_api()


# ================================================================
# CEO CONSOLE SNAPSHOT
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
# INCLUDE ROUTERS
# ================================================================
app.include_router(audit_router, prefix="/api")
app.include_router(adnan_ai_router, prefix="/api")
app.include_router(ai_router_module.router, prefix="/api")
app.include_router(ai_ops_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(alerting_router, prefix="/api")
app.include_router(_chat_router, prefix="/api")  # /api/chat
app.include_router(_chat_router, prefix="")  # /chat alias
app.include_router(ceo_console_module.router, prefix="/api/internal")


# ================================================================
# GLOBAL ERROR HANDLER
# ================================================================
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException):
    detail = getattr(exc, "detail", None)

    content: Dict[str, Any] = {"detail": detail}
    content["status"] = "error"
    content["message"] = detail

    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("GLOBAL ERROR")
    req_id = getattr(getattr(request, "state", None), "req_id", None)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc), "req_id": req_id},
    )


# ================================================================
# REACT FRONTEND (PROD BUILD) â€” SERVE dist/
# ================================================================
if not FRONTEND_DIST_DIR.is_dir():
    logger.warning("React dist directory not found: %s", FRONTEND_DIST_DIR)
else:

    @app.head("/", include_in_schema=False)
    async def head_root():
        return Response(status_code=200)

    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIST_DIR), html=True),
        name="frontend",
    )
