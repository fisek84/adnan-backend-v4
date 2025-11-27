from ext.notion.writer import create_page, append_text
from ext.notion.linker import link_to_relation

def orchestrate_document(payload: dict):
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

    title = payload.get("title")
    content = payload.get("content")
    parent_db = payload.get("parent_db")
    relations = payload.get("relations", {})

    # 1. Create page
    page = create_page(title, parent_db)
    page_id = page["id"]

    # 2. Write content (chunking applied)
    append_text(page_id, content)

    # 3. Add relations if provided
    for rel_name, rel_id in relations.items():
        link_to_relation(page_id, rel_name, rel_id)

    return {"page_id": page_id}
