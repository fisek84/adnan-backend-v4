# gateway/gateway_server.py
# ruff: noqa: E402
# FULL FILE — zamijeni cijeli gateway_server.py ovim.

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
    logger.critical("OS_ENABLED=false — system will not start.")
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
PROPOSAL_WRAPPER_INTENT = "ceo.command.propose"


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


def _filter_ai_command_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    fields = _ai_command_field_names()
    if not fields:
        return {
            "command": data.get("command"),
            "intent": data.get("intent"),
            "params": data.get("params")
            if isinstance(data.get("params"), dict)
            else {},
            "initiator": data.get("initiator") or "ceo",
            "read_only": bool(data.get("read_only", False)),
            "metadata": data.get("metadata")
            if isinstance(data.get("metadata"), dict)
            else {},
            "execution_id": data.get("execution_id"),
            "approval_id": data.get("approval_id"),
        }
    return {k: v for k, v in data.items() if k in fields}


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

    # IMPORTANT FIX: allow "Kreiraj cilj u Notionu:" prefix
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


def _inject_fallback_proposed_commands(result: Dict[str, Any], *, prompt: str) -> None:
    pcs = result.get("proposed_commands")
    pcs_list = _ensure_list(pcs)

    if len(pcs_list) > 0:
        result["proposed_commands"] = pcs_list
        tr0 = _ensure_dict(result.get("trace"))
        tr0.setdefault("fallback_proposed_commands", False)
        tr0.setdefault("router_version", "gateway-fallback-proposed-commands-v1")
        result["trace"] = tr0
        return

    safe_prompt = (prompt or "").strip() or "noop"

    result["proposed_commands"] = [
        {
            "command": "ceo.command.propose",
            "args": {"prompt": safe_prompt},
            "status": "BLOCKED",
            "requires_approval": True,
            "scope": "ceo_console",
            "risk": "LOW",
            "cost_hint": "Low",
            "risk_hint": "Low",
            "command_type": "ceo.command.propose",
            "payload": {"prompt": safe_prompt},
            "required_approval": True,
        }
    ]

    tr = _ensure_dict(result.get("trace"))
    tr["fallback_proposed_commands"] = True
    tr["router_version"] = "gateway-fallback-proposed-commands-v1"
    result["trace"] = tr


# ================================================================
# /api/execute — EXECUTION PATH (NL INPUT)
# ================================================================
@app.post("/api/execute")
async def execute_command(payload: ExecuteInput):
    # FIX: preprocess before translate to avoid polluting title with "u Notionu:" etc.
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
    ai_command = _unwrap_proposal_wrapper_or_raise(
        command=payload.command,
        intent=payload.intent,
        params=payload.params if isinstance(payload.params, dict) else {},
        initiator=payload.initiator,
        read_only=payload.read_only,
        metadata=payload.metadata if isinstance(payload.metadata, dict) else {},
    )

    execution_id = _ensure_execution_id(ai_command)

    approval_state = get_approval_state()
    approval = approval_state.create(
        command=getattr(ai_command, "command", None) or "execute_raw",
        payload_summary=_safe_command_summary(ai_command),
        scope="api_execute_raw",
        risk_level="unknown",
        execution_id=execution_id,
    )
    approval_id = approval.get("approval_id")
    if not approval_id:
        raise HTTPException(
            status_code=500, detail="Approval create failed: missing approval_id"
        )

    _ensure_trace_on_command(ai_command, approval_id=approval_id)

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

    # leave as-is (your current file content)
    if isinstance(proposal, dict):
        proposal_cmd = proposal.get("command")
        proposal_args = (
            proposal.get("args") if isinstance(proposal.get("args"), dict) else {}
        )
        proposal_scope = proposal.get("scope")
        proposal_risk = proposal.get("risk")
    else:
        proposal_cmd = getattr(proposal, "command", None)
        proposal_args = (
            getattr(proposal, "args", {})
            if isinstance(getattr(proposal, "args", None), dict)
            else {}
        )
        proposal_scope = getattr(proposal, "scope", None)
        proposal_risk = getattr(proposal, "risk", None)

    args = proposal_args

    if proposal_cmd == "ceo.command.propose":
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise HTTPException(
                status_code=400, detail="ceo.command.propose requires args.prompt"
            )

        ai_command = coo_translation_service.translate(
            raw_input=prompt.strip(),
            source="system",
            context={"mode": "execute", "via": "proposal_promotion"},
        )
        if not ai_command:
            raise HTTPException(
                status_code=400, detail="Could not translate proposal prompt to command"
            )

        ai_command.initiator = initiator

        md = getattr(ai_command, "metadata", None)
        if not isinstance(md, dict):
            md = {}
        md.setdefault("promotion", {})
        if isinstance(md.get("promotion"), dict):
            md["promotion"].setdefault("source", "/api/chat")
            md["promotion"].setdefault("proposal_command", proposal_cmd)
            md["promotion"].setdefault("risk", proposal_risk)
            md["promotion"].setdefault("scope", proposal_scope)
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
        _execution_registry.register(ai_command)

        result = await _execution_orchestrator.execute(ai_command)
        if isinstance(result, dict):
            result.setdefault("approval_id", approval_id)
            result.setdefault("execution_id", execution_id)
            result.setdefault("status", "BLOCKED")
        return result

    raise HTTPException(status_code=400, detail="Unsupported proposal payload")


# ================================================================
# NOTION OPS (READ: list databases)  ✅ FIX: add /api + non-/api
# ================================================================
@app.get("/api/notion-ops/databases")
@app.get("/notion-ops/databases")
async def notion_ops_databases():
    """
    Frontend expects:
      { ok: true, read_only: true, databases: { <db_key>: <database_id>, ... } }
    """
    dbs: Dict[str, str] = {}
    for key, env in [
        ("goals", "NOTION_GOALS_DB_ID"),
        ("tasks", "NOTION_TASKS_DB_ID"),
        ("projects", "NOTION_PROJECTS_DB_ID"),
    ]:
        v = (os.getenv(env) or "").strip()
        if v:
            dbs[key] = v
    return {"ok": True, "read_only": True, "databases": dbs}


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


# ================================================================
# NOTION OPS — LIST DATABASES (READ ONLY)
# ================================================================
@app.get("/notion-ops/databases")
@app.get("/api/notion-ops/databases")
async def notion_ops_list_databases():
    from services.notion_service import get_notion_service

    ns = get_notion_service()

    # Tolerantno pokupi poznate DB id-jeve ako postoje na NotionService
    candidates = {
        "goals": ["goals_db_id", "_goals_db_id"],
        "tasks": ["tasks_db_id", "_tasks_db_id"],
        "projects": ["projects_db_id", "_projects_db_id"],
        "kpi": ["kpi_db_id", "_kpi_db_id"],
        "leads": ["leads_db_id", "_leads_db_id"],
        "agent_exchange": ["agent_exchange_db_id", "_agent_exchange_db_id"],
        "ai_summary": ["ai_summary_db_id", "_ai_summary_db_id"],
    }

    dbs: Dict[str, str] = {}
    for key, attrs in candidates.items():
        for a in attrs:
            v = getattr(ns, a, None)
            if isinstance(v, str) and v.strip():
                dbs[key] = v.strip()
                break

    # Ako nema ništa setovano, vrati empty map (UI će bar prestati da puca na 404)
    return {
        "ok": True,
        "read_only": True,
        "ops_safe_mode": _ops_safe_mode(),
        "databases": dbs,
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
    Accept:
      - {"query": {...}}
      - {"filter": {...}, "page_size": N, "sorts": [...], "start_cursor": "..."}
    Return:
      - dict compatible with Notion databases.query body keys
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


async def _call_maybe_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    out = fn(*args, **kwargs)
    if asyncio.iscoroutine(out):
        return await out
    return out


async def _query_notion_database(db_key: str, query: Dict[str, Any]) -> Dict[str, Any]:
    """
    Best-effort:
      1) try NotionService methods if present
      2) fallback to notion_client Client(auth=...)
    """
    from services.notion_service import get_notion_service

    notion_service = get_notion_service()

    # 1) Try NotionService public methods
    for name in ("query_database", "database_query", "query_db", "query"):
        fn = getattr(notion_service, name, None)
        if callable(fn):
            # try common signatures
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

    # 2) Fallback to notion_client
    try:
        from notion_client import Client  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Notion query failed: NotionService has no query method and notion_client is unavailable: {exc}",
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
        # IMPORTANT: notion_client is sync; run in a thread to avoid blocking event loop
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
async def notion_bulk_query(payload: Dict[str, Any] = Body(...)):
    """
    Supports:
      A) single query shape (used by your terminal):
         { "db_key": "tasks", "query": {...} }
         { "db_key": "tasks", "filter": {...}, "page_size": 20 }

      B) legacy batch shape (tests):
         { "queries": [ { "db_key": "...", "query": {...} }, ... ] }
         -> returns { "results": [ { "query": <q>, "items": [...], "response": {...} }, ... ] }
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    # A) Single query
    if isinstance(payload.get("db_key"), str) and payload["db_key"].strip():
        db_key = payload["db_key"].strip()
        q = _normalize_notion_query_payload(payload)
        res = await _query_notion_database(db_key, q)
        return res

    # B) Legacy batch
    queries = payload.get("queries")
    if queries is None:
        queries = []
    if not isinstance(queries, list):
        raise HTTPException(status_code=400, detail="queries must be a list")

    out: List[Dict[str, Any]] = []
    for q in queries:
        if not isinstance(q, dict):
            raise HTTPException(status_code=400, detail="each query must be an object")

        db_key = q.get("db_key")
        if not isinstance(db_key, str) or not db_key.strip():
            out.append(
                {
                    "query": q,
                    "items": [],
                    "response": {"results": [], "has_more": False},
                }
            )
            continue

        nq = _normalize_notion_query_payload(q)
        res = await _query_notion_database(db_key.strip(), nq)
        items = (
            res.get("results")
            if isinstance(res, dict) and isinstance(res.get("results"), list)
            else []
        )
        out.append({"query": q, "items": items, "response": res})

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
app.include_router(_chat_router, prefix="/api")
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
async def global_exception_handler(_: Request, exc: Exception):
    logger.exception("GLOBAL ERROR")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)},
    )


# ================================================================
# REACT FRONTEND (PROD BUILD) — SERVE dist/
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
