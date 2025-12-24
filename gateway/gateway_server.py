# ruff: noqa: E402
# gateway/gateway_server.py
# FULL FILE — zamijeni cijeli gateway_server.py ovim.
# (Phase 11: migrate startup to lifespan; fix OPS_SAFE_MODE flag; keep behavior)

# ================================================================
# SYSTEM VERSION (V1.1 — VERZIJA C)
# ================================================================
import os
import logging
import uuid
import re
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List

import httpx

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

NOTION_API_KEY = os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN")
NOTION_GOALS_DB_ID = os.getenv("NOTION_GOALS_DB_ID")
NOTION_TASKS_DB_ID = os.getenv("NOTION_TASKS_DB_ID")

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
# WEEKLY MEMORY SERVICE (CEO DASHBOARD)
# ================================================================
from services.weekly_memory_service import get_weekly_memory_service

# AI SUMMARY DB SERVICE (REALNO STANJE WEEKLY PRIORITY)
from services.ai_summary_service import get_ai_summary_service

# ================================================================
# ROUTERS
# ================================================================
from routers.audit_router import router as audit_router
from routers.adnan_ai_router import router as adnan_ai_router
from routers.ai_ops_router import ai_ops_router
from routers.ceo_console_router import router as ceo_console_router

# Phase 9: Metrics + Alerting dashboards (READ-ONLY)
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
    logger.critical("❌ OS_ENABLED=false — system will not start.")
    raise RuntimeError("OS is disabled by configuration.")

identity = load_identity()
mode = load_mode()
state = load_state()


# ================================================================
# LIFESPAN (PHASE 11)
# ================================================================
@asynccontextmanager
async def lifespan(_: FastAPI):
    global _BOOT_READY

    _BOOT_READY = False
    try:
        bootstrap_application()

        from services.notion_service import get_notion_service

        notion_service = get_notion_service()
        await notion_service.sync_knowledge_snapshot()

        _BOOT_READY = True
        logger.info("🟢 System boot completed. READY.")
        yield
    finally:
        _BOOT_READY = False


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
app.include_router(ceo_console_router, prefix="/api")

# Phase 9: dashboards (so /api/metrics/ and /api/alerting/ exist)
app.include_router(metrics_router, prefix="/api")
app.include_router(alerting_router, prefix="/api")

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


class CeoCommandInput(BaseModel):
    """
    CEO Dashboard → COO (NL input + opcioni smart_context).

    - Poštuje isti governance pipeline kao /api/execute
    - smart_context se koristi kao HINT, ne kao direktan write
    """

    input_text: str
    smart_context: Optional[Dict[str, Any]] = None
    source: str = "ceo_dashboard"


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


def _preprocess_ceo_nl_input(
    raw_text: str,
    smart_context: Optional[Dict[str, Any]],
) -> str:
    """
    Minimalni, deterministički preprocessing za CEO Dashboard NL input.
    """
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


# ================================================================
# NOTION HELPERS ZA GOALS/TASKS SNAPSHOT
# ================================================================
NOTION_VERSION = "2022-06-28"


async def _query_notion_db(
    db_id: Optional[str], page_size: int = 20
) -> List[Dict[str, Any]]:
    if not NOTION_API_KEY or not db_id:
        return []

    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    body: Dict[str, Any] = {"page_size": page_size}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
    return data.get("results", [])


def _extract_title(properties: Dict[str, Any]) -> Optional[str]:
    for prop in properties.values():
        if prop.get("type") == "title":
            pieces = prop.get("title") or []
            text = "".join(p.get("plain_text", "") for p in pieces).strip()
            if text:
                return text
    for prop in properties.values():
        if prop.get("type") == "rich_text":
            pieces = prop.get("rich_text") or []
            text = "".join(p.get("plain_text", "") for p in pieces).strip()
            if text:
                return text
    return None


def _extract_select(properties: Dict[str, Any], keywords: List[str]) -> Optional[str]:
    for name, prop in properties.items():
        lower_name = name.lower()
        if not any(k in lower_name for k in keywords):
            continue

        t = prop.get("type")
        if t == "status":
            v = prop.get("status")
            if v and v.get("name"):
                return v["name"]
        if t == "select":
            v = prop.get("select")
            if v and v.get("name"):
                return v["name"]
        if t == "multi_select":
            vals = prop.get("multi_select") or []
            if vals:
                return ", ".join(v.get("name", "") for v in vals if v.get("name"))
    return None


def _extract_date(properties: Dict[str, Any], keywords: List[str]) -> Optional[str]:
    for name, prop in properties.items():
        lower_name = name.lower()
        if not any(k in lower_name for k in keywords):
            continue
        if prop.get("type") == "date":
            d = prop.get("date") or {}
            return d.get("start") or d.get("end")
    for prop in properties.values():
        if prop.get("type") == "date":
            d = prop.get("date") or {}
            return d.get("start") or d.get("end")
    return None


async def _load_goals_summary() -> List[Dict[str, Any]]:
    try:
        rows = await _query_notion_db(NOTION_GOALS_DB_ID, page_size=50)
    except Exception as exc:
        logger.exception("Failed to query Goals DB from Notion: %s", exc)
        return []

    result: List[Dict[str, Any]] = []
    for row in rows:
        props = row.get("properties") or {}
        name = _extract_title(props) or "(bez naziva)"
        status = _extract_select(props, ["status", "stanje"])
        priority = _extract_select(props, ["prioritet", "priority"])
        deadline = _extract_date(props, ["due", "deadline", "rok", "datum"])
        result.append(
            {
                "name": name,
                "status": status or "-",
                "priority": priority or "-",
                "due_date": deadline or "-",
            }
        )
    return result


async def _load_tasks_summary() -> List[Dict[str, Any]]:
    try:
        rows = await _query_notion_db(NOTION_TASKS_DB_ID, page_size=50)
    except Exception as exc:
        logger.exception("Failed to query Tasks DB from Notion: %s", exc)
        return []

    result: List[Dict[str, Any]] = []
    for row in rows:
        props = row.get("properties") or {}
        name = _extract_title(props) or "(bez naziva)"
        status = _extract_select(props, ["status", "stanje"])
        priority = _extract_select(props, ["prioritet", "priority"])
        due = _extract_date(props, ["due", "deadline", "rok", "datum"])
        result.append(
            {
                "title": name,
                "status": status or "-",
                "priority": priority or "-",
                "due_date": due or "-",
            }
        )
    return result


# ================================================================
# /api/execute — CEO → COO (NL INPUT)
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
# /ceo/command — CEO DASHBOARD → COO (NL + SMART CONTEXT)
# ================================================================
@app.post("/ceo/command")
async def ceo_dashboard_command(payload: CeoCommandInput):
    cleaned_text = _preprocess_ceo_nl_input(
        raw_text=payload.input_text,
        smart_context=payload.smart_context,
    )

    ai_command = coo_translation_service.translate(
        raw_input=cleaned_text,
        source=payload.source or "ceo_dashboard",
        context={
            "mode": "execute",
            "smart_context": payload.smart_context,
            "original_text": payload.input_text,
        },
    )

    if not ai_command:
        raise HTTPException(400, "Could not translate input to command")

    _execution_registry.register(ai_command)

    approval_id = str(uuid.uuid4())

    approval_state = get_approval_state()
    approval_state._approvals[approval_id] = {
        "approval_id": approval_id,
        "execution_id": ai_command.execution_id,
        "status": "pending",
        "source": payload.source or "ceo_dashboard",
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
    approval_state = get_approval_state()
    approvals_map: Dict[str, Dict[str, Any]] = getattr(approval_state, "_approvals", {})
    approvals_list = list(approvals_map.values())

    pending = [a for a in approvals_list if a.get("status") == "pending"]
    approved = [a for a in approvals_list if a.get("status") == "approved"]
    rejected = [a for a in approvals_list if a.get("status") == "rejected"]
    failed = [a for a in approvals_list if a.get("status") == "failed"]
    completed = [a for a in approvals_list if a.get("status") == "completed"]

    ks = KnowledgeSnapshotService.get_snapshot()
    ks_dbs = ks.get("databases") or {}
    ai_summary_raw = ks_dbs.get("ai_summary")

    weekly_memory = None
    if isinstance(ai_summary_raw, list) and ai_summary_raw:
        latest_item = ai_summary_raw[0]

        title = None
        week_range = None
        short_summary = None
        notion_page_id = None
        notion_url = None

        if isinstance(latest_item, dict):
            title = latest_item.get("title") or latest_item.get("Name")
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

    goals_summary = await _load_goals_summary()
    tasks_summary = await _load_tasks_summary()

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
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "failed_count": len(failed),
            "pending": pending,
        },
        "knowledge_snapshot": {
            "ready": ks.get("ready"),
            "last_sync": ks.get("last_sync"),
        },
        "weekly_memory": _to_serializable(weekly_memory)
        if weekly_memory is not None
        else None,
        "goals_summary": goals_summary,
        "tasks_summary": tasks_summary,
    }

    return snapshot


@app.get("/ceo/console/snapshot")
async def ceo_console_snapshot_public():
    return await ceo_console_snapshot()


@app.get("/api/ceo/console/weekly-memory")
async def ceo_weekly_memory():
    wm_service = get_weekly_memory_service()
    wm_snapshot = wm_service.get_snapshot()
    return {"weekly_memory": _to_serializable(wm_snapshot)}


@app.get("/ceo/weekly-priority-memory")
async def ceo_weekly_priority_memory():
    try:
        service = get_ai_summary_service()
        items = service.get_this_week_priorities()
    except Exception as exc:
        logger.exception("Failed to load Weekly Priority Memory from AI SUMMARY DB")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load Weekly Priority Memory from AI SUMMARY DB: {exc}",
        ) from exc

    return {"items": [i.dict() for i in items]}


@app.get("/ceo/agents")
async def ceo_agents():
    agents = [
        {
            "id": "notion_ops_agent",
            "name": "Notion Ops Agent",
            "role": "executor",
            "status": "idle",
        },
        {
            "id": "ai_command_service",
            "name": "AI Command Service",
            "role": "system",
            "status": "ready",
        },
        {
            "id": "coo_translation_service",
            "name": "COO Translation Service",
            "role": "translation",
            "status": "ready",
        },
    ]
    return agents


@app.get("/ceo-console/snapshot", include_in_schema=False)
async def legacy_ceo_console_snapshot():
    return await ceo_console_snapshot()


@app.get("/ceo-console/weekly-memory", include_in_schema=False)
async def legacy_ceo_weekly_memory():
    return await ceo_weekly_memory()


@app.get("/")
async def serve_frontend():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.isfile(index_path):
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


@app.get("/health")
async def health_check():
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail="System not ready")
    return {"status": "ok"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("GLOBAL ERROR")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
