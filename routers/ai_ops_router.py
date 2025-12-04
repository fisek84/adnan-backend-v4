# routers/ai_ops_router.py

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging

from services.notion_ops.ops_commands import NotionOpsCommands
from services.notion_ops.ops_engine import NotionOpsEngine
from services.notion_ops.ops_validator import NotionOpsValidator


router = APIRouter(prefix="/ai-ops", tags=["AI Ops"])

# Core singletons
_engine = NotionOpsEngine()
_commands = NotionOpsCommands(_engine)
_validator = NotionOpsValidator(_engine)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================
# NATURAL LANGUAGE INTERPRETER
# ============================================================
def smart_interpret(text: str) -> tuple[str, dict]:
    t = text.lower().strip()
    logger.info(f"[AI-OPS] Natural language received: {t}")

    # ---- READ DATABASE ----
    if any(k in t for k in ["provjeri", "pregledaj", "daj mi", "izvještaj", "report"]) and \
       any(k in t for k in ["database", "bazu", "db", "notion"]):

        if "task" in t or "zadac" in t:
            logger.info("[AI-OPS] Interpreted: db.read.all → tasks")
            return "db.read.all", {"key": "tasks"}

        if "goal" in t or "cilj" in t:
            logger.info("[AI-OPS] Interpreted: db.read.all → goals")
            return "db.read.all", {"key": "goals"}

        logger.info("[AI-OPS] Interpreted: db.read.all_dbs")
        return "db.read.all_dbs", {}

    # ---- STRUCTURE CHECK ----
    if any(k in t for k in ["struktura", "structure", "schema"]):

        if "task" in t:
            logger.info("[AI-OPS] Interpreted: db.structure.check → tasks")
            return "db.structure.check", {"key": "tasks"}

        if "goal" in t:
            logger.info("[AI-OPS] Interpreted: db.structure.check → goals")
            return "db.structure.check", {"key": "goals"}

        logger.info("[AI-OPS] Interpreted: db.structure.check_all")
        return "db.structure.check_all", {}

    # ---- UNKNOWN ----
    logger.error("[AI-OPS] Natural language command not understood")
    raise ValueError("AI ne može prepoznati šta želiš. Preciziraj malo bolje.")


# ============================================================
# MAIN AI-OPS EXECUTION ENDPOINT
# ============================================================
@router.post("/run")
async def ai_ops_run(body: Dict[str, Any]):
    """
    Supports both:
    1) natural language
       { "natural": "provjeri sve task database" }

    2) structured commands
       { "command": "db.read.all", "payload": {"key": "tasks"} }
    """

    try:
        natural_text = body.get("natural")
        command = body.get("command")
        payload = body.get("payload", {})

        # ---------------------------------------------
        # NATURAL LANGUAGE MODE
        # ---------------------------------------------
        if natural_text:
            logger.info(f"[AI-OPS] Processing natural text: {natural_text}")
            command, payload = smart_interpret(natural_text)

        # ---------------------------------------------
        # VALIDATION
        # ---------------------------------------------
        if not command:
            raise ValueError("Missing 'command' field.")

        logger.info(f"[AI-OPS] Validating: {command} with {payload}")
        _validator.validate(command, payload)

        # ---------------------------------------------
        # EXECUTION
        # ---------------------------------------------
        logger.info(f"[AI-OPS] Executing: {command}")
        result = await _engine.run(command, payload)

        logger.info(f"[AI-OPS] Completed: {result}")

        return {
            "ok": True,
            "command": command,
            "payload": payload,
            "result": result
        }

    except Exception as e:
        logger.error(f"[AI-OPS] Error: {e}")
        raise HTTPException(400, detail=str(e))


# exported router for main.py
ai_ops_router = router
