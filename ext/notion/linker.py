from typing import Any, Dict

from models.ai_command import AICommand
from services.execution_orchestrator import ExecutionOrchestrator


def _canonicalize_notion_id(id_str: str) -> str:
    """
    Pretvara ID u canonical Notion UUID format ako je već u skraćenom obliku.
    Primjer:
    '2b95873bd84a81e59a15fea6a570c652' ->
    '2b95873b-d84a-81e5-9a15-fea6a570c652'
    """

    clean = id_str.replace("-", "").strip()

    if len(clean) != 32:
        # nije validan UUID — vrati original
        return id_str

    # formatiraj u canonical oblik
    return f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"


def _require_str(v: Any, name: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise RuntimeError(f"{name} is required")
    return v.strip()


async def link_to_relation(
    page_id: str,
    relation_name: str,
    target_id: str,
    *,
    db_key: str,
    approval_id: str,
    execution_id: str,
    initiator: str = "unknown",
) -> Dict[str, Any]:
    """
    Dodaje relation link na Notion stranicu.
    relation_name = ime relation property-ja u bazi (npr. "Project", "Goal")
    target_id = ID stranice/entiteta na koji se linkuje
    """

    # 🔥 Canonicalize oba ID-a prije slanja Notion-u
    page_id_fmt = _canonicalize_notion_id(page_id)
    target_id_fmt = _canonicalize_notion_id(target_id)

    cmd = AICommand(
        command="update_page",
        intent="update_page",
        params={
            "db_key": _require_str(db_key, "db_key"),
            "page_id": page_id_fmt,
            "properties": {
                _require_str(relation_name, "relation_name"): {
                    "relation": [{"id": target_id_fmt}]
                }
            },
        },
        initiator=_require_str(initiator, "initiator"),
        execution_id=_require_str(execution_id, "execution_id"),
        approval_id=_require_str(approval_id, "approval_id"),
    )

    return await ExecutionOrchestrator().execute(cmd)
