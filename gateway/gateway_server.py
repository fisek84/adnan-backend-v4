# ================================================================
# SYSTEM VERSION (V1.1 — VERZIJA C)
# ================================================================
import os
import time
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

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
_LAST_CALL_TS = 0.0
MIN_INTERVAL_SECONDS = 0.5

# ================================================================
# LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("gateway")

# ================================================================
# CORE MODELS / SERVICES
# ================================================================
from models.ai_command import AICommand
from services.conversation_state_service import ConversationStateService
from services.awareness_service import AwarenessService
from services.response_formatter import ResponseFormatter

# ================================================================
# DECISION / ORCHESTRATION
# ================================================================
from services.decision_engine.context_orchestrator import ContextOrchestrator

# ================================================================
# IDENTITY / MODE / STATE
# ================================================================
from services.identity_loader import load_identity
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state

# ================================================================
# EXECUTION
# ================================================================
from services.action_workflow_service import ActionWorkflowService

# ================================================================
# NOTION / SOP (READ-ONLY SNAPSHOT)
# ================================================================
from services.notion_service import NotionService

# ================================================================
# INITIAL LOAD (FAIL FAST)
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
# ROOT + HEALTH (PLATFORM ONLY)
# ================================================================
@app.get("/")
async def root():
    return {
        "status": "ok",
        "system": SYSTEM_NAME,
        "version": VERSION,
        "release_channel": RELEASE_CHANNEL,
        "arch_lock": ARCH_LOCK,
        "safe_mode": OPS_SAFE_MODE,
        "boot_ready": _BOOT_READY,
        "read_only": True,
    }

@app.get("/health")
async def health_check():
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail="System not ready")
    return {"status": "ok"}

# ================================================================
# SINGLETON SERVICES (KANON)
# ================================================================
conversation_state_service = ConversationStateService()
awareness_service = AwarenessService()
response_formatter = ResponseFormatter()

orchestrator = ContextOrchestrator(
    identity,
    mode,
    state,
    conversation_state_service,
)

workflow_service = ActionWorkflowService()

# ================================================================
# NOTION SERVICE
# ================================================================
notion_service = NotionService(
    api_key=os.getenv("NOTION_API_KEY"),
    goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
    tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
    projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID"),
)

# ================================================================
# GLOBAL ERROR HANDLER (SAFE)
# ================================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("GLOBAL ERROR")

    awareness = awareness_service.build_snapshot(
        command=None,
        csi_state=conversation_state_service.get(),
    )

    return JSONResponse(
        status_code=500,
        content=response_formatter.format(
            intent="system_error",
            confidence=1.0,
            csi_state=conversation_state_service.get(),
            execution_result={"success": False},
            awareness=awareness,
            request_id=None,
        ),
    )

# ================================================================
# STARTUP (DETERMINISTIC)
# ================================================================
@app.on_event("startup")
async def startup_event():
    global _BOOT_READY
    logger.info(">> Startup: syncing Notion knowledge snapshot")
    await notion_service.sync_knowledge_snapshot()
    _BOOT_READY = True
    logger.info("🟢 System boot completed. READY.")

# ================================================================
# CORS (LOCKED)
# ================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================================
# MODELS
# ================================================================
class CommandRequest(BaseModel):
    command: str
    payload: dict

# ================================================================
# /ops/execute — CSI-CENTRIC PIPELINE
# ================================================================
@app.post("/ops/execute")
async def execute(req: CommandRequest):
    global _LAST_CALL_TS

    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail="System not ready")

    if OPS_SAFE_MODE:
        raise HTTPException(status_code=403, detail="OPS_SAFE_MODE enabled")

    # ============================================================
    # RATE LIMIT
    # ============================================================
    now = time.time()
    if now - _LAST_CALL_TS < MIN_INTERVAL_SECONDS:
        awareness = awareness_service.build_snapshot(
            command=None,
            csi_state=conversation_state_service.get(),
        )
        return response_formatter.format(
            intent=req.command,
            confidence=1.0,
            csi_state=conversation_state_service.get(),
            execution_result={"success": False},
            awareness=awareness,
            request_id=None,
        )
    _LAST_CALL_TS = now

    # ============================================================
    # ORCHESTRATION
    # ============================================================
    command = AICommand(
        command=req.command,
        input=req.payload,
        identity_snapshot=identity,
        state_snapshot=state,
        mode_snapshot=mode,
    )

    user_text = (
        req.payload.get("text")
        or req.payload.get("input")
        or ""
    ).strip()

    orch = await orchestrator.run(user_text)
    decision_output = orch.get("result", {})

    awareness = awareness_service.build_snapshot(
        command=command,
        csi_state=conversation_state_service.get(),
        decision=decision_output,
    )

    execution_result = None

    # ============================================================
    # EXECUTION (STRICT)
    # ============================================================
    if decision_output.get("type") == "delegation":
        delegation = decision_output.get("delegation", {})
        cmd = delegation.get("command")
        payload = delegation.get("payload") or {}

        if cmd:
            conversation_state_service.set_executing(
                request_id=command.request_id
            )

            workflow = {
                "type": "workflow",
                "steps": [
                    {"directive": cmd, "params": payload}
                ],
            }

            execution_result = await workflow_service.execute_workflow(workflow)

            conversation_state_service.set_idle(
                request_id=command.request_id
            )

    return response_formatter.format(
        intent=req.command,
        confidence=1.0,
        csi_state=conversation_state_service.get(),
        decision=decision_output,
        execution_result=execution_result,
        awareness=awareness,
        request_id=command.request_id,
    )
