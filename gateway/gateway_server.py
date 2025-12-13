# ================================================================
# SYSTEM VERSION (V1.0 FREEZE MARKER)
# ================================================================
import os
import time

from system_version import (
    SYSTEM_NAME,
    VERSION,
    ARCH_LOCK,
    RELEASE_CHANNEL,
)

# ================================================================
# OS SAFETY CONTROLS (V1.0 HARDENING)
# ================================================================
OS_ENABLED = os.getenv("OS_ENABLED", "true").lower() == "true"
OPS_SAFE_MODE = os.getenv("OPS_SAFE_MODE", "false").lower() == "true"

_LAST_CALL_TS = 0.0
MIN_INTERVAL_SECONDS = 0.5

# ================================================================
# STANDARD IMPORTS
# ================================================================
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

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
from services.decision_engine.personality_engine import PersonalityEngine
from services.decision_engine.context_orchestrator import ContextOrchestrator

# ================================================================
# IDENTITY / MODE / STATE
# ================================================================
from services.identity_loader import load_identity
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state

# ================================================================
# EXECUTION / GOVERNANCE
# ================================================================
from services.action_workflow_service import ActionWorkflowService
from services.execution_governance_service import ExecutionGovernanceService

# ================================================================
# MEMORY
# ================================================================
from services.memory_service import MemoryService

# ================================================================
# NOTION (READ-ONLY SNAPSHOT)
# ================================================================
from services.notion_service import NotionService

# ================================================================
# ROUTERS
# ================================================================
from routers.voice_router import router as voice_router
from routers.adnan_ai_router import router as adnan_ai_router
from routers.metrics_router import router as metrics_router
from routers.alerting_router import router as alerting_router

# ================================================================
# INITIAL LOAD
# ================================================================
identity = load_identity()
mode = load_mode()
state = load_state()

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

app = FastAPI()

# ================================================================
# GLOBAL SINGLETON SERVICES
# ================================================================
personality_engine = PersonalityEngine()
orchestrator = ContextOrchestrator(identity, mode, state)
workflow_service = ActionWorkflowService()
memory_service = MemoryService()
governance_service = ExecutionGovernanceService()

conversation_state_service = ConversationStateService()
awareness_service = AwarenessService()
response_formatter = ResponseFormatter()

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
# HEALTH
# ================================================================
@app.get("/health")
async def health():
    return {"status": "ok"}

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
# ROUTERS
# ================================================================
app.include_router(voice_router)
app.include_router(adnan_ai_router)
app.include_router(metrics_router)
app.include_router(alerting_router)

# ================================================================
# /ops/execute — AWARE OPERATOR PIPELINE (CSI ENFORCED)
# ================================================================
@app.post("/ops/execute")
async def execute(req: CommandRequest):
    global _LAST_CALL_TS

    if not OS_ENABLED:
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

    command = AICommand(
        command=req.command,
        input=req.payload,
        identity_snapshot=identity,
        state_snapshot=state,
        mode_snapshot=mode,
    )

    user_text = req.payload.get("text") or req.payload.get("query") or ""
    orch = await orchestrator.run(user_text)
    decision_output = orch.get("result", {})

    awareness = awareness_service.build_snapshot(
        command=command,
        csi_state=conversation_state_service.get(),
        decision=decision_output,
    )

    execution_result = None

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

            execution_state = execution_result.get("execution_state")

            if execution_state:
                conversation_state_service.sync_from_execution(
                    execution_state=execution_state,
                    request_id=command.request_id,
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

# ================================================================
# DIRECT AI CONTEXT
# ================================================================
@app.post("/ai/context")
async def ai_context(req: dict):
    user_input = req.get("text")
    if not user_input:
        raise HTTPException(400, "Missing field: text")

    orch = await orchestrator.run(user_input)

    return {
        "success": True,
        "engine_output": orch,
    }
