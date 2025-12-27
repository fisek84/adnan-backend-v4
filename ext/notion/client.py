from __future__ import annotations
import os
from typing import Any, Dict
from dotenv import load_dotenv

try:
    # Optional in some CI/test environments.
    from notion_client import Client  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    Client = None  # type: ignore[assignment,misc]

from services.notion_schema_registry import NotionSchemaRegistry

# ============================================================
# ENV INIT
# ============================================================

load_dotenv()

def _get_notion_client() -> "Client":
    """Create a Notion client lazily.
    This module is imported by parts of the runtime as well as by tests.
    To keep imports CI-friendly (Phase 11), we must NOT hard-fail at import
    time if NOTION_API_KEY is missing.
    We only raise when a Notion operation is actually invoked.
    """
    if Client is None:
        raise RuntimeError(
            "notion-client is not installed. Install requirements.txt dependencies to use Notion features."
        )

    api_key = os.getenv("NOTION_API_KEY")
    if not api_key:
        raise RuntimeError("NOTION_API_KEY is missing")

    return Client(auth=api_key)

# ============================================================
# LOW-LEVEL WORKERS (NO LOGIC, HARD VALIDATION)
# ============================================================

def create_page(database_id: str, properties: Dict[str, Any]):
    try:
        notion = _get_notion_client()
        page = notion.pages.create(
            parent={"database_id": database_id},
            properties=properties,
        )

        # HARD ASSERT — nema silent success-a
        if (
            not page
            or "id" not in page
            or page.get("parent", {}).get("database_id") != database_id
        ):
            raise RuntimeError(f"Notion page creation failed silently: {page}")

        return {
            "success": True,
            "page_id": page["id"],
            "page": page,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }

def delete_page(page_id: str):
    try:
        notion = _get_notion_client()
        notion.pages.delete(page_id)
        return {
            "success": True,
            "page_id": page_id,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }

# ============================================================
# CANONICAL DISPATCHER (KANON)
# ============================================================

def perform_notion_action(
    *,
    operation: str,
    database: str = None,  # db_key, npr. "goals"
    payload: dict = None,
    **_,
):
    """
    KANONSKI Notion dispatcher.
    - agent NE zna db_id
    - payload se gradi ISKLJUČIVO kroz NotionSchemaRegistry
    - nema mutacije payload-a
    """
    payload = payload or {}

    if operation == "create_page":
        if not database:
            raise ValueError("database (db_key) is required")
        db = NotionSchemaRegistry.get_db(database)
        db_id = db.get("db_id")
        if not db_id:
            raise RuntimeError(f"NOTION DB ID missing for '{database}'")

        # KANONSKI PAYLOAD BUILD
        page_payload = NotionSchemaRegistry.build_create_page_payload(
            db_key=database,
            properties=payload,
        )

        return create_page(
            database_id=db_id,
            properties=page_payload["properties"],
        )

    if operation == "delete_page":
        page_id = payload.get("page_id")
        if not page_id:
            raise ValueError("page_id is required for delete_page")
        return delete_page(page_id)

    raise ValueError(f"Unsupported Notion operation: {operation}")
