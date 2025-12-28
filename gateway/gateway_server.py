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

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ================================================================
# Logging
# ================================================================
logger = logging.getLogger("gateway")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())

# ================================================================
# Repo layout
# ================================================================
REPO_ROOT = Path(__file__).resolve().parents[1]

# Vite build output:
#   gateway/frontend/dist/index.html
#   gateway/frontend/dist/assets/...
FRONTEND_DIST_DIR = REPO_ROOT / "gateway" / "frontend" / "dist"

# ================================================================
# Optional token enforcement
# ================================================================
def _enforce_ceo_token_if_enabled(request: Request) -> None:
    enabled = (os.environ.get("CEO_TOKEN_ENFORCEMENT") or "").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return

    expected = (os.environ.get("CEO_APPROVAL_TOKEN") or "").strip()
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


# ================================================================
# Lifespan (keeps original structure)
# ================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Any startup hooks here if your code uses them elsewhere
    yield
    # Any shutdown hooks here if needed


app = FastAPI(title="Adnan Backend V4 Gateway", version="4.0", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================================
# Internal routers/services
# ================================================================
# Keep these imports aligned with your repo structure
from routers.chat_router import build_chat_router
from routers.notion_ops_router import build_notion_ops_router
from routers.sync_router import build_sync_router
from routers.ai_router import build_ai_router
from routers.ai_ops_router import build_ai_ops_router
from routers.tasks_router import build_tasks_router
from routers.projects_router import build_projects_router
from routers.goals_router import build_goals_router
from routers.metrics_router import build_metrics_router
from routers.alerting_router import build_alerting_router
from routers.audit_router import build_audit_router
from routers.voice_router import build_voice_router
from routers.sop_query_router import build_sop_query_router
from routers.nlp_router import build_nlp_router
from routers.ai_summary_router import build_ai_summary_router
from routers.agents_router import build_agents_router
from routers.adnan_ai_router import build_adnan_ai_router
from routers.adnan_ai_query_router import build_adnan_ai_query_router
from routers.adnan_ai_data_router import build_adnan_ai_data_router
from routers.adnan_ai_action_router import build_adnan_ai_action_router

from services.agent_router_service import AgentRouterService
from services.ceo_console_snapshot_service import CEOConsoleSnapshotService
from services.memory_weekly_service import WeeklyMemoryService

# IMPORTANT: correct module import (fixes your ImportError)
import routers.ceo_console_router as ceo_console_module


# ================================================================
# Wire internal routers
# ================================================================
agent_router = AgentRouterService()
snapshot_service = CEOConsoleSnapshotService()
weekly_memory_service = WeeklyMemoryService()

# Canon chat router mounted under /chat (as defined in router)
app.include_router(build_chat_router(agent_router))

# Other API routers
app.include_router(build_notion_ops_router())
app.include_router(build_sync_router())
app.include_router(build_ai_router())
app.include_router(build_ai_ops_router())
app.include_router(build_tasks_router())
app.include_router(build_projects_router())
app.include_router(build_goals_router())
app.include_router(build_metrics_router())
app.include_router(build_alerting_router())
app.include_router(build_audit_router())
app.include_router(build_voice_router())
app.include_router(build_sop_query_router())
app.include_router(build_nlp_router())
app.include_router(build_ai_summary_router())
app.include_router(build_agents_router())
app.include_router(build_adnan_ai_router())
app.include_router(build_adnan_ai_query_router())
app.include_router(build_adnan_ai_data_router())
app.include_router(build_adnan_ai_action_router())


# ================================================================
# Health
# ================================================================
@app.get("/health")
async def health():
    return {"status": "ok"}


# ================================================================
# CEO console helpers
# ================================================================
def _preprocess_ceo_nl_input(raw: str, smart_context: Optional[Dict[str, Any]] = None) -> str:
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    return text


def _extract_text_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
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
    return "ceo_dashboard"


# ================================================================
# CEO Command Core
# ================================================================
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

    # session_id: UI može poslati session_id na root-u ili unutar data
    session_id = payload_dict.get("session_id")
    if session_id is None and isinstance(payload_dict.get("data"), dict):
        session_id = payload_dict["data"].get("session_id")

    req = ceo_console_module.CEOCommandRequest(
        text=cleaned_text.strip(),
        initiator=source,
        session_id=session_id,
        context_hint=smart_context,
    )

    result_obj = await ceo_console_module.ceo_command(req)
    result = jsonable_encoder(result_obj)

    if not isinstance(result, dict):
        result = {"ok": True, "summary": str(result_obj), "trace": {}}

    if not result.get("text"):
        result["text"] = result.get("summary") or ""

    tr = result.get("trace")
    if isinstance(tr, dict):
        tr["normalized_input_text"] = cleaned_text.strip()
        tr["normalized_input_source"] = source
        tr["normalized_input_has_smart_context"] = bool(smart_context)
        tr["normalized_input_session_id_present"] = bool(session_id)

    return JSONResponse(result)


# ================================================================
# CEO API routes (compat + canonical)
# ================================================================
@app.post("/api/ceo/command")
async def ceo_dashboard_command_api(request: Request, payload: Dict[str, Any] = Body(...)):
    _enforce_ceo_token_if_enabled(request)
    return await _ceo_command_core(payload)


@app.post("/api/ceo-console/command")
async def ceo_console_command_api(request: Request, payload: Dict[str, Any] = Body(...)):
    _enforce_ceo_token_if_enabled(request)
    return await _ceo_command_core(payload)


@app.post("/api/ceo-console/command/internal")
async def ceo_console_command_api_internal(payload: Dict[str, Any] = Body(...)):
    return await _ceo_command_core(payload)


@app.get("/api/ceo-console/status")
async def ceo_console_status():
    return {"ok": True, "status": "ready"}


@app.get("/api/ceo/console/snapshot")
async def ceo_console_snapshot():
    snap = snapshot_service.get_snapshot()
    return jsonable_encoder(snap)


@app.get("/api/ceo/console/weekly-memory")
async def ceo_console_weekly_memory():
    data = weekly_memory_service.get_weekly_memory()
    return jsonable_encoder(data)


# ================================================================
# Static frontend (Vite dist) + SPA
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
