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
from typing import Any, Dict, List, Optional, Tuple

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


def _is_ceo_request(request: Request) -> bool:
    """
    Check if the request is from a CEO user.
    CEO users are identified by:
    1. Valid X-CEO-Token header (if CEO_TOKEN_ENFORCEMENT is enabled)
    2. X-Initiator == "ceo_chat" or similar CEO indicators
    """
    # If enforcement is enabled, check for valid token
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True

    # Check for CEO indicators in request (for non-enforced mode)
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True

    return False


def _guard_write_bulk(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE and approval checks
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return

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
# IDENTITY / MODE / STATE (READ-ONLY LOADS OK AT IMPORT)
# ================================================================
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state
from services.identity_loader import load_identity

from services.ceo_console_snapshot_service import CEOConsoleSnapshotService

# ================================================================
# NOTION SERVICE (KANONSKI INIT) — NO SIDE EFFECTS AT IMPORT
# ================================================================
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.notion_service import (
    init_notion_service_from_env_or_raise,
    try_get_notion_service,
)

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
from routers.notion_ops_router import router as notion_ops_router

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
    logger.critical("OS_ENABLED=false - system will not start.")
    raise RuntimeError("OS is disabled by configuration.")

identity = load_identity()
mode = load_mode()
state = load_state()

# ================================================================
# CANON: NO SERVICE CONSTRUCTION AT IMPORT TIME
# ================================================================
ai_command_service: Optional[AICommandService] = None
coo_translation_service: Optional[COOTranslationService] = None
coo_conversation_service: Optional[COOConversationService] = None

_execution_registry = None  # type: ignore[assignment]
_execution_orchestrator: Optional[ExecutionOrchestrator] = None


def _require_boot_services() -> (
    Tuple[
        AICommandService,
        COOTranslationService,
        COOConversationService,
        Any,
        ExecutionOrchestrator,
    ]
):
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail=_BOOT_ERROR or "System not ready")

    if (
        ai_command_service is None
        or coo_translation_service is None
        or coo_conversation_service is None
        or _execution_orchestrator is None
        or _execution_registry is None
    ):
        raise HTTPException(status_code=503, detail="Boot services not initialized")

    return (
        ai_command_service,
        coo_translation_service,
        coo_conversation_service,
        _execution_registry,
        _execution_orchestrator,
    )


# ================================================================
# HARD-BLOCK: ONLY NEXT_STEP MUST NEVER CREATE APPROVAL OR EXECUTE
# ================================================================
_HARD_READ_ONLY_INTENTS = {
    "ceo_console.next_step",
}


# ================================================================
# META-COMMANDS MUST NOT ENTER EXECUTION/APPROVAL
# ================================================================
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

    summary = {
        "command": cmd,
        "intent": intent,
        "params": params if isinstance(params, dict) else {},
    }

    md = getattr(ai_command, "metadata", None)
    if isinstance(md, dict) and isinstance(md.get("confidence_risk"), dict):
        summary["confidence_risk"] = md.get("confidence_risk")

    return summary


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


# ================================================================
# ? REPLACED FUNCTION (robust prompt extraction)
# ================================================================
def _extract_wrapper_patch_from_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Extract fill_missing patch from wrapper params.

    Canon: wrapper args/params contain prompt + optional fields (Status/Priority/Deadline/...).
    Gateway must ignore prompt and forward the rest as wrapper_patch.
    """
    if not isinstance(params, dict) or not params:
        return {}

    # Wrapper params often contain routing hints (intent/type/etc). We only want
    # user-fillable Notion field values.
    reserved = {
        "prompt",
        "intent",
        "intent_hint",
        "type",
        "command",
        "ai_command",
        "metadata",
        "session_id",
        "source",
        "db_key",
        "database",
        "operations",
    }

    patch: Dict[str, Any] = {}
    for k, v in params.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if k in reserved:
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        patch[k] = v
    return patch


def _apply_wrapper_patch_to_ai_command(
    ai_command: AICommand, wrapper_patch: Dict[str, Any]
) -> None:
    """Apply UI fill_missing patch to translated AICommand (post-translate).

    HARD RULES:
      - Only apply to notion_write/create_page.
      - Do not mutate prompt/title mapping except explicit patch overrides.
      - Use COOTranslationService normalizers.
      - If translation produced next_step/noop, caller must skip patch.
    """
    if not isinstance(wrapper_patch, dict) or not wrapper_patch:
        return

    if getattr(ai_command, "command", None) != "notion_write":
        return
    intent = getattr(ai_command, "intent", None)
    if intent not in {"create_page", "create_goal", "create_task", "create_project"}:
        return

    params = getattr(ai_command, "params", None)
    if not isinstance(params, dict):
        params = {}
        ai_command.params = params

    # For create_page we patch property_specs; for create_goal/task/project we patch params fields.
    property_specs = params.get("property_specs")
    if not isinstance(property_specs, dict):
        property_specs = {}
        params["property_specs"] = property_specs

    # Determine Status property type: goals use status, tasks use select.
    status_type = "select"
    db_key = params.get("db_key")
    if isinstance(db_key, str) and db_key.strip():
        lk = db_key.strip().lower()
        if lk in {"goals", "goal"}:
            status_type = "status"
        elif lk in {"tasks", "task"}:
            status_type = "select"

    if "Status" in wrapper_patch:
        raw = wrapper_patch.get("Status")
        if isinstance(raw, str) and raw.strip():
            name = COOTranslationService._normalize_status(raw)
            if intent == "create_page":
                property_specs["Status"] = {"type": status_type, "name": name}
            else:
                params["status"] = name

    if "Priority" in wrapper_patch:
        raw = wrapper_patch.get("Priority")
        if isinstance(raw, str) and raw.strip():
            name = COOTranslationService._normalize_priority(raw)
            if intent == "create_page":
                property_specs["Priority"] = {"type": "select", "name": name}
            else:
                params["priority"] = name

    if "Deadline" in wrapper_patch:
        raw = wrapper_patch.get("Deadline")
        if isinstance(raw, str) and raw.strip():
            iso = COOTranslationService._try_parse_date_to_iso(raw)
            if iso:
                if intent == "create_page":
                    property_specs["Deadline"] = {"type": "date", "start": iso}
                else:
                    params["deadline"] = iso

    if "Due Date" in wrapper_patch:
        raw = wrapper_patch.get("Due Date")
        if isinstance(raw, str) and raw.strip():
            iso = COOTranslationService._try_parse_date_to_iso(raw)
            if iso:
                if intent == "create_page":
                    property_specs["Due Date"] = {"type": "date", "start": iso}
                else:
                    params["deadline"] = iso

    if "Description" in wrapper_patch:
        raw = wrapper_patch.get("Description")
        if isinstance(raw, str) and raw.strip():
            if intent == "create_page":
                property_specs["Description"] = {
                    "type": "rich_text",
                    "text": raw.strip(),
                }
            else:
                params["description"] = raw.strip()

    params["property_specs"] = property_specs
    ai_command.params = params


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

    wrapper_patch = _extract_wrapper_patch_from_params(
        params if isinstance(params, dict) else {}
    )

    # ? Robust prompt extraction: params.prompt OR metadata.prompt OR metadata.wrapper.prompt
    prompt: Optional[str] = None
    if isinstance(params, dict):
        p0 = params.get("prompt")
        if isinstance(p0, str) and p0.strip():
            prompt = p0.strip()

    if prompt is None and isinstance(metadata, dict):
        p1 = metadata.get("prompt")
        if isinstance(p1, str) and p1.strip():
            prompt = p1.strip()

    if prompt is None and isinstance(metadata, dict):
        w = metadata.get("wrapper")
        if isinstance(w, dict):
            p2 = w.get("prompt")
            if isinstance(p2, str) and p2.strip():
                prompt = p2.strip()

    if not isinstance(prompt, str) or not prompt.strip():
        raise HTTPException(
            status_code=400,
            detail="ceo.command.propose cannot enter execution. Missing prompt for unwrap/translation (expected params.prompt or metadata.wrapper.prompt).",
        )

    # ============================================================
    # ENTERPRISE FAST-PATH: deterministic intent hints from NotionOpsAgent
    # ============================================================
    hint_intent: Optional[str] = None
    hint_type: Optional[str] = None
    if isinstance(params, dict):
        p_intent = params.get("intent") or params.get("intent_hint")
        if isinstance(p_intent, str) and p_intent.strip():
            hint_intent = p_intent.strip()
        p_type = params.get("type")
        if isinstance(p_type, str) and p_type.strip():
            hint_type = p_type.strip()

    def _strip_prefixes_for_title(s: str) -> str:
        t = (s or "").strip()
        if not t:
            return t
        t2 = re.sub(r"^(task|zadatak)\s*[:\-–—]\s*", "", t, flags=re.IGNORECASE).strip()
        t2 = re.sub(
            r"^(kreiraj|napravi|create)\s+(task|zadatak|project|projekat|projekt|goal|cilj)\w*\s*(?:u\s+notionu)?\s*[:\-–—,;]?\s*",
            "",
            t2,
            flags=re.IGNORECASE,
        ).strip()
        return t2 or t

    def _extract_relation_title_from_prompt(
        prompt_text: str, *, kind: str
    ) -> Optional[str]:
        """Best-effort extract of a relation target title from natural prompt.

        Examples (bs/en):
          - "povezi sa ciljem ADNAN RAMBO"
          - "sa ciljem: ADNAN RAMBO"
          - "with goal ADNAN RAMBO"
          - "goal: ADNAN RAMBO"
        """
        s = (prompt_text or "").strip()
        if not s:
            return None

        if kind == "goal":
            token = r"(?:ciljem|cilj|goal)"
        elif kind == "project":
            token = r"(?:projektom|projekat|projekt|project)"
        else:
            return None

        patterns = [
            rf"(?i)\b(?:povezi|pove\u017ei|link(?:aj)?|connect|attach)\s+(?:sa|with)\s+{token}\s*[:\-–—]?\s*([^,;\n]+)",
            rf"(?i)\b(?:sa|with)\s+{token}\s*[:\-–—]?\s*([^,;\n]+)",
            rf"(?i)\b{token}\s*[:=]\s*([^,;\n]+)",
        ]

        for pat in patterns:
            m = re.search(pat, s)
            if not m:
                continue
            val = (m.group(1) or "").strip().strip("\"'")
            if val:
                return val
        return None

    # Branch/batch requests: build operations list deterministically.
    try:
        if (hint_type or "").lower() in {"branch_request", "batch_request"} or (
            isinstance(hint_intent, str)
            and hint_intent.strip().lower()
            in {"batch_request", "batch", "branch_request"}
        ):
            from services.branch_request_handler import BranchRequestHandler  # noqa: PLC0415

            br = BranchRequestHandler.process_branch_request(prompt.strip())
            ops = br.get("operations") if isinstance(br, dict) else None
            if isinstance(ops, list) and ops:
                ai_command = AICommand(
                    command="notion_write",
                    intent="batch_request",
                    read_only=False,
                    params={
                        "operations": ops,
                        "source_prompt": prompt.strip(),
                        "wrapper_patch": dict(wrapper_patch) if wrapper_patch else None,
                    },
                    initiator=initiator,
                    validated=True,
                    metadata={
                        **(metadata if isinstance(metadata, dict) else {}),
                        "canon": "execute_raw_unwrap_batch_fast_path",
                        "endpoint": "/api/execute/raw",
                        "wrapper": {
                            "prompt": prompt.strip(),
                            "wrapper_patch": wrapper_patch,
                        },
                    },
                )

                if isinstance(wrapper_patch, dict) and wrapper_patch:
                    _apply_wrapper_patch_to_ai_command(ai_command, wrapper_patch)

                # Ensure downstream executor can apply schema-backed patches.
                try:
                    if isinstance(ai_command.params, dict) and wrapper_patch:
                        ai_command.params["wrapper_patch"] = dict(wrapper_patch)
                except Exception:
                    pass

                return ai_command
    except Exception:
        pass

    # Explicit goal + numbered task list (enterprise UX): convert to batch_request.
    try:
        from services.goal_task_batch_parser import (  # noqa: PLC0415
            build_batch_operations_from_parsed,
            parse_goal_with_explicit_tasks,
        )

        parsed = parse_goal_with_explicit_tasks(prompt.strip())
        if parsed:
            ops = build_batch_operations_from_parsed(parsed)
            if ops:
                ai_command = AICommand(
                    command="notion_write",
                    intent="batch_request",
                    read_only=False,
                    params={
                        "operations": ops,
                        "source_prompt": prompt.strip(),
                        "wrapper_patch": dict(wrapper_patch) if wrapper_patch else None,
                    },
                    initiator=initiator,
                    validated=True,
                    metadata={
                        **(metadata if isinstance(metadata, dict) else {}),
                        "canon": "execute_raw_unwrap_explicit_goal_task_batch",
                        "endpoint": "/api/execute/raw",
                        "wrapper": {
                            "prompt": prompt.strip(),
                            "wrapper_patch": wrapper_patch,
                        },
                    },
                )

                if isinstance(wrapper_patch, dict) and wrapper_patch:
                    _apply_wrapper_patch_to_ai_command(ai_command, wrapper_patch)

                try:
                    if isinstance(ai_command.params, dict) and wrapper_patch:
                        ai_command.params["wrapper_patch"] = dict(wrapper_patch)
                except Exception:
                    pass

                return ai_command
    except Exception:
        pass

    # If NotionOpsAgent didn't pass an explicit hint, try deterministic local detection.
    if not (isinstance(hint_intent, str) and hint_intent.strip()):
        try:
            from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415

            auto = NotionKeywordMapper.detect_intent(prompt.strip())
            if isinstance(auto, str) and auto.strip():
                hint_intent = auto.strip()
        except Exception:
            pass

    # If this looks like a batch/branch request, force batch_request so we do NOT enter create_goal/create_task fast-path.
    try:
        from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415

        if NotionKeywordMapper.is_batch_request(prompt.strip()):
            hint_intent = "batch_request"
    except Exception:
        pass

    # Create intents with explicit/detected hint: build minimal executable without LLM translation.
    try:
        if isinstance(hint_intent, str) and hint_intent.strip():
            hi = hint_intent.strip().lower()
            if hi in {"create_task", "create_goal", "create_project"}:
                raw_prompt = prompt.strip()
                title = _strip_prefixes_for_title(raw_prompt)
                if title:
                    extra_params: Dict[str, Any] = {"title": title}

                    # Reuse branch/property NLP so CEO Console single-input
                    # follows the same backend rules (status/priority/deadline, assignees).
                    try:
                        from services.branch_request_handler import (  # noqa: PLC0415
                            BranchRequestHandler,
                        )

                        props = BranchRequestHandler._extract_properties(  # type: ignore[attr-defined]
                            raw_prompt
                        )
                    except Exception:
                        props = {}

                    if isinstance(props, dict) and props:
                        # Map extracted properties into fast-path params.
                        prio = props.get("priority")
                        if isinstance(prio, str) and prio.strip():
                            extra_params.setdefault("priority", prio.strip())

                        status = props.get("status")
                        if isinstance(status, str) and status.strip():
                            extra_params.setdefault("status", status.strip())

                        deadline = props.get("deadline")
                        if isinstance(deadline, str) and deadline.strip():
                            extra_params.setdefault("deadline", deadline.strip())

                        assignees = props.get("assignees")
                        if isinstance(assignees, list) and assignees:
                            extra_params.setdefault("assignees", assignees)

                    # Preserve relation intent if user specified it by title.
                    if hi == "create_task":
                        goal_title = _extract_relation_title_from_prompt(
                            raw_prompt, kind="goal"
                        )
                        if goal_title:
                            extra_params["goal_title"] = goal_title
                        project_title = _extract_relation_title_from_prompt(
                            raw_prompt, kind="project"
                        )
                        if project_title:
                            extra_params["project_title"] = project_title

                    if hi == "create_project":
                        goal_title = _extract_relation_title_from_prompt(
                            raw_prompt, kind="goal"
                        )
                        if goal_title:
                            extra_params["primary_goal_title"] = goal_title

                    ai_command = AICommand(
                        command="notion_write",
                        intent=hi,
                        read_only=False,
                        params=extra_params,
                        initiator=initiator,
                        validated=True,
                        metadata={
                            **(metadata if isinstance(metadata, dict) else {}),
                            "canon": "execute_raw_unwrap_intent_hint_fast_path",
                            "endpoint": "/api/execute/raw",
                            "wrapper": {
                                "prompt": raw_prompt,
                                "wrapper_patch": wrapper_patch,
                            },
                        },
                    )

                    if isinstance(wrapper_patch, dict) and wrapper_patch:
                        _apply_wrapper_patch_to_ai_command(ai_command, wrapper_patch)

                    try:
                        if isinstance(ai_command.params, dict) and wrapper_patch:
                            ai_command.params["wrapper_patch"] = dict(wrapper_patch)
                    except Exception:
                        pass

                    return ai_command
    except Exception:
        pass

    # require translation service to exist (booted)
    _, trans, _, _, _ = _require_boot_services()

    ai_command = None
    try:
        ai_command = trans.translate(
            raw_input=prompt.strip(),
            source="system",
            context={
                "mode": "execute",
                "via": "execute_raw_unwrap",
                "wrapper_patch": wrapper_patch,
            },
        )
    except Exception:
        ai_command = None

    # Never allow wrapper to remain wrapper after translate (avoid loops)
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

    # Apply UI fill_missing patch (Status/Priority/Deadline/...) to final AICommand
    # Ignore if translate returned NOOP/next_step.
    if isinstance(wrapper_patch, dict) and wrapper_patch:
        if (
            getattr(ai_command, "command", None) not in _HARD_READ_ONLY_INTENTS
            and getattr(ai_command, "intent", None) not in _HARD_READ_ONLY_INTENTS
        ):
            _apply_wrapper_patch_to_ai_command(ai_command, wrapper_patch)

        # Pass through for schema-backed patching during execution (NotionService).
        if getattr(ai_command, "command", None) == "notion_write":
            p0 = getattr(ai_command, "params", None)
            if not isinstance(p0, dict):
                p0 = {}
            p0["wrapper_patch"] = dict(wrapper_patch)
            ai_command.params = p0

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
        if isinstance(wrapper_patch, dict) and wrapper_patch:
            md["wrapper"].setdefault("patch", dict(wrapper_patch))

    if isinstance(metadata, dict):
        for k, v in metadata.items():
            md[k] = v
    ai_command.metadata = md

    return ai_command


# ================================================================
# BOOT/SHUTDOWN ROUTINES (SINGLE SSOT)
# ================================================================
_boot_lock = asyncio.Lock()


async def _boot_once() -> None:
    global _BOOT_READY, _BOOT_ERROR
    global ai_command_service, coo_translation_service, coo_conversation_service
    global _execution_registry, _execution_orchestrator

    async with _boot_lock:
        if _BOOT_READY:
            return

        _BOOT_READY = False
        _BOOT_ERROR = None

        # ensure globals start clean (reload-safe)
        ai_command_service = None
        coo_translation_service = None
        coo_conversation_service = None
        _execution_registry = None
        _execution_orchestrator = None

        try:
            try:
                validate_runtime_env_or_raise()
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"env_invalid:{exc}")
                logger.critical("Boot aborted due to invalid env: %s", exc)
                raise

            # SSOT: init NotionService singleton here
            try:
                init_notion_service_from_env_or_raise()
                logger.info("NotionService singleton initialized (SSOT via env)")
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"notion_init_failed:{exc}")
                logger.critical("NotionService init failed: %s", exc)
                raise

            # BOOTSTRAP app wiring (safe after Notion init)
            bootstrap_application()

            # construct all dependent services AFTER Notion init
            try:
                ai_command_service = AICommandService()
                coo_translation_service = COOTranslationService()
                coo_conversation_service = COOConversationService()

                _execution_registry = get_execution_registry()
                _execution_orchestrator = ExecutionOrchestrator()

                logger.info(
                    "Boot services initialized (orchestrator/translation/command)"
                )
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"boot_services_init_failed:{exc}")
                logger.critical("Boot services init failed: %s", exc)
                raise

            # agent registry load (best-effort)
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

            # inject AI router services (now guaranteed initialized)
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

            # inject AI ops services (best-effort)
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

            # best-effort knowledge sync
            try:
                notion_service = try_get_notion_service()
                if notion_service is not None:
                    await notion_service.sync_knowledge_snapshot()
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"notion_sync_failed:{exc}")
                logger.warning("Notion knowledge snapshot sync failed: %s", exc)

            _BOOT_READY = True
            logger.info("System boot completed. READY.")
        except Exception:
            _BOOT_READY = False
            raise


async def _shutdown_best_effort() -> None:
    global _BOOT_READY
    global ai_command_service, coo_translation_service, coo_conversation_service
    global _execution_registry, _execution_orchestrator

    try:
        ns = try_get_notion_service()
        if ns is not None:
            close_fn = getattr(ns, "aclose", None)
            if callable(close_fn):
                await close_fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("NotionService shutdown close failed: %s", exc)

    ai_command_service = None
    coo_translation_service = None
    coo_conversation_service = None
    _execution_registry = None
    _execution_orchestrator = None

    _BOOT_READY = False
    logger.info("System shutdown — boot_ready=False.")


def _is_boot_exempt_path(path: str) -> bool:
    p = (path or "").strip()
    if not p:
        return True
    if p in {"/health", "/ready", "/", "/favicon.ico"}:
        return True
    if p.startswith("/docs") or p.startswith("/openapi") or p.startswith("/redoc"):
        return True
    if p.startswith("/assets") or p.startswith("/static"):
        return True
    if p in {"/api/ceo-console/status", "/ceo-console/status"}:
        return True
    return False


async def _ensure_boot_if_needed(request: Request) -> None:
    if _BOOT_READY:
        return
    if _is_boot_exempt_path(request.url.path):
        return
    try:
        await _boot_once()
    except Exception:
        raise HTTPException(
            status_code=503, detail=_BOOT_ERROR or "System not ready"
        ) from None


# ================================================================
# LIFESPAN
# ================================================================
@asynccontextmanager
async def lifespan(_: FastAPI):
    await _boot_once()
    try:
        yield
    finally:
        await _shutdown_best_effort()


# ================================================================
# APP INIT
# ================================================================
app = FastAPI(
    title=SYSTEM_NAME,
    version=VERSION,
    lifespan=lifespan,
)


@app.on_event("startup")
async def _startup_event() -> None:
    await _boot_once()


@app.on_event("shutdown")
async def _shutdown_event() -> None:
    await _shutdown_best_effort()


# ================================================================
# REQUEST TRACE
# ================================================================
@app.middleware("http")
async def request_trace_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.req_id = req_id

    await _ensure_boot_if_needed(request)

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


class NotionReadResponse(BaseModel):
    ok: bool
    title: Optional[str] = None
    notion_url: Optional[str] = None
    content_markdown: Optional[str] = None
    error: Optional[str] = None


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
        r"^(kreiraj|napravi|create)\s+cilj[a]?(?:\s+u\s+notionu)?\s*[:\-–—,;]?\s*",
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


def _ensure_str(x: Any) -> str:
    return x if isinstance(x, str) else ""


def _proposal_wrapper_dict(*, prompt: str, source: str) -> Dict[str, Any]:
    safe_prompt = (prompt or "").strip() or "noop"
    return {
        "command": PROPOSAL_WRAPPER_INTENT,  # ceo.command.propose
        "args": {"prompt": safe_prompt},
        "intent": PROPOSAL_WRAPPER_INTENT,
        "reason": "Notion write intent ide kroz approval pipeline; predlažem komandu za promotion/execute.",
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
    pcs = result.get("proposed_commands")
    pcs_list = _normalize_gateway_proposed_commands(pcs)

    # If backend already provided proposals, just normalize and exit.
    if len(pcs_list) > 0:
        result["proposed_commands"] = pcs_list
        tr0 = _ensure_dict(result.get("trace"))
        tr0.setdefault("fallback_proposed_commands", False)
        tr0.setdefault("router_version", "gateway-proposed-commands-normalize-v1")
        result["trace"] = tr0
        return

    text = (prompt or "").strip().lower()
    write_like = any(
        k in text
        for k in [
            "create",
            "kreiraj",
            "napravi",
            "dodaj",
            "update",
            "azuriraj",
            "izmijeni",
            "promijeni",
            "delete",
            "obrisi",
            "ukloni",
            "task",
            "zadatak",
            "goal",
            "cilj",
            "notion",
        ]
    )

    if not write_like:
        result["proposed_commands"] = []
        tr = _ensure_dict(result.get("trace"))
        tr["fallback_proposed_commands"] = False
        tr["router_version"] = "gateway-fallback-proposals-disabled-for-nonwrite-v1"
        result["trace"] = tr
        return

    # CANON FALLBACK (SSOT): emit notion_write envelope directly (NO ceo.command.propose wrapper).
    pc = {
        "command": PROPOSAL_WRAPPER_INTENT,  # ceo.command.propose
        "intent": PROPOSAL_WRAPPER_INTENT,  # ceo.command.propose
        "dry_run": True,
        "requires_approval": True,
        "risk": "LOW",
        "scope": "api_execute_raw",
        "params": {
            "ai_command": {
                # Keep prompt so backend can translate later if needed.
                "intent": PROPOSAL_WRAPPER_INTENT,
                "prompt": (prompt or "").strip(),
                "target": None,
                "operations": [],
            }
        },
        "payload_summary": {
            "endpoint": "/api/execute/raw",
            "canon": "CEO_CONSOLE_EXECUTION_FLOW",
            "source": "ceo_console",
        },
        "reason": "Approval required (write intent detected).",
    }

    result["proposed_commands"] = [pc]

    tr = _ensure_dict(result.get("trace"))
    tr["fallback_proposed_commands"] = True
    tr["router_version"] = "gateway-fallback-proposed-commands-writeonly-v2-canon"
    result["trace"] = tr


def _compute_confidence_risk_block(
    *,
    prompt: str,
    trace: Dict[str, Any],
    proposed_commands: List[Dict[str, Any]],
) -> Dict[str, Any]:
    tr = trace if isinstance(trace, dict) else {}
    pcs = proposed_commands if isinstance(proposed_commands, list) else []

    fallback = bool(tr.get("fallback_proposed_commands") is True)

    assumption_count = 1 if fallback else 0

    risk_level = "low"
    if len(pcs) > 0:
        risk_level = "medium"

    for p in pcs:
        if not isinstance(p, dict):
            continue
        r = (p.get("risk") or p.get("risk_hint") or "").strip().lower()
        if r in {"high", "critical"}:
            risk_level = "high"
            break

    confidence_score = 0.90
    if fallback:
        confidence_score = 0.60

    if not (prompt or "").strip():
        confidence_score = min(confidence_score, 0.50)

    try:
        confidence_score_f = float(confidence_score)
    except Exception:
        confidence_score_f = 0.50
    if confidence_score_f < 0.0:
        confidence_score_f = 0.0
    if confidence_score_f > 1.0:
        confidence_score_f = 1.0

    if risk_level not in {"low", "medium", "high"}:
        risk_level = "low"

    if not isinstance(assumption_count, int) or assumption_count < 0:
        assumption_count = 0

    return {
        "confidence_score": confidence_score_f,
        "risk_level": risk_level,
        "assumption_count": assumption_count,
    }


# ===========================
# PHASE A FIX: robust normalize
# ===========================
def _normalize_execute_raw_payload_dict(body: Dict[str, Any]) -> ExecuteRawInput2:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    cmd = (
        body.get("command")
        or body.get("name")
        or body.get("command_type")
        or body.get("type")
        or ""
    )
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

    if not params:
        args0 = body.get("args")
        if isinstance(args0, dict):
            params = dict(args0)

    if not params:
        payload0 = body.get("payload")
        if isinstance(payload0, dict):
            params = dict(payload0)

    # Compatibility: some proposals wrap the real executable command under params.ai_command.
    # Example (observed from CEO Console proposals):
    #   { command: "notion_write", intent: "notion_write", params: { ai_command: { command:"notion_write", intent:"create_page", params:{...} } } }
    # If we don't unwrap, the orchestrator will attempt to execute intent="notion_write" and NotionService will reject it.
    if isinstance(params, dict):
        ac = params.get("ai_command")
        if isinstance(ac, dict):
            ac_cmd = ac.get("command")
            ac_intent = ac.get("intent")
            ac_params = ac.get("params")
            ac_args = ac.get("args")

            # Unwrap only when ai_command looks like an actual command envelope.
            if (
                isinstance(ac_cmd, str)
                and ac_cmd.strip()
                and (isinstance(ac_params, dict) or isinstance(ac_args, dict))
            ):
                cmd = ac_cmd.strip()
                if isinstance(ac_intent, str) and ac_intent.strip():
                    intent = ac_intent.strip()
                else:
                    intent = cmd

                if isinstance(ac_params, dict):
                    params = dict(ac_params)
                elif isinstance(ac_args, dict):
                    params = dict(ac_args)

    if intent == PROPOSAL_WRAPPER_INTENT and "prompt" not in params:
        args = body.get("args")
        if isinstance(args, dict):
            prompt = args.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                params["prompt"] = prompt.strip()

        if "prompt" not in params:
            payload = body.get("payload")
            if isinstance(payload, dict):
                prompt = payload.get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    params["prompt"] = prompt.strip()

        if "prompt" not in params:
            prompt = body.get("prompt")
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

    # Merge envelope metadata if present.
    if isinstance(body.get("params"), dict):
        ac0 = body["params"].get("ai_command")
        if isinstance(ac0, dict) and isinstance(ac0.get("metadata"), dict):
            merged_md = dict(ac0.get("metadata") or {})
            merged_md.update(metadata)
            metadata = merged_md

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


def _notion_properties_preview_from_property_specs(
    property_specs: Dict[str, Any],
) -> Dict[str, Any]:
    """Best-effort preview of the Notion `properties` payload.

    IMPORTANT:
      - No Notion schema lookups and no network calls.
      - Mirrors the core mapping logic in NotionService for common types.
      - Execution-time schema normalization (status vs select, option name
        resolution) may still adjust the final payload.
    """
    out: Dict[str, Any] = {}
    if not isinstance(property_specs, dict) or not property_specs:
        return out

    for prop_name, spec in property_specs.items():
        if not isinstance(prop_name, str) or not prop_name.strip():
            continue
        if not isinstance(spec, dict):
            continue

        pn = prop_name.strip()
        stype = _ensure_str(spec.get("type")).lower()

        if stype == "title":
            txt = _ensure_str(spec.get("text") or spec.get("value") or "")
            out[pn] = {"title": [{"text": {"content": txt.strip()}}]}
            continue

        if stype in ("rich_text", "text"):
            txt = _ensure_str(spec.get("text") or spec.get("value") or "")
            out[pn] = {"rich_text": [{"text": {"content": txt.strip()}}]}
            continue

        if stype == "select":
            name = _ensure_str(spec.get("name") or spec.get("value") or "").strip()
            out[pn] = {"select": {"name": name}} if name else {"select": None}
            continue

        if stype == "status":
            name = _ensure_str(spec.get("name") or spec.get("value") or "").strip()
            out[pn] = {"status": {"name": name}} if name else {"status": None}
            continue

        if stype == "date":
            date_str = _ensure_str(spec.get("start") or spec.get("value") or "").strip()
            out[pn] = {"date": {"start": date_str}} if date_str else {"date": None}
            continue

        # Unknown types ignored by design
        continue

    return out


# ================================================================
# /api/execute — EXECUTION PATH (NL INPUT)
# ================================================================
@app.post("/api/execute")
async def execute_command(payload: ExecuteInput):
    cleaned_text = _preprocess_ceo_nl_input(payload.text, smart_context=None)

    _, trans, _, registry, orchestrator = _require_boot_services()

    ai_command = trans.translate(
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

    orchestrator.registry.register(ai_command)
    registry.register(ai_command)

    result = await orchestrator.execute(ai_command)

    if isinstance(result, dict):
        result.setdefault("approval_id", approval_id)
        result.setdefault("execution_id", execution_id)

    return result


@app.post("/api/execute/raw")
async def execute_raw_command(payload: Dict[str, Any] = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    normalized = _normalize_execute_raw_payload_dict(payload)

    if (normalized.intent in _HARD_READ_ONLY_INTENTS) or (
        normalized.command in _HARD_READ_ONLY_INTENTS
    ):
        execution_id = str(uuid.uuid4())
        return {
            "status": "COMPLETED",
            "execution_state": "COMPLETED",
            "read_only": True,
            "execution_id": execution_id,
            "approval_id": None,
            "command": normalized.command,
            "intent": normalized.intent,
            "params": normalized.params if isinstance(normalized.params, dict) else {},
            "proposed_commands": [],
            "trace": {
                "canon": "execute_raw_hard_block_read_only",
                "endpoint": "/api/execute/raw",
                "hard_block_intent": normalized.intent,
                "hard_block_command": normalized.command,
                "note": "next_step hard-block only; wrapper intents proceed to unwrap+approval",
            },
        }

    _, _, _, registry, orchestrator = _require_boot_services()

    ai_command = _unwrap_proposal_wrapper_or_raise(
        command=normalized.command,
        intent=normalized.intent,
        params=normalized.params if isinstance(normalized.params, dict) else {},
        initiator=normalized.initiator,
        read_only=normalized.read_only,
        metadata=normalized.metadata if isinstance(normalized.metadata, dict) else {},
    )

    # CRITICAL: wrapper unwrapping may yield a meta-command (next_step).
    # Hard-block those *after* unwrap so they never enter approval/execution.
    if (getattr(ai_command, "intent", None) in _HARD_READ_ONLY_INTENTS) or (
        getattr(ai_command, "command", None) in _HARD_READ_ONLY_INTENTS
    ):
        execution_id = _ensure_execution_id(ai_command)
        return {
            "status": "COMPLETED",
            "execution_state": "COMPLETED",
            "read_only": True,
            "execution_id": execution_id,
            "approval_id": None,
            "text": "Need more information before executing. Please answer the CEO Console questions, then retry.",
            "command": getattr(ai_command, "command", None),
            "intent": getattr(ai_command, "intent", None),
            "params": getattr(ai_command, "params", None)
            if isinstance(getattr(ai_command, "params", None), dict)
            else {},
            "proposed_commands": [],
            "trace": {
                "canon": "execute_raw_hard_block_after_unwrap",
                "endpoint": "/api/execute/raw",
                "hard_block_intent": getattr(ai_command, "intent", None),
                "hard_block_command": getattr(ai_command, "command", None),
            },
        }

    execution_id = _ensure_execution_id(ai_command)

    approval_state = get_approval_state()

    # PHASE A FIX: robust scope/risk extraction
    scope_val = payload.get("scope") or payload.get("scope_hint") or "api_execute_raw"
    risk_val = (
        payload.get("risk")
        or payload.get("risk_level")
        or payload.get("risk_hint")
        or "unknown"
    )

    approval = approval_state.create(
        command=getattr(ai_command, "command", None) or "execute_raw",
        payload_summary=_safe_command_summary(ai_command),
        scope=scope_val,
        risk_level=risk_val,
        execution_id=execution_id,
    )

    approval_id = approval.get("approval_id")
    if not approval_id:
        raise HTTPException(
            status_code=500, detail="Approval create failed: missing approval_id"
        )

    _ensure_trace_on_command(ai_command, approval_id=approval_id)

    orchestrator.registry.register(ai_command)
    registry.register(ai_command)

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


@app.post("/api/execute/preview")
async def execute_preview_command(
    request: Request, payload: Dict[str, Any] = Body(...)
):
    """Preview the *exact* command payload (no approvals, no execution).

    Intended for CEO Console UI so the user can confirm Notion mapping
    (property_specs -> properties) before hitting Approve.
    """
    if not _is_ceo_request(request):
        raise HTTPException(
            status_code=403, detail="This endpoint is restricted to CEO users only"
        )
    _require_ceo_token_if_enforced(request)

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    normalized = _normalize_execute_raw_payload_dict(payload)

    # Hard read-only intents stay read-only.
    if (normalized.intent in _HARD_READ_ONLY_INTENTS) or (
        normalized.command in _HARD_READ_ONLY_INTENTS
    ):
        return {
            "ok": True,
            "read_only": True,
            "command": {
                "command": normalized.command,
                "intent": normalized.intent,
                "params": normalized.params
                if isinstance(normalized.params, dict)
                else {},
                "initiator": normalized.initiator,
                "metadata": normalized.metadata
                if isinstance(normalized.metadata, dict)
                else {},
            },
            "notion": None,
            "trace": {
                "canon": "execute_preview_hard_block_read_only",
                "endpoint": "/api/execute/preview",
            },
        }

    ai_command = _unwrap_proposal_wrapper_or_raise(
        command=normalized.command,
        intent=normalized.intent,
        params=normalized.params if isinstance(normalized.params, dict) else {},
        initiator=normalized.initiator,
        read_only=True,
        metadata=normalized.metadata if isinstance(normalized.metadata, dict) else {},
    )

    # Preview should always be treated as read-only.
    ai_command.read_only = True
    md = getattr(ai_command, "metadata", None)
    if not isinstance(md, dict):
        md = {}
    md["canon"] = "execute_preview"
    md["endpoint"] = "/api/execute/preview"
    md["preview"] = True
    ai_command.metadata = md

    cmd_dump = (
        ai_command.model_dump()
        if hasattr(ai_command, "model_dump")
        else _to_serializable(ai_command)
    )

    notion_block = None
    review_block = None

    # If this came from a proposal wrapper, we can deterministically provide a review schema
    # so UI can fill missing Status/Priority/Deadline/etc before approval.
    try:
        from services.review_contract import detect_write_create_review_contract  # noqa: PLC0415

        prompt = None
        md0 = getattr(ai_command, "metadata", None)
        if isinstance(md0, dict):
            w0 = md0.get("wrapper")
            if isinstance(w0, dict):
                p0 = w0.get("prompt")
                if isinstance(p0, str) and p0.strip():
                    prompt = p0.strip()

        if isinstance(prompt, str) and prompt.strip():
            ok, intent_type, missing_fields, fields_schema = (
                detect_write_create_review_contract(prompt)
            )
            if ok and isinstance(fields_schema, dict) and fields_schema:
                review_block = {
                    "type": "command_review",
                    "mode": "fill_missing" if missing_fields else "approve",
                    "title": "Complete fields before approval",
                    "summary": "Add or confirm Notion field values (Status/Priority/Deadline/etc).",
                    "missing_fields": missing_fields,
                    "fields_schema": fields_schema,
                }
    except Exception:
        review_block = None

    # Enterprise UX: always try to provide DB schema for table preview.
    async def _fallback_fields_schema(db_key: str) -> Dict[str, Any]:
        k = (db_key or "").strip().lower()
        base: Dict[str, Any] = {
            "Name": {"type": "title"},
            "Status": {"type": "status"},
            "Priority": {"type": "select"},
            "Deadline": {"type": "date"},
            "Due Date": {"type": "date"},
            "Description": {"type": "rich_text"},
        }
        if k in {"tasks", "task"}:
            base.setdefault("Goal", {"type": "relation"})
            base.setdefault("Project", {"type": "relation"})
            base.setdefault("Owner", {"type": "people"})
        if k in {"projects", "project"}:
            base.setdefault("Primary Goal", {"type": "relation"})
        return base

    async def _best_effort_fields_schema(db_key: str) -> Tuple[Dict[str, Any], str]:
        db_key = (db_key or "").strip()
        if not db_key:
            return {}, "none"
        try:
            from services.notion_service import get_or_init_notion_service  # noqa: PLC0415

            svc = get_or_init_notion_service()
            if svc is not None:
                schema = await svc.get_fields_schema(db_key)
                if isinstance(schema, dict) and schema:
                    return schema, "notion"
        except Exception:
            pass

        fb = await _fallback_fields_schema(db_key)
        return (fb if isinstance(fb, dict) else {}), "fallback"

    # Determine DB keys involved so we can attach schema even if notion_block is empty.
    db_keys: List[str] = []
    try:
        if getattr(ai_command, "command", None) == "notion_write":
            intent0 = getattr(ai_command, "intent", None)
            params0 = getattr(ai_command, "params", None)
            params0 = params0 if isinstance(params0, dict) else {}

            if intent0 in {"create_goal"}:
                db_keys = ["goals"]
            elif intent0 in {"create_task"}:
                db_keys = ["tasks"]
            elif intent0 in {"create_project"}:
                db_keys = ["projects"]
            elif intent0 in {"create_page", "update_page"}:
                dk = params0.get("db_key")
                if isinstance(dk, str) and dk.strip():
                    db_keys = [dk.strip()]
            elif intent0 in {"batch_request", "batch", "branch_request"}:
                ops0 = params0.get("operations")
                if isinstance(ops0, list):
                    for op in ops0:
                        if not isinstance(op, dict):
                            continue
                        payload0 = op.get("payload")
                        payload0 = payload0 if isinstance(payload0, dict) else {}
                        dk = payload0.get("db_key")
                        if isinstance(dk, str) and dk.strip():
                            db_keys.append(dk.strip())
                        else:
                            oi = (op.get("intent") or "").strip().lower()
                            if oi == "create_goal":
                                db_keys.append("goals")
                            elif oi == "create_task":
                                db_keys.append("tasks")
                            elif oi == "create_project":
                                db_keys.append("projects")
    except Exception:
        db_keys = []

    # If we couldn't infer db keys from the translated command, infer from wrapper prompt.
    if not db_keys:
        try:
            prompt0 = None
            md0 = getattr(ai_command, "metadata", None)
            if isinstance(md0, dict):
                w0 = md0.get("wrapper")
                if isinstance(w0, dict):
                    p0 = w0.get("prompt")
                    if isinstance(p0, str) and p0.strip():
                        prompt0 = p0.strip()

            if isinstance(prompt0, str) and prompt0:
                from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415

                auto_intent = NotionKeywordMapper.detect_intent(prompt0)
                ai = (auto_intent or "").strip().lower()
                if ai == "create_goal":
                    db_keys = ["goals"]
                elif ai == "create_task":
                    db_keys = ["tasks"]
                elif ai == "create_project":
                    db_keys = ["projects"]

                # Heuristic: if prompt mentions both goal and task, attach both schemas.
                if not db_keys:
                    p_low = prompt0.lower()
                    has_goal = bool(re.search(r"\b(cilj\w*|goal\w*)\b", p_low))
                    has_task = bool(re.search(r"\b(zadat\w*|task\w*)\b", p_low))
                    if has_goal and has_task:
                        db_keys = ["goals", "tasks"]
        except Exception:
            pass

    # Normalize + de-dupe
    db_keys = [k for k in [str(x).strip() for x in db_keys] if k]
    db_keys = list(dict.fromkeys(db_keys))

    # Attach schema to review block (single union) and keep per-db map for debugging.
    try:
        if db_keys:
            union_schema: Dict[str, Any] = {}
            by_db: Dict[str, Any] = {}
            sources: Dict[str, str] = {}
            for dk in db_keys:
                sch, src = await _best_effort_fields_schema(dk)
                if isinstance(sch, dict) and sch:
                    by_db[dk] = sch
                    sources[dk] = src
                    for k, v in sch.items():
                        if k not in union_schema:
                            union_schema[k] = v

            if union_schema:
                if not isinstance(review_block, dict):
                    review_block = {
                        "type": "command_review",
                        "mode": "approve",
                        "title": "Notion schema",
                        "summary": "Notion database schema (best-effort) for preview/fill-missing.",
                        "missing_fields": [],
                        "fields_schema": union_schema,
                    }
                else:
                    fs0 = review_block.get("fields_schema")
                    if not isinstance(fs0, dict) or not fs0:
                        review_block["fields_schema"] = union_schema
                review_block["fields_schema_by_db_key"] = by_db
                review_block["schema_source_by_db_key"] = sources
    except Exception:
        pass

    try:
        if getattr(ai_command, "command", None) == "notion_write":
            intent = getattr(ai_command, "intent", None)
            params = getattr(ai_command, "params", None)
            params = params if isinstance(params, dict) else {}

            def _build_property_specs_from_payload(
                payload: Dict[str, Any],
            ) -> Dict[str, Any]:
                payload = payload if isinstance(payload, dict) else {}
                title = _ensure_str(
                    payload.get("title") or payload.get("name") or payload.get("Name")
                ).strip()
                description = _ensure_str(
                    payload.get("description") or payload.get("Description")
                ).strip()
                deadline = _ensure_str(
                    payload.get("deadline")
                    or payload.get("due_date")
                    or payload.get("Deadline")
                    or payload.get("Due Date")
                ).strip()
                priority = _ensure_str(
                    payload.get("priority") or payload.get("Priority")
                ).strip()
                status = _ensure_str(
                    payload.get("status") or payload.get("Status")
                ).strip()

                ps: Dict[str, Any] = {}
                if title:
                    ps["Name"] = {"type": "title", "text": title}
                if description:
                    ps["Description"] = {"type": "rich_text", "text": description}
                if deadline:
                    ps["Deadline"] = {"type": "date", "start": deadline}
                if priority:
                    ps["Priority"] = {"type": "select", "name": priority}
                if status:
                    ps["Status"] = {"type": "status", "name": status}

                extra_specs = payload.get("property_specs")
                if isinstance(extra_specs, dict) and extra_specs:
                    # Let explicit specs override derived ones.
                    ps.update(extra_specs)
                return ps

            # create_page/update_page carry property_specs directly.
            if intent in {"create_page", "update_page"}:
                db_key = params.get("db_key")
                property_specs = params.get("property_specs")
                if isinstance(property_specs, dict) and property_specs:
                    notion_block = {
                        "db_key": db_key,
                        "property_specs": property_specs,
                        "properties_preview": _notion_properties_preview_from_property_specs(
                            property_specs
                        ),
                        "note": "Preview does not hit Notion. Final execution may still normalize select/status types based on DB schema.",
                    }

            # create_goal/create_task/create_project derive property_specs at execution time.
            elif intent in {"create_goal", "create_task", "create_project"}:
                db_key = (
                    "goals"
                    if intent == "create_goal"
                    else "tasks"
                    if intent == "create_task"
                    else "projects"
                )

                title = _ensure_str(params.get("title")).strip()
                description = _ensure_str(params.get("description")).strip()
                deadline = _ensure_str(params.get("deadline")).strip()
                priority = _ensure_str(params.get("priority")).strip()
                status = _ensure_str(params.get("status")).strip()

                property_specs: Dict[str, Any] = {}
                if title:
                    property_specs["Name"] = {"type": "title", "text": title}
                if description:
                    property_specs["Description"] = {
                        "type": "rich_text",
                        "text": description,
                    }
                if deadline:
                    property_specs["Deadline"] = {"type": "date", "start": deadline}
                if priority:
                    property_specs["Priority"] = {"type": "select", "name": priority}
                if status:
                    property_specs["Status"] = {"type": "status", "name": status}

                if property_specs:
                    notion_block = {
                        "db_key": db_key,
                        "property_specs": property_specs,
                        "properties_preview": _notion_properties_preview_from_property_specs(
                            property_specs
                        ),
                        "note": "Preview does not hit Notion. create_goal/create_task/create_project derive properties at execution time; this mirrors that mapping.",
                    }

            # batch_request: preview each operation as a table row
            elif intent in {"batch_request", "batch", "branch_request"}:
                ops = params.get("operations")
                if isinstance(ops, list) and ops:
                    rows: List[Dict[str, Any]] = []

                    def _format_ref(v: Any) -> Optional[str]:
                        if v is None:
                            return None
                        if isinstance(v, str):
                            s = v.strip()
                            if not s:
                                return None
                            # Convention used by BranchRequestHandler: "$op_id" references.
                            if s.startswith("$") and len(s) > 1:
                                return f"ref:{s[1:]}"
                            return s
                        # Keep non-string refs readable (numbers, dicts)
                        try:
                            return str(v)
                        except Exception:
                            return None

                    for idx, op in enumerate(ops):
                        if not isinstance(op, dict):
                            continue
                        op_id = op.get("op_id")
                        op_intent = (
                            _ensure_str(op.get("intent") or "").strip() or "unknown"
                        )
                        payload = op.get("payload")
                        payload = payload if isinstance(payload, dict) else {}

                        db_key = payload.get("db_key")
                        if not isinstance(db_key, str) or not db_key.strip():
                            db_key = (
                                "goals"
                                if op_intent == "create_goal"
                                else "tasks"
                                if op_intent == "create_task"
                                else "projects"
                                if op_intent == "create_project"
                                else None
                            )

                        # Try to build a Notion-like properties preview for create intents.
                        ps: Dict[str, Any] = {}
                        if op_intent in {
                            "create_goal",
                            "create_task",
                            "create_project",
                        }:
                            ps = _build_property_specs_from_payload(payload)
                        elif op_intent in {"create_page", "update_page"}:
                            sp0 = payload.get("property_specs") or payload.get(
                                "properties"
                            )
                            if isinstance(sp0, dict) and sp0:
                                ps = dict(sp0)

                        row: Dict[str, Any] = {
                            "op_index": idx,
                            "op_id": op_id,
                            "intent": op_intent,
                            "db_key": db_key,
                        }

                        # Relationship hints (pre-execution): show readable refs even before Notion IDs exist.
                        goal_ref = _format_ref(
                            payload.get("goal_id") or payload.get("primary_goal_id")
                        )
                        project_ref = _format_ref(payload.get("project_id"))
                        parent_goal_ref = _format_ref(payload.get("parent_goal_id"))
                        if goal_ref:
                            row["Goal Ref"] = goal_ref
                        if project_ref:
                            row["Project Ref"] = project_ref
                        if parent_goal_ref:
                            row["Parent Goal Ref"] = parent_goal_ref

                        if ps:
                            row["property_specs"] = ps
                            row["properties_preview"] = (
                                _notion_properties_preview_from_property_specs(ps)
                            )
                        rows.append(row)

                    notion_block = {
                        "type": "batch_preview",
                        "rows": rows,
                        "note": "Preview does not hit Notion. Final execution may still normalize select/status types based on DB schema.",
                    }
    except Exception:
        notion_block = None

    return {
        "ok": True,
        "read_only": True,
        "command": cmd_dump,
        "notion": notion_block,
        "review": review_block,
        "trace": {
            "canon": "execute_preview",
            "endpoint": "/api/execute/preview",
        },
    }


# ================================================================
# /api/proposals/execute
# ================================================================
@app.post("/api/proposals/execute")
async def execute_proposal(payload: ProposalExecuteInput):
    proposal = payload.proposal
    initiator = (payload.initiator or "ceo").strip() or "ceo"
    meta_in = payload.metadata if isinstance(payload.metadata, dict) else {}

    _, _, _, registry, orchestrator = _require_boot_services()

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

    cr = None
    if isinstance(proposal_meta, dict):
        cr = proposal_meta.get("confidence_risk")
    if cr is None and isinstance(meta_in, dict):
        cr = meta_in.get("confidence_risk")

    if isinstance(cr, dict):
        merged_md["confidence_risk"] = cr

    ai_command = _unwrap_proposal_wrapper_or_raise(
        command=proposal_cmd,
        intent=proposal_intent,
        params=proposal_params if isinstance(proposal_params, dict) else {},
        initiator=initiator,
        read_only=False,
        metadata=merged_md,
    )

    # Same post-unwrapping hard-block as /api/execute/raw.
    if (getattr(ai_command, "intent", None) in _HARD_READ_ONLY_INTENTS) or (
        getattr(ai_command, "command", None) in _HARD_READ_ONLY_INTENTS
    ):
        execution_id = _ensure_execution_id(ai_command)
        return {
            "status": "COMPLETED",
            "execution_state": "COMPLETED",
            "read_only": True,
            "execution_id": execution_id,
            "approval_id": None,
            "text": "Need more information before executing. Please answer the questions, then retry.",
            "command": getattr(ai_command, "command", None),
            "intent": getattr(ai_command, "intent", None),
            "params": getattr(ai_command, "params", None)
            if isinstance(getattr(ai_command, "params", None), dict)
            else {},
            "proposed_commands": [],
            "trace": {
                "canon": "proposals_execute_hard_block_after_unwrap",
                "endpoint": "/api/proposals/execute",
            },
        }

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
    orchestrator.registry.register(ai_command)
    registry.register(ai_command)

    result = await orchestrator.execute(ai_command)
    if isinstance(result, dict):
        result.setdefault("approval_id", approval_id)
        result.setdefault("execution_id", execution_id)
        result.setdefault("status", "BLOCKED")
    return result


# ================================================================
# NOTION READ — READ ONLY (NO APPROVAL / NO EXECUTION)
# ================================================================
@app.post("/api/notion/read", response_model=NotionReadResponse)
async def notion_read(payload: Any = Body(None)) -> Any:
    def _model_to_dict(m: NotionReadResponse) -> Dict[str, Any]:
        if hasattr(m, "model_dump"):
            try:
                d = m.model_dump()  # type: ignore[attr-defined]
                return d if isinstance(d, dict) else {}
            except Exception:
                pass
        try:
            d2 = m.dict()  # type: ignore[attr-defined]
            return d2 if isinstance(d2, dict) else {}
        except Exception:
            return {}

    def _json(resp: NotionReadResponse) -> JSONResponse:
        return JSONResponse(
            content=_model_to_dict(resp),
            media_type="application/json; charset=utf-8",
        )

    def _resp_err(msg: str) -> JSONResponse:
        return _json(
            NotionReadResponse(
                ok=False,
                title=None,
                notion_url=None,
                content_markdown=None,
                error=msg,
            )
        )

    if payload is None:
        return _resp_err("Body must be an object")
    if not isinstance(payload, dict):
        return _resp_err("Body must be an object")

    mode0 = payload.get("mode")
    if not isinstance(mode0, str) or not mode0.strip():
        return _resp_err("Field 'mode' is required")
    mode0 = mode0.strip()

    if mode0 != "page_by_title":
        return _resp_err("Unsupported mode. Allowed: 'page_by_title'")

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return _resp_err("Field 'query' is required")
    query = query.strip()

    try:
        from services.notion_read_service import read_page_as_markdown

        res = await read_page_as_markdown(query)
        if not isinstance(res, dict):
            return _resp_err("Notion read failed: invalid service response")

        title = res.get("title") if isinstance(res.get("title"), str) else ""
        url = res.get("url") if isinstance(res.get("url"), str) else ""
        md = (
            res.get("content_markdown")
            if isinstance(res.get("content_markdown"), str)
            else ""
        )

        title = (title or "").strip()
        url = (url or "").strip()
        md = (md or "").strip()

        if not title and not url and not md:
            return _json(
                NotionReadResponse(
                    ok=False,
                    title=None,
                    notion_url=None,
                    content_markdown=None,
                    error=f"Page not found for query: {query}",
                )
            )

        return _json(
            NotionReadResponse(
                ok=True,
                title=title or None,
                notion_url=url or None,
                content_markdown=md or None,
                error=None,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _resp_err(f"Notion read failed: {exc}")


# ================================================================
# NOTION OPS — LIST DATABASES (READ ONLY)
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
    if payload is None:
        return {"results": []}

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

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
                    "response": res,
                }
            ]
        }

    queries = payload.get("queries")
    if queries is None:
        queries = []
    if not isinstance(queries, list):
        raise HTTPException(status_code=400, detail="queries must be a list")

    if len(queries) == 0:
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
                "response": res,
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

    if not isinstance(result.get("proposed_commands"), list):
        result["proposed_commands"] = []

    tr2 = _ensure_dict(result.get("trace"))
    if not isinstance(tr2.get("confidence_risk"), dict):
        tr2["confidence_risk"] = _compute_confidence_risk_block(
            prompt=cleaned_text.strip(),
            trace=tr2,
            proposed_commands=_ensure_list(result.get("proposed_commands")),
        )
    result["trace"] = tr2

    # === CANON PATCH: propagate confidence/risk into proposal payloads ===
    cr = tr2.get("confidence_risk")
    if isinstance(cr, dict):
        for pc in result.get("proposed_commands", []):
            if not isinstance(pc, dict):
                continue

            ps = pc.get("payload_summary")
            if not isinstance(ps, dict):
                ps = {}
                pc["payload_summary"] = ps

            ps.setdefault("confidence_score", cr.get("confidence_score"))
            ps.setdefault("assumption_count", cr.get("assumption_count", 0))
            ps.setdefault("recommendation_type", "OPERATIONAL")

            rl = cr.get("risk_level")
            if isinstance(rl, str):
                pc.setdefault(
                    "risk",
                    {"low": "LOW", "medium": "MED", "high": "HIGH"}.get(rl, "LOW"),
                )

            # PHASE A FIX: also propagate to proposal metadata
            md0 = pc.get("metadata")
            if not isinstance(md0, dict):
                md0 = {}
                pc["metadata"] = md0
            md0.setdefault("confidence_risk", cr)
    # === END CANON PATCH ===

    # === CANON STABILITY PATCH: ensure args.prompt exists ===
    for pc in result.get("proposed_commands", []):
        if not isinstance(pc, dict):
            continue

        if pc.get("command") == "ceo.command.propose":
            args = pc.get("args")
            if not isinstance(args, dict):
                args = {}
                pc["args"] = args

            if "prompt" not in args or not isinstance(args.get("prompt"), str):
                args["prompt"] = cleaned_text.strip()
    # === END CANON STABILITY PATCH ===

    # ? PATCH: fallback proposal injection when write-like but proposed_commands empty
    # If ceo-console agent says "I propose approval" but returns no proposed_commands,
    # inject a canonical proposal wrapper so UI can execute it via /api/execute/raw.
    if (
        isinstance(result.get("proposed_commands"), list)
        and len(result.get("proposed_commands")) == 0
    ):
        _inject_fallback_proposed_commands(result, prompt=cleaned_text.strip())

    # === POST-FALLBACK STABILITY PATCH: ensure args.prompt exists ===
    for pc in result.get("proposed_commands", []):
        if not isinstance(pc, dict):
            continue
        if pc.get("command") == "ceo.command.propose":
            args = pc.get("args")
            if not isinstance(args, dict):
                args = {}
                pc["args"] = args
            if (
                "prompt" not in args
                or not isinstance(args.get("prompt"), str)
                or not args.get("prompt")
            ):
                args["prompt"] = cleaned_text.strip()
    # === END POST-FALLBACK STABILITY PATCH ===
    # === POST-FALLBACK EXECUTION PATCH: ensure params.prompt + metadata.wrapper.prompt ===
    for pc in result.get("proposed_commands", []):
        if not isinstance(pc, dict):
            continue
        if pc.get("command") != "ceo.command.propose":
            continue

        # ensure args.prompt (already for happy-path script)
        args = pc.get("args")
        if not isinstance(args, dict):
            args = {}
            pc["args"] = args
        if not isinstance(args.get("prompt"), str) or not args.get("prompt"):
            args["prompt"] = cleaned_text.strip()

        # ensure params.prompt (required by /api/proposals/execute)
        params = pc.get("params")
        if not isinstance(params, dict):
            params = {}
            pc["params"] = params
        if not isinstance(params.get("prompt"), str) or not params.get("prompt"):
            params["prompt"] = args.get("prompt") or cleaned_text.strip()

        # ensure metadata.wrapper.prompt (also accepted by gateway)
        md = pc.get("metadata")
        if not isinstance(md, dict):
            md = {}
            pc["metadata"] = md
        wrapper = md.get("wrapper")
        if not isinstance(wrapper, dict):
            wrapper = {}
            md["wrapper"] = wrapper
        if not isinstance(wrapper.get("prompt"), str) or not wrapper.get("prompt"):
            wrapper["prompt"] = (
                params.get("prompt") or args.get("prompt") or cleaned_text.strip()
            )
    # === END POST-FALLBACK EXECUTION PATCH ===

    # === POST-FALLBACK CANON PATCH: ensure payload_summary fields on injected proposals ===
    cr2 = _ensure_dict(_ensure_dict(result.get("trace")).get("confidence_risk"))
    if isinstance(cr2, dict):
        for pc in result.get("proposed_commands", []):
            if not isinstance(pc, dict):
                continue

            ps = pc.get("payload_summary")
            if not isinstance(ps, dict):
                ps = {}
                pc["payload_summary"] = ps

            cs = ps.get("confidence_score", None)
            if cs is None:
                cs2 = cr2.get("confidence_score")
                cs = float(cs2) if isinstance(cs2, (int, float)) else 0.50
            if cs < 0.0:
                cs = 0.0
            if cs > 1.0:
                cs = 1.0
            ps["confidence_score"] = float(cs)

            ac = ps.get("assumption_count", None)
            if not isinstance(ac, int) or ac < 0:
                ac2 = cr2.get("assumption_count")
                ac = int(ac2) if isinstance(ac2, int) and ac2 >= 0 else 0
            ps["assumption_count"] = ac

            rt = ps.get("recommendation_type")
            if not isinstance(rt, str) or not rt.strip():
                ps["recommendation_type"] = "OPERATIONAL"
    # === END POST-FALLBACK CANON PATCH ===
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

    knowledge_snapshot = {
        "ready": ks.get("ready", False),
        "last_sync": ks.get("last_sync"),
        "trace": ks.get("trace", {}),
    }

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
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "failed_count": len(failed),
            "completed_count": len(completed),
            "pending": pending,
        },
        "knowledge_snapshot": knowledge_snapshot,
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
app.include_router(notion_ops_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(alerting_router, prefix="/api")
if _chat_router is not None:
    app.include_router(_chat_router, prefix="/api")  # /api/chat
    app.include_router(_chat_router, prefix="")  # /chat alias
else:
    logger.warning("chat_router is None — chat endpoints disabled")
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
