from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from services.notion_service import get_notion_service, NotionService

PageObj = Dict[str, Any]
BlockObj = Dict[str, Any]


@dataclass(frozen=True)
class ReadPageResult:
    title: str
    url: str
    content_markdown: str


class NotionReadService:
    """
    READ-only servis.
    Koristi postojeći NotionService (aiohttp session + _safe_request).
    """

    def __init__(self, notion: NotionService) -> None:
        self._notion = notion

    async def get_page_by_title_contains(self, query: str) -> Optional[PageObj]:
        """
        Vraća page samo ako title sadrži query (case-insensitive).
        NEMA fallback-a na "prvi page rezultat" — to je bitno za negative test.
        """
        q = (query or "").strip()
        if not q:
            return None

        payload: Dict[str, Any] = {
            "query": q,
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": 25,
        }

        resp = await self._notion._safe_request(
            "POST",
            "https://api.notion.com/v1/search",
            payload=payload,
        )

        results: Sequence[Dict[str, Any]] = resp.get("results", []) or []
        if not results:
            return None

        q_lower = q.lower()

        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get("object") != "page":
                continue

            title = self._extract_page_title(item)
            if title and q_lower in title.lower():
                return item

        # Important: NO fallback.
        return None

    async def render_page_to_markdown(self, page: PageObj) -> str:
        page_id = page.get("id") if isinstance(page, dict) else None
        if not page_id or not isinstance(page_id, str):
            return ""

        blocks = await self._list_all_child_blocks(block_id=page_id, max_blocks=500)

        lines: List[str] = []
        for block in blocks:
            rendered_lines = self._render_block(block)
            if rendered_lines:
                lines.extend(rendered_lines)

        return self._normalize_markdown("\n".join(lines).strip())

    # -------------------------
    # internals
    # -------------------------

    async def _list_all_child_blocks(self, block_id: str, max_blocks: int) -> List[BlockObj]:
        out: List[BlockObj] = []
        next_cursor: Optional[str] = None

        max_blocks_i = int(max_blocks) if max_blocks is not None else 0
        if max_blocks_i <= 0:
            return []

        while len(out) < max_blocks_i:
            params: Dict[str, Any] = {"page_size": min(100, max_blocks_i - len(out))}
            if next_cursor:
                params["start_cursor"] = next_cursor

            resp = await self._notion._safe_request(
                "GET",
                f"https://api.notion.com/v1/blocks/{block_id}/children",
                params=params,
            )

            batch = resp.get("results", []) or []
            if isinstance(batch, list):
                out.extend([b for b in batch if isinstance(b, dict)])

            if not resp.get("has_more"):
                break

            next_cursor = resp.get("next_cursor")
            if not next_cursor:
                break

        return out[:max_blocks_i]

    def _render_block(self, block: BlockObj) -> List[str]:
        if not isinstance(block, dict):
            return []

        btype = block.get("type")
        if not isinstance(btype, str) or not btype:
            return []

        data = block.get(btype, {}) or {}
        if not isinstance(data, dict):
            data = {}

        if btype == "heading_1":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            return [f"# {text}".rstrip(), ""]

        if btype == "heading_2":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            return [f"## {text}".rstrip(), ""]

        if btype == "heading_3":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            return [f"### {text}".rstrip(), ""]

        if btype == "paragraph":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            if not text.strip():
                return [""]
            return [text]

        if btype == "bulleted_list_item":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            if not text.strip():
                return []
            return [f"- {text}"]

        # fallback: pokušaj izvući rich_text / caption u plain; inače ignoriši
        text = ""
        if "rich_text" in data:
            text = self._rich_text_to_plain(data.get("rich_text", []))
        elif "caption" in data:
            text = self._rich_text_to_plain(data.get("caption", []))

        text = (text or "").strip()
        return [text] if text else []

    def _extract_page_title(self, page: PageObj) -> str:
        if not isinstance(page, dict):
            return ""

        props = page.get("properties") or {}
        if not isinstance(props, dict):
            return ""

        for prop in props.values():
            if not isinstance(prop, dict):
                continue
            if prop.get("type") != "title":
                continue
            title_items = prop.get("title") or []
            if not isinstance(title_items, list):
                return ""
            return self._rich_text_to_plain(title_items).strip()

        return ""

    def _rich_text_to_plain(self, rich_text: Sequence[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for item in rich_text or []:
            if isinstance(item, dict):
                parts.append(item.get("plain_text", "") or "")
        return "".join(parts)

    def _normalize_markdown(self, md: str) -> str:
        # collapse multiple blank lines
        lines = md.splitlines()
        out: List[str] = []
        blank = False
        for line in lines:
            if line.strip() == "":
                if blank:
                    continue
                blank = True
                out.append("")
            else:
                blank = False
                out.append(line.rstrip())
        return "\n".join(out).strip()


async def read_page_as_markdown(query: str) -> Dict[str, str]:
    """
    Helper (READ-only, bez approvala):
      - uses get_page_by_title_contains + render_page_to_markdown
      - returns: { "title": ..., "url": ..., "content_markdown": ... }
    """
    q = (query or "").strip()
    if not q:
        return {"title": "", "url": "", "content_markdown": ""}

    notion = get_notion_service()
    svc = NotionReadService(notion)

    page = await svc.get_page_by_title_contains(q)
    if not page:
        return {"title": "", "url": "", "content_markdown": ""}

    title = svc._extract_page_title(page)
    url = page.get("url", "") if isinstance(page, dict) else ""
    content_md = await svc.render_page_to_markdown(page)

    return {"title": title or "", "url": url or "", "content_markdown": content_md or ""}
