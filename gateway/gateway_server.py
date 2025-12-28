# gateway/gateway_server.py
# ruff: noqa: E402
# FULL FILE — Gateway server for adnan-backend-v4

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ================================================================
# Logging
# ================================================================
logger = logging.getLogger("gateway")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())

# ================================================================
# Repo layout
# ================================================================
REPO_ROOT = Path(__file__).resolve().parents[1]

# REACT BUILD OUTPUT (Vite default):
#   gateway/frontend/dist/index.html
#   gateway/frontend/dist/assets/...
FRONTEND_DIST_DIR = REPO_ROOT / "gateway" / "frontend" / "dist"


def _agents_registry_path() -> Path:
    """
    Registry file for agents (if present).
    """
    return REPO_ROOT / "agents_registry.json"


# ================================================================
# Imports of internal modules (routers/services)
# ================================================================
# NOTE: ruff: noqa E402 because path/import ordering sometimes matters in this repo
try:
    from routers import ceo_console_module  # type: ignore
    from routers import coo_translation_service  # type: ignore
    from routers.approvals_state import get_approval_state  # type: ignore
    from routers.ceo_command_router import ProposedCommand  # type: ignore
    from routers.notion_ops_router import _guard_write_bulk, _validate_bulk_items  # type: ignore
except Exception as e:
    logger.exception("Failed importing internal routers/services: %s", e)
    raise

# ================================================================
# FastAPI app
# ================================================================
app = FastAPI(title="Adnan Backend V4 Gateway", version="4.0")

# CORS (keep wide for now, as per existing code)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    proposal: ProposedCommand
    initiator: str = "ceo"
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ================================================================
# Helpers
# ================================================================
def _preprocess_ceo_nl_input(raw: str, smart_context: Optional[Dict[str, Any]] = None) -> str:
    """
    Existing preprocessing logic stays as-is; keep it minimal.
    """
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    return text


def _ensure_execution_id(ai_command: Any) -> str:
    execution_id = getattr(ai_command, "execution_id", None) or getattr(ai_command, "id", None)
    if isinstance(execution_id, str) and execution_id.strip():
        return execution_id.strip()
    eid = str(uuid.uuid4())
    try:
        ai_command.execution_id = eid
    except Exception:
        pass
    return eid


def _extract_text_from_payload(payload: Any) -> str:
    """
    Extracts text from different possible payload shapes.
    Supported keys:
      - input_text
      - text
      - message
      - prompt
    Also supports nested: payload["data"][...]
    """
    if isinstance(payload, dict):
        for key in ("input_text", "text", "message", "prompt"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                return v
        data_obj = payload.get("data")
        if isinstance(data_obj, dict):
            for key in ("input_text", "text", "message", "prompt"):
                v = data_obj.get(key)
                if isinstance(v, str) and v.strip():
                    return v
    return ""


def _extract_smart_context(payload: Any) -> Optional[Dict[str, Any]]:
    """
    Frontend/clients mogu slati kontekst pod raznim ključevima.
    Podržavamo: smart_context | context | context_hint | ui_context_hint
    (i iste ključeve unutar payload["data"]).
    """
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

    data_obj = payload.get("data")
    if isinstance(data_obj, dict):
        return _pick(data_obj)

    return None


def _extract_source(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "ceo_dashboard"
    s = payload.get("source") or payload.get("initiator")
    if isinstance(s, str) and s.strip():
        return s.strip()
    data_obj = payload.get("data")
    if isinstance(data_obj, dict):
        s2 = data_obj.get("source") or data_obj.get("initiator")
        if isinstance(s2, str) and s2.strip():
            return s2.strip()
    return "ceo_dashboard"


# ================================================================
# Health
# ================================================================
@app.get("/health")
async def health():
    return {"status": "ok"}


# ================================================================
# API EXECUTE
# ================================================================
@app.post("/api/execute")
async def execute_command(payload: ExecuteInput):
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
        execution_id=execution_id,
        initiator=getattr(ai_command, "initiator", None) or "ceo",
        metadata={"source": "api_execute"},
    )

    return {
        "status": "PENDING_APPROVAL",
        "execution_state": "PENDING_APPROVAL",
        "execution_id": execution_id,
        "approval_id": approval.approval_id,
        "proposal": jsonable_encoder(ai_command),
    }


@app.post("/api/execute/raw")
async def execute_raw_command(payload: ExecuteRawInput):
    """
    Existing raw execute handler.
    """
    approval_state = get_approval_state()
    execution_id = str(uuid.uuid4())

    approval = approval_state.create(
        command=payload.command,
        execution_id=execution_id,
        initiator="system",
        metadata={"intent": payload.intent, "params": payload.params},
    )

    return {
        "status": "PENDING_APPROVAL",
        "execution_state": "PENDING_APPROVAL",
        "execution_id": execution_id,
        "approval_id": approval.approval_id,
        "proposal": {
            "command": payload.command,
            "intent": payload.intent,
            "params": payload.params,
        },
    }


@app.post("/api/execute/proposal")
async def execute_proposal(payload: ProposalExecuteInput):
    """
    Execute an already proposed command (post-approval flows).
    """
    proposal = payload.proposal
    initiator = payload.initiator

    approval_state = get_approval_state()
    execution_id = str(uuid.uuid4())

    approval = approval_state.create(
        command=getattr(proposal, "command", None) or "execute",
        execution_id=execution_id,
        initiator=initiator,
        metadata=payload.metadata or {},
    )

    return {
        "status": "PENDING_APPROVAL",
        "execution_state": "PENDING_APPROVAL",
        "execution_id": execution_id,
        "approval_id": approval.approval_id,
        "proposal": jsonable_encoder(proposal),
    }


# ================================================================
# CEO COMMAND CORE (shared by multiple aliases)
# ================================================================
async def _ceo_command_core(payload_dict: Dict[str, Any]) -> JSONResponse:
    raw_text = _extract_text_from_payload(payload_dict)
    smart_context = _extract_smart_context(payload_dict)
    source = _extract_source(payload_dict)

    # session_id (UI može poslati session_id na root-u ili unutar data)
    session_id = payload_dict.get("session_id")
    if session_id is None and isinstance(payload_dict.get("data"), dict):
        session_id = payload_dict["data"].get("session_id")

    cleaned_text = _preprocess_ceo_nl_input(raw_text, smart_context)

    if not isinstance(cleaned_text, str) or not cleaned_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Missing text. Provide one of: input_text | text | message | prompt (optionally under data).",
        )

    req = ceo_console_module.CEOCommandRequest(
        text=cleaned_text.strip(),
        initiator=source,
        session_id=session_id,
        context_hint=smart_context,
    )

    result_obj = await ceo_console_module.ceo_command(req)
    result = jsonable_encoder(result_obj)

    if not isinstance(result, dict):
        return JSONResponse({"ok": True, "result": result})

    return JSONResponse(result)


@app.post("/api/ceo/command")
async def ceo_dashboard_command_api(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


# Alias za stare frontende: "/api/ceo-console/command"
@app.post("/api/ceo-console/command")
async def ceo_console_command_api(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


# DEBUG alias (no collision, always available)
@app.post("/api/ceo-console/command/internal")
async def ceo_console_command_api_internal(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


@app.post("/ceo/command")
async def ceo_dashboard_command_public(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


# ================================================================
# NOTION OPS (bulk)
# ================================================================
@app.post("/notion-ops/bulk/create")
async def notion_bulk_create(request: Request, payload: Dict[str, Any] = Body(...)):
    _guard_write_bulk(request)

    items = _validate_bulk_items(payload.get("items"))

    created: List[Dict[str, Any]] = []
    for it in items:
        created.append(it)

    return {"ok": True, "created": created}


# ================================================================
# Static (React dist)
# (servira /, /assets/* i SPA deep-link fallback)
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
