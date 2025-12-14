# ================================================================
# SYSTEM VERSION (V1.1 — VERZIJA C)
# ================================================================
import os
import time
import logging
from fastapi import FastAPI, Request
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
# OS SAFETY CONTROLS
# ================================================================
OS_ENABLED = os.getenv("OS_ENABLED", "true").lower() == "true"
OPS_SAFE_MODE = os.getenv("OPS_SAFE_MODE", "false").lower() == "true"

_LAST_CALL_TS = 0.0
MIN_INTERVAL_SECONDS = 0.5

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
# INITIAL LOAD
# ================================================================
load_dotenv(".env")

identity = load_identity()
mode = load_mode()
state = load_state()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

app = FastAPI()

# ================================================================
# ROOT + HEALTH (PLATFORM ONLY — NO CSI)
# ================================================================
@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/health")
async def health_check():
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
    conversation_state_service,  # 🔒 CSI SINGLETON
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
# GLOBAL ERROR HANDLER
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
# STARTUP
# ================================================================
@app.on_event("startup")
async def startup_event():
    logger.info(">> Startup: syncing Notion knowledge snapshot")
    await notion_service.sync_knowledge_snapshot()

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

# ================================================================
# MODELS
# ================================================================
class CommandRequest(BaseModel):
    command: str
    payload: dict

# ================================================================
# /ops/execute — CSI-CENTRIC PIPELINE (FINAL)
# ================================================================
@app.post("/ops/execute")
async def execute(req: CommandRequest):
    global _LAST_CALL_TS

    # ============================================================
    # INPUT NORMALIZATION (KANONSKI FIX)
    # ============================================================
    user_text = (
        req.payload.get("text")
        or req.payload.get("input")
        or ""
    ).strip()

    csi = conversation_state_service.get()

    # ============================================================
    # RATE LIMIT
    # ============================================================
    now = time.time()
    if now - _LAST_CALL_TS < MIN_INTERVAL_SECONDS:
        awareness = awareness_service.build_snapshot(
            command=None,
            csi_state=csi,
        )
        return response_formatter.format(
            intent=req.command,
            confidence=1.0,
            csi_state=csi,
            execution_result={"success": False},
            awareness=awareness,
            request_id=None,
        )
    _LAST_CALL_TS = now

    # ============================================================
    # ORCHESTRATION (READ / DECISION ONLY)
    # ============================================================
    command = AICommand(
        command=req.command,
        input=req.payload,
        identity_snapshot=identity,
        state_snapshot=state,
        mode_snapshot=mode,
    )

    orch = await orchestrator.run(user_text)
    decision_output = orch.get("result", {})

    awareness = awareness_service.build_snapshot(
        command=command,
        csi_state=conversation_state_service.get(),
        decision=decision_output,
    )

    execution_result = None

    # ============================================================
    # EXECUTION PHASE (CSI PUBLIC API ONLY)
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
