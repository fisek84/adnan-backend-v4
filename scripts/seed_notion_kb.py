from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from services.identity_loader import load_json_file, resolve_path


def _get_token() -> str:
    for k in ("NOTION_TOKEN", "NOTION_API_KEY"):
        v = (os.getenv(k) or "").strip()
        if v:
            return v
    raise SystemExit("Missing NOTION_TOKEN or NOTION_API_KEY")


def _chunk_rich_text(text: str, *, chunk_size: int = 1900) -> List[Dict[str, Any]]:
    # Notion rich_text has practical size limits; keep conservative.
    t = text or ""
    if not t:
        return []
    out: List[Dict[str, Any]] = []
    for i in range(0, len(t), chunk_size):
        part = t[i : i + chunk_size]
        out.append({"type": "text", "text": {"content": part}})
    return out


def _props_from_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    title = entry.get("title") if isinstance(entry.get("title"), str) else ""
    kb_id = entry.get("id") if isinstance(entry.get("id"), str) else ""
    content = entry.get("content") if isinstance(entry.get("content"), str) else ""

    tags = entry.get("tags") if isinstance(entry.get("tags"), list) else []
    tags_ms = [{"name": x} for x in tags if isinstance(x, str) and x.strip()]

    applies = (
        entry.get("applies_to") if isinstance(entry.get("applies_to"), list) else []
    )
    applies_ms = [{"name": x} for x in applies if isinstance(x, str) and x.strip()]

    pr = entry.get("priority")
    priority = float(pr) if isinstance(pr, (int, float)) else 0.5

    updated_at = entry.get("updated_at")
    updated_start = (
        updated_at if isinstance(updated_at, str) and updated_at.strip() else None
    )

    props: Dict[str, Any] = {
        "Name": {"title": [{"type": "text", "text": {"content": title or kb_id}}]},
        "ID": {"rich_text": [{"type": "text", "text": {"content": kb_id}}]},
        "Tags": {"multi_select": tags_ms},
        "AppliesTo": {"multi_select": applies_ms or [{"name": "all"}]},
        "Priority": {"number": priority},
        "Content": {"rich_text": _chunk_rich_text(content)},
    }

    if updated_start:
        props["UpdatedAt"] = {"date": {"start": updated_start}}

    return props


async def _query_page_by_id(
    client: httpx.AsyncClient, *, db_id: str, kb_id: str
) -> Optional[str]:
    r = await client.post(
        f"/v1/databases/{db_id}/query",
        json={
            "filter": {"property": "ID", "rich_text": {"equals": kb_id}},
            "page_size": 1,
        },
    )
    r.raise_for_status()
    data = r.json()
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    page = results[0]
    if not isinstance(page, dict):
        return None
    pid = page.get("id")
    return pid if isinstance(pid, str) and pid.strip() else None


async def _upsert_entry(
    client: httpx.AsyncClient, *, db_id: str, entry: Dict[str, Any]
) -> Tuple[bool, bool]:
    """Returns (created, updated)."""
    kb_id = entry.get("id")
    if not isinstance(kb_id, str) or not kb_id.strip():
        return False, False

    page_id = await _query_page_by_id(client, db_id=db_id, kb_id=kb_id)
    props = _props_from_entry(entry)

    if page_id:
        r = await client.patch(f"/v1/pages/{page_id}", json={"properties": props})
        r.raise_for_status()
        return False, True

    r = await client.post(
        "/v1/pages",
        json={
            "parent": {"database_id": db_id},
            "properties": props,
        },
    )
    r.raise_for_status()
    return True, False


async def main() -> None:
    db_id = (os.getenv("NOTION_KB_DB_ID") or "").strip()
    if not db_id:
        raise SystemExit("Missing NOTION_KB_DB_ID")

    notion_version = (os.getenv("NOTION_VERSION") or "2022-06-28").strip()
    base_url = (os.getenv("NOTION_API_BASE_URL") or "https://api.notion.com").strip()

    kb_path = (os.getenv("IDENTITY_KNOWLEDGE_PATH") or "").strip()
    kb = (
        load_json_file(os.path.abspath(kb_path))
        if kb_path
        else load_json_file(resolve_path("knowledge.json"))
    )

    entries = kb.get("entries") if isinstance(kb, dict) else []
    items = entries if isinstance(entries, list) else []

    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Notion-Version": notion_version,
        "Content-Type": "application/json",
    }

    created = 0
    updated = 0
    skipped = 0

    async with httpx.AsyncClient(
        base_url=base_url, headers=headers, timeout=15.0
    ) as client:
        for raw in items:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            if not isinstance(raw.get("id"), str) or not isinstance(
                raw.get("content"), str
            ):
                skipped += 1
                continue

            c, u = await _upsert_entry(client, db_id=db_id, entry=raw)
            created += 1 if c else 0
            updated += 1 if u else 0

    print(
        {
            "ok": True,
            "db_id": db_id,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "total": len(items),
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
