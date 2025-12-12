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
# GLOBAL SERVICES (SINGLETONS)
# ================================================================
personality_engine = PersonalityEngine()
orchestrator = ContextOrchestrator(identity, mode, state)
workflow_service = ActionWorkflowService()


# ================================================================
# MODELS
# ================================================================
class CommandRequest(BaseModel):
    command: str
    payload: dict


app.include_router(voice_router)


# ================================================================
# PERSONALITY ROUTES
# ================================================================
@app.get("/ops/get_personality")
async def get_personality():
    return {
        "success": True,
        "personality": personality_engine.get_personality()
    }


@app.post("/ops/reset_personality")
async def reset_personality():
    personality_engine.reset()
    return {"success": True}


@app.post("/ops/teach_personality")
async def teach_personality(req: dict):
    text = req.get("text")
    category = req.get("category", "values")

    if not text:
        raise HTTPException(400, "Missing field: text")

    personality_engine.add_trait(category, text)
    return {"success": True}


# ================================================================
# /ops/execute — CEO → ORCHESTRATOR → WORKFLOW → EXECUTION
# ================================================================
@app.post("/ops/execute")
async def execute(req: CommandRequest):
    try:
        logger.info(">> /ops/execute %s", req.command)

        user_text = (
            req.payload.get("text")
            or req.payload.get("query")
            or ""
        )

        # ------------------------------------------------------------
        # 1. ORCHESTRATOR (CEO BRAIN)
        # ------------------------------------------------------------
        orch = await orchestrator.run(user_text)
        context_type = orch.get("context_type")
        result = orch.get("result", {})

        # ------------------------------------------------------------
        # 2. NON-EXECUTING CONTEXTS
        # ------------------------------------------------------------
        if context_type in {"identity", "chat", "memory", "meta"}:
            return {
                "success": True,
                "final_answer": orch["final_output"]["final_answer"],
                "engine_output": orch,
            }

        # ------------------------------------------------------------
        # 3. SOP DELEGATION → SOPExecutionManager
        # ------------------------------------------------------------
        if (
            result.get("type") == "delegation"
            and result.get("context") == "sop"
        ):
            workflow = {
                "type": "sop_execution",
                "execution_plan": result["delegation"].get("plan", []),
            }

            workflow_result = await workflow_service.execute_workflow(workflow)

            return {
                "success": True,
                "final_answer": "SOP je izvršen.",
                "engine_output": {
                    "context_type": "sop_execution",
                    "workflow": workflow,
                    "workflow_result": workflow_result,
                },
            }

        # ------------------------------------------------------------
        # 4. GENERIC DELEGATION → WORKFLOW ENGINE
        # ------------------------------------------------------------
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

            return {
                "success": True,
                "final_answer": "Zadatak je izvršen.",
                "engine_output": {
                    "context_type": "workflow_execution",
                    "workflow": workflow,
                    "workflow_result": workflow_result,
                },
            }

        # ------------------------------------------------------------
        # 5. FALLBACK
        # ------------------------------------------------------------
        return {
            "success": True,
            "final_answer": orch["final_output"]["final_answer"],
            "engine_output": orch,
        }

    except Exception as e:
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
