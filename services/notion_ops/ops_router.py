# services/notion_ops/ops_router.py

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from .ops_engine import NotionOpsEngine
from .ops_commands import NotionOpsCommands
from .ops_validator import NotionOpsValidator
from .ops_structure_sync import NotionStructureSync

router = APIRouter(prefix="/notion-ops", tags=["Notion Ops"])

# Singleton instances
_engine = NotionOpsEngine()
_commands = NotionOpsCommands(_engine)
_validator = NotionOpsValidator(_engine)
_structure = NotionStructureSync()


# ============================================================
# MAIN EXECUTION ENDPOINT
# ============================================================
@router.post("/execute")
def execute_ops(body: Dict[str, Any]):
    """
    Glavni endpoint za sve Notion Ops komande.
    Očekuje:
    {
        "command": "db.read.all",
        "payload": { "key": "tasks" }
    }
    """

    try:
        command = body.get("command")
        payload = body.get("payload", {})

        if not command:
            raise ValueError("Body mora sadržavati 'command'.")

        # Validate
        _validator.validate(command, payload)

        # Execute
        result = _commands.execute(command, payload)

        return {
            "ok": True,
            "command": command,
            "result": result
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================
# STRUCTURE CHECK ENDPOINT
# ============================================================
@router.post("/structure-check")
def structure_check(body: Dict[str, Any]):
    """
    Očekuje:
    {
        "db_key": "tasks",
        "expected_properties": {
            "Name": "title",
            "Task ID": "rich_text",
            "Status": "select",
            "Description": "rich_text",
            "Priority": "select",
            "Due Date": "date",
            "Goal": "relation",
            "Order": "number"
        }
    }
    """

    try:
        db_key = body.get("db_key")
        expected = body.get("expected_properties")

        if not db_key:
            raise ValueError("Missing db_key")
        if not expected:
            raise ValueError("Missing expected_properties")

        db_id = _engine.db_registry.get(db_key)
        if not db_id:
            raise ValueError(f"Database '{db_key}' nije registrovan.")

        result = _structure.run_structure_check(db_id, expected)

        return {
            "ok": True,
            "db_key": db_key,
            "result": result
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================
# REQUIRED BY main.py
# ============================================================
notion_ops_router = router
