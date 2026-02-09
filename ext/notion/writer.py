# ext/notion/writer.py

import logging
from typing import Any, Dict, Optional

from models.ai_command import AICommand
from services.execution_orchestrator import ExecutionOrchestrator

logger = logging.getLogger(__name__)


def _require_str(v: Any, name: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise RuntimeError(f"{name} is required")
    return v.strip()


# -------------------------------------------------
#  GOVERNED NOTION WRITES ONLY
# -------------------------------------------------
async def create_page(
    *,
    db_key: str,
    property_specs: Dict[str, Any],
    approval_id: str,
    execution_id: str,
    initiator: str = "unknown",
    wrapper_patch: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Governed create_page via canonical orchestrator (approval required)."""

    cmd = AICommand(
        command="create_page",
        intent="create_page",
        params={
            "db_key": _require_str(db_key, "db_key"),
            "property_specs": property_specs or {},
            "wrapper_patch": wrapper_patch or {},
        },
        initiator=_require_str(initiator, "initiator"),
        execution_id=_require_str(execution_id, "execution_id"),
        approval_id=_require_str(approval_id, "approval_id"),
    )

    return await ExecutionOrchestrator().execute(cmd)


async def delete_page(
    *,
    page_id: str,
    approval_id: str,
    execution_id: str,
    initiator: str = "unknown",
) -> Dict[str, Any]:
    """Governed delete_page via canonical orchestrator (approval required)."""

    cmd = AICommand(
        command="delete_page",
        intent="delete_page",
        params={"page_id": _require_str(page_id, "page_id")},
        initiator=_require_str(initiator, "initiator"),
        execution_id=_require_str(execution_id, "execution_id"),
        approval_id=_require_str(approval_id, "approval_id"),
    )
    return await ExecutionOrchestrator().execute(cmd)


def append_text(*_: Any, **__: Any) -> None:
    raise RuntimeError(
        "DISABLED: ext.notion.writer.append_text performs direct block writes; use governed notion_ops flow"
    )
