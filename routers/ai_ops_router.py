# routers/ai_ops_router.py

from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from services.notion_ops.ops_commands import NotionOpsCommands
from services.notion_ops.ops_engine import NotionOpsEngine
from services.notion_ops.ops_validator import NotionOpsValidator

router = APIRouter(prefix="/ai-ops", tags=["AI Ops"])

# Core instances
_engine = NotionOpsEngine()
_commands = NotionOpsCommands(_engine)
_validator = NotionOpsValidator(_engine)


# ============================================================
# SMART MODE — Natural Language → Structured Ops Command
# ============================================================
def smart_interpret(text: str) -> (str, dict):
    t = text.lower().strip()

    # ---- READ DB ----
    if any(k in t for k in ["provjeri", "pregledaj", "daj mi", "izvještaj", "report"]) and \
       any(k in t for k in ["database", "bazu", "db", "notion"]):

        # find which db (tasks or goals)
        if "task" in t or "zadac" in t:
            return "db.read.all", {"key": "tasks"}

        if "goal" in t or "cilj" in t:
            return "db.read.all", {"key": "goals"}

        # general: "provjeri sve database"
        return "db.read.all_dbs", {}

    # ---- DB STRUCTURE CHECK ----
    if "struktura" in t or "structure" in t or "schema" in t:
        if "task" in t:
            return "db.structure.check", {"key": "tasks"}
        if "goal" in t:
            return "db.structure.check", {"key": "goals"}
        return "db.structure.check_all", {}

    # Unknown natural command
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

        # ---------------------------------------
        # SMART MODE: natural language handling
        # ---------------------------------------
        if natural:
            command, payload = smart_interpret(natural)

        # ---------------------------------------
        # VALIDATE
        # ---------------------------------------
        _validator.validate(command, payload)

        # ---------------------------------------
        # EXECUTE
        # ---------------------------------------
        result = await _engine.run(command, payload)

        return {
            "ok": True,
            "command": command,
            "payload": payload,
            "result": result
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# EXPORT
ai_ops_router = router
