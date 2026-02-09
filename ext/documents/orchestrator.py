from ext.notion.writer import create_page
from ext.notion.linker import link_to_relation


async def orchestrate_document(payload: dict):
    """
    payload expected:
    {
        "title": "...",
        "content": "...",
        "parent_db": "database_id",
        "relations": {
            "Project": "project_id",
            "Goal": "goal_id"
        }
    }
    """

    content = payload.get("content")
    relations = payload.get("relations", {})

    # 1. Create page
    approval_id = payload.get("approval_id")
    execution_id = payload.get("execution_id")
    initiator = payload.get("initiator") or "unknown"
    db_key = payload.get("db_key")

    page_res = await create_page(
        db_key=db_key,
        property_specs=payload.get("property_specs") or {},
        wrapper_patch=payload.get("wrapper_patch") or {},
        approval_id=approval_id,
        execution_id=execution_id,
        initiator=initiator,
    )
    page_id = (
        ((page_res.get("result") or {}).get("result") or {}).get("page_id")
        if isinstance(page_res, dict)
        else None
    )

    # 2. Content writes are DISABLED here: use governed notion_ops flow.
    if content:
        raise RuntimeError(
            "DISABLED: ext.documents.orchestrator content writes must use governed notion_ops flow"
        )

    # 3. Add relations if provided
    for rel_name, rel_id in relations.items():
        await link_to_relation(
            page_id,
            rel_name,
            rel_id,
            db_key=db_key,
            approval_id=approval_id,
            execution_id=execution_id,
            initiator=initiator,
        )

    return {"page_id": page_id, "create_result": page_res}
