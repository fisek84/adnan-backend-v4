# routers/ai_ops_router.py

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging  # Dodajemo logovanje

from services.notion_ops.ops_commands import NotionOpsCommands
from services.notion_ops.ops_engine import NotionOpsEngine
from services.notion_ops.ops_validator import NotionOpsValidator

router = APIRouter(prefix="/ai-ops", tags=["AI Ops"])

# Core instances
_engine = NotionOpsEngine()
_commands = NotionOpsCommands(_engine)
_validator = NotionOpsValidator(_engine)

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# SMART MODE — Natural Language → Structured Ops Command
# ============================================================
def smart_interpret(text: str) -> (str, dict):
    t = text.lower().strip()
    logger.info(f"Interpreting natural language input: {t}")

    # ---- READ DB ----
    if any(k in t for k in ["provjeri", "pregledaj", "daj mi", "izvještaj", "report"]) and \
       any(k in t for k in ["database", "bazu", "db", "notion"]):

        # find which db (tasks or goals)
        if "task" in t or "zadac" in t:
            logger.info("Interpreted as 'db.read.all' for tasks.")
            return "db.read.all", {"key": "tasks"}

        if "goal" in t or "cilj" in t:
            logger.info("Interpreted as 'db.read.all' for goals.")
            return "db.read.all", {"key": "goals"}

        # general: "provjeri sve database"
        logger.info("Interpreted as 'db.read.all_dbs'.")
        return "db.read.all_dbs", {}

    # ---- DB STRUCTURE CHECK ----
    if "struktura" in t or "structure" in t or "schema" in t:
        if "task" in t:
            logger.info("Interpreted as 'db.structure.check' for tasks.")
            return "db.structure.check", {"key": "tasks"}
        if "goal" in t:
            logger.info("Interpreted as 'db.structure.check' for goals.")
            return "db.structure.check", {"key": "goals"}
        logger.info("Interpreted as 'db.structure.check_all'.")
        return "db.structure.check_all", {}

    # Unknown natural command
    logger.error("Failed to interpret command.")
    raise ValueError("AI ne može prepoznati šta želiš. Preciziraj malo bolje.")


# ============================================================
# MAIN AI OPS ENDPOINT
# ============================================================
@router.post("/run")
async def ai_ops_run(body: Dict[str, Any]):
    """
    Accepts both:
    - natural language: "provjeri sve database"
    - structured: { "command": "db.read.all", "payload": {"key": "tasks"} }
    """

    try:
        command = body.get("command")
        payload = body.get("payload", {})
        natural = body.get("natural")

        logger.info(f"Received request to run command: {command} with payload: {payload}")

        # ---------------------------------------
        # SMART MODE: natural language handling
        # ---------------------------------------
        if natural:
            logger.info("Received natural language command, processing...")
            command, payload = smart_interpret(natural)

        # ---------------------------------------
        # VALIDATE
        # ---------------------------------------
        logger.info(f"Validating command: {command} with payload: {payload}")
        _validator.validate(command, payload)

        # ---------------------------------------
        # EXECUTE
        # ---------------------------------------
        logger.info(f"Executing command: {command} with payload: {payload}")
        result = await _engine.run(command, payload)

        logger.info(f"Command executed successfully. Result: {result}")
        return {
            "ok": True,
            "command": command,
            "payload": payload,
            "result": result
        }

    except Exception as e:
        logger.error(f"Error during AI ops execution: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


# EXPORT
ai_ops_router = router
