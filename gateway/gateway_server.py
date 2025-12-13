# ================================================================
# BOOT DEBUG — MORA BITI PRIJE SVIH OSTALIH IMPORTA
# ================================================================
import os
print("=== BOOT DEBUG START ===")
print("CWD:", os.getcwd())
print("/app exists:", os.path.exists("/app"))
print("/app content:", os.listdir("/app") if os.path.exists("/app") else "NO /app")
print("/app/services exists:", os.path.exists("/app/services"))
print(
    "/app/services content:",
    os.listdir("/app/services") if os.path.exists("/app/services") else "NO services"
)
print("=== BOOT DEBUG END ===")

print("LOADED NEW GATEWAY VERSION")

# ================================================================
# STANDARD IMPORTS
# ================================================================
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

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
# EXECUTION LAYER (KANONSKI)
# ================================================================
from services.action_workflow_service import ActionWorkflowService

# ================================================================
# GOVERNANCE (FAZA 19)
# ================================================================
from services.execution_governance_service import ExecutionGovernanceService

# ================================================================
# MEMORY (FAZA 8.1)
# ================================================================
from services.memory_service import MemoryService

# ================================================================
# NOTION (READ-ONLY KNOWLEDGE → SNAPSHOT)
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

print("CURRENT FILE LOADED FROM:", os.path.abspath(__file__))

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

app = FastAPI()

# ================================================================
# GLOBAL SERVICES (SINGLETONS)
# ================================================================
personality_engine = PersonalityEngine()
orchestrator = ContextOrchestrator(identity, mode, state)
workflow_service = ActionWorkflowService()
memory_service = MemoryService()
governance_service = ExecutionGovernanceService()

# ------------------------------------------------
# NOTION READ-ONLY SERVICE (SNAPSHOT SOURCE)
# ------------------------------------------------
notion_service = NotionService(
    api_key=os.getenv("NOTION_API_KEY"),
    goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
    tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
    projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID"),
)

# ================================================================
# STARTUP — INITIAL KNOWLEDGE SYNC
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
# ROUTER REGISTRATION
# ================================================================
app.include_router(voice_router)
app.include_router(adnan_ai_router)
app.include_router(metrics_router)
app.include_router(alerting_router)

# ================================================================
# /ops/execute — CEO → ORCHESTRATOR → GOVERNANCE → EXECUTION
# ================================================================
@app.post("/ops/execute")
async def execute(req: CommandRequest):
    try:
        logger.info(">> /ops/execute %s", req.command)

        if memory_service.get_active_decision():
            return {
                "success": False,
                "final_answer": (
                    "Postoji aktivna odluka. "
                    "Potrebno je završiti ili otkazati prije nove."
                ),
            }

        user_text = (
            req.payload.get("text")
            or req.payload.get("query")
            or ""
        )

        orch = await orchestrator.run(user_text)
        context_type = orch.get("context_type")
        result = orch.get("result", {})

        if context_type in {
            "identity", "chat", "memory",
            "meta", "knowledge", "status"
        }:
            return {
                "success": True,
                "final_answer": orch["final_output"]["final_answer"],
                "engine_output": orch,
            }

        if result.get("type") == "delegation":
            delegation = result.get("delegation", {})
            command = delegation.get("command")
            payload = delegation.get("payload") or {}

            if not command:
                return {
                    "success": True,
                    "final_answer": orch["final_output"]["final_answer"],
                    "engine_output": orch,
                }

            memory_service.set_active_decision({
                "command": command,
                "payload": payload,
            })

            workflow = {
                "type": "workflow",
                "steps": [
                    {
                        "directive": command,
                        "params": payload,
                    }
                ],
            }

            workflow_result = await workflow_service.execute_workflow(workflow)
            memory_service.clear_active_decision()

            return {
                "success": True,
                "final_answer": orch["final_output"]["final_answer"],
                "engine_output": workflow_result,
            }

        return {
            "success": True,
            "final_answer": orch["final_output"]["final_answer"],
            "engine_output": orch,
        }

    except Exception as e:
        memory_service.clear_active_decision()
        logger.exception(">> ERROR /ops/execute")
        raise HTTPException(500, str(e))

# ================================================================
# DIRECT AI CONTEXT (READ-ONLY)
# ================================================================
@app.post("/ai/context")
async def ai_context(req: dict):
    user_input = req.get("text")

    if not user_input:
        raise HTTPException(400, "Missing field: text")

    result = await orchestrator.run(user_input)

    return {
        "success": True,
        "final_answer": result["final_output"]["final_answer"],
        "engine_output": result,
    }
