print("LOADED NEW GATEWAY VERSION")

import os
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
# VOICE
# ================================================================
from routers.voice_router import router as voice_router


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

app.include_router(voice_router)

# ================================================================
# /ops/execute — CEO → ORCHESTRATOR → GOVERNANCE → EXECUTION
# ================================================================
@app.post("/ops/execute")
async def execute(req: CommandRequest):
    try:
        logger.info(">> /ops/execute %s", req.command)

        # ------------------------------------------------------------
        # ACTIVE DECISION GUARD
        # ------------------------------------------------------------
        if memory_service.get_active_decision():
            return {
                "success": False,
                "final_answer": "Postoji aktivna odluka. Potrebno je završiti ili otkazati prije nove.",
            }

        user_text = (
            req.payload.get("text")
            or req.payload.get("query")
            or ""
        )

        # ------------------------------------------------------------
        # 1. ORCHESTRATOR
        # ------------------------------------------------------------
        orch = await orchestrator.run(user_text)
        context_type = orch.get("context_type")
        result = orch.get("result", {})

        # ------------------------------------------------------------
        # 2. READ-ONLY CONTEXTS
        # ------------------------------------------------------------
        if context_type in {
            "identity", "chat", "memory",
            "meta", "knowledge", "status"
        }:
            return {
                "success": True,
                "final_answer": orch["final_output"]["final_answer"],
                "engine_output": orch,
            }

        # ============================================================
        # 3A. SOP EXECUTION (KANONSKI)
        # ============================================================
        if result.get("type") == "sop_execution":
            execution_plan = result.get("execution_plan")

            if not execution_plan:
                return {
                    "success": False,
                    "final_answer": "SOP nema execution plan.",
                }

            # Active decision
            memory_service.set_active_decision({
                "type": "sop_execution",
                "sop": result.get("sop"),
            })

            workflow = {
                "type": "sop_execution",
                "execution_plan": execution_plan,
            }

            workflow_result = await workflow_service.execute_workflow(workflow)

            success = bool(workflow_result.get("success"))

            memory_service.record_execution(
                decision_type="sop",
                key=result.get("sop"),
                success=success,
            )

            memory_service.clear_active_decision()

            return {
                "success": success,
                "final_answer": (
                    "SOP je uspješno izvršen."
                    if success
                    else "SOP nije uspješno izvršen."
                ),
                "engine_output": workflow_result,
            }

        # ============================================================
        # 3B. LEGACY DELEGATION (POSTOJEĆI FLOW)
        # ============================================================
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

            governance = governance_service.evaluate(
                role=payload.get("role", "user"),
                context_type=context_type,
                directive=command,
                params=payload,
                approval_id=payload.get("approval_id"),
            )

            if not governance.get("allowed"):
                return {
                    "success": False,
                    "final_answer": "Izvršenje je blokirano governance pravilima.",
                    "governance": governance,
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

            steps = workflow_result.get("steps_results", [])
            confirmed = any(
                step.get("result", {}).get("confirmed") is True
                for step in steps
            )

            memory_service.record_execution(
                decision_type="workflow",
                key=command,
                success=confirmed,
            )

            memory_service.clear_active_decision()

            return {
                "success": confirmed,
                "final_answer": (
                    "Akcija je uspješno izvršena."
                    if confirmed
                    else "Akcija nije potvrđena."
                ),
                "engine_output": workflow_result,
            }

        # ------------------------------------------------------------
        # 4. FALLBACK
        # ------------------------------------------------------------
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
