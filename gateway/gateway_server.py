# ================================================================
# SYSTEM VERSION (V1.1 — VERZIJA C)
# ================================================================
import os
import logging
import uuid
import re
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
# WEEKLY MEMORY SERVICE (CEO DASHBOARD)
# ================================================================
from services.weekly_memory_service import get_weekly_memory_service

# ================================================================
# ROUTERS
# ================================================================
from routers.audit_router import router as audit_router
from routers.adnan_ai_router import router as adnan_ai_router
from routers.ai_ops_router import ai_ops_router
from routers.ceo_console_router import router as ceo_console_router

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
app.include_router(ceo_console_router, prefix="/api")

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

    Cilj:
    - ispraviti grešku "Kreiraj cilj ..." gdje se glagol lijepi u GOAL NAME
    - NE uvodi nove side-effecte, samo čisti tekst za COOTranslationService

    Pravila:
    - ako smart_context.command_type == "create_goal" i postoji goal.name,
      tekst koji šaljemo COO-u počinje nazivom cilja (bez "kreiraj cilj")
    - fallback: regex strip samo prefiksa "kreiraj cilj" / "napravi cilj" / "create cilj"
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

    # fallback: samo skidamo komandni prefiks, ostatak ostaje identičan
    cleaned = re.sub(
        r"^(?i)(kreiraj|napravi|create)\s+cilj[a]?\s*[:\-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    return cleaned or text


def _extract_candidate_lists(container: Any) -> List[Any]:
    """
    Best-effort ekstrakcija potencijalnih weekly-priority listi
    iz snapshot strukture (koju puni NotionOpsAgent).

    - ne mijenja state
    - ne pretpostavlja tačan shape; samo traži list-e ugniježdene u dict-ove
    """
    items: List[Any] = []
    if isinstance(container, list):
        return container

    if isinstance(container, dict):
        for value in container.values():
            if isinstance(value, list):
                items.extend(value)
            elif isinstance(value, dict):
                items.extend(_extract_candidate_lists(value))

    return items


def _pick_first(d: Dict[str, Any], *keys: str) -> Optional[Any]:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _normalize_priority_item(raw: Any) -> Dict[str, Any]:
    """
    Normalize jedan raw zapis iz WeeklyMemoryService u uniformnu CEO tabelu:

    {
        "type": "...",
        "name": "...",
        "status": "...",
        "priority": "...",
        "due_period": "...",
        "raw": {...}  # za debug / audit u JSON-u
    }
    """
    if not isinstance(raw, dict):
        return {
            "type": None,
            "name": str(raw),
            "status": None,
            "priority": None,
            "due_period": None,
            "raw": raw,
        }

    type_val = _pick_first(raw, "type", "Type", "tip", "Tip", "kind", "Kind")
    name_val = _pick_first(
        raw, "name", "Name", "title", "Title", "goal_name", "Goal", "Naziv", "naziv"
    )
    status_val = _pick_first(raw, "status", "Status", "state", "State")
    priority_val = _pick_first(
        raw, "priority", "Priority", "prioritet", "Prioritet", "prio", "Prio"
    )
    due_val = _pick_first(
        raw,
        "due",
        "Due",
        "date",
        "Date",
        "deadline",
        "Deadline",
        "period",
        "Period",
        "week",
        "Week",
        "range",
        "Range",
    )

    return {
        "type": type_val,
        "name": name_val or str(raw),
        "status": status_val,
        "priority": priority_val,
        "due_period": due_val,
        "raw": raw,
    }


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
# /ceo/command — CEO DASHBOARD → COO (NL + SMART CONTEXT)
# ================================================================
@app.post("/ceo/command")
async def ceo_dashboard_command(payload: CeoCommandInput):
    """
    CEO Dashboard entrypoint.

    - koristi isti kanonski pipeline kao /api/execute (BLOCKED → APPROVAL → EXECUTED)
    - prima raw tekst + smart_context (hint iz frontenda)
    - smart_context se koristi SAMO za poboljšanje parsiranja, ne mijenja governance
    """
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
        # novi blok za CEO Weekly Memory (AI summary) – best-effort iz KnowledgeSnapshot-a
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
# CEO WEEKLY MEMORY (READ-ONLY, IN-MEMORY CACHE)
# ================================================================
@app.get("/api/ceo/console/weekly-memory")
async def ceo_weekly_memory():
    """
    Read-only API za WEEKLY PRIORITY MEMORY karticu.

    Vraća striktno ono što je NotionOpsAgent zadnje upisao
    u WeeklyMemoryService (npr. nakon KPI weekly summary workflowa).
    """
    wm_service = get_weekly_memory_service()
    wm_snapshot = wm_service.get_snapshot()
    return {"weekly_memory": _to_serializable(wm_snapshot)}


# ================================================================
# CEO WEEKLY PRIORITY LIST (FLATTENED ZA FRONTEND TABELU)
# ================================================================
@app.get("/ceo/weekly-priority-memory")
async def ceo_weekly_priority_memory():
    """
    Novi CEO Dashboard endpoint:

    - čisto READ, bez side-effects
    - flatten-a WeeklyMemoryService snapshot u listu stavki:
      [{type, name, status, priority, due_period, raw}, ...]
    - frontend koristi type/name/status/priority/due_period za tabelu
    """
    wm_service = get_weekly_memory_service()
    wm_snapshot = wm_service.get_snapshot()

    candidates = _extract_candidate_lists(wm_snapshot)
    items = [_normalize_priority_item(raw) for raw in candidates]

    return {"items": items}


# ================================================================
# CEO AGENTS (READ-ONLY, STATIC + FUTURE DYNAMIC)
# ================================================================
@app.get("/ceo/agents")
async def ceo_agents():
    """
    Read-only lista agenata dostupnih CEO-u.

    Za sada statična (bez side-effects), može se proširiti da čita
    iz ExecutionRegistry / agent registrija kada bude spremno.
    """
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


# ================================================================
# LEGACY ROUTES (BACKWARD COMPATIBILITY ZA STARI FRONTEND)
# ================================================================
@app.get("/ceo-console/snapshot", include_in_schema=False)
async def legacy_ceo_console_snapshot():
    """
    Legacy ruta za stari frontend.
    Proksira na kanonski /api/ceo/console/snapshot da ne baca 500.
    """
    return await ceo_console_snapshot()


@app.get("/ceo-console/weekly-memory", include_in_schema=False)
async def legacy_ceo_weekly_memory():
    """
    Legacy ruta za stari frontend.
    Proksira na kanonski /api/ceo/console/weekly-memory.
    """
    return await ceo_weekly_memory()


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
