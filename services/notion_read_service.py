from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from services.notion_service import NotionService, get_notion_service

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

    Canon:
    - koristi postojeći NotionService (aiohttp session + _safe_request)
    - ne radi approval
    - ne radi write operacije
    - vraća human-friendly markdown (ne raw JSON)
    """

    def __init__(self, notion: NotionService) -> None:
        self._notion = notion

    async def get_page_by_title_contains(self, query: str) -> Optional[PageObj]:
        """
        Vraća page samo ako title sadrži query (case-insensitive).
        NEMA fallback-a na "prvi page rezultat" (bitno za negative test).
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

        resp = await self._notion._safe_request(  # canon: reuse existing transport
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

        return None

    async def render_page_to_markdown(self, page: PageObj) -> str:
        """
        Renderuje Notion page block tree u markdown.
        Minimalno:
          - heading_1/2/3
          - paragraph
          - bulleted_list_item
        + mali broj praktičnih dodataka (divider, to_do, numbered) uz fallback.
        """
        page_id = page.get("id") if isinstance(page, dict) else None
        if not page_id or not isinstance(page_id, str):
            return ""

        # Page content
        blocks = await self._list_all_child_blocks(block_id=page_id, max_blocks=1500)

        lines: List[str] = []
        for block in blocks:
            rendered_lines = await self._render_block_recursive(block, depth=0)
            if rendered_lines:
                lines.extend(rendered_lines)

        md = "\n".join(lines).strip()
        return self._normalize_markdown(md)

    async def read_page_as_markdown(self, query: str) -> Dict[str, str]:
        """
        Stable contract for endpoint consumption.
        Returns empty strings if not found (endpoint normalizes to ok=false).
        """
        q = (query or "").strip()
        if not q:
            return {"title": "", "url": "", "content_markdown": ""}

        page = await self.get_page_by_title_contains(q)
        if not page:
            return {"title": "", "url": "", "content_markdown": ""}

        title = self._extract_page_title(page)
        url = page.get("url", "") if isinstance(page, dict) else ""
        content_md = await self.render_page_to_markdown(page)

        return {
            "title": (title or "").strip(),
            "url": (url or "").strip(),
            "content_markdown": (content_md or "").strip(),
        }

    # -------------------------
    # internals
    # -------------------------

    async def _list_all_child_blocks(
        self, block_id: str, max_blocks: int
    ) -> List[BlockObj]:
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

    async def _render_block_recursive(
        self, block: BlockObj, *, depth: int
    ) -> List[str]:
        """
        Render block and optionally its children (for has_children).
        Depth-limited to avoid runaway recursion.
        """
        if not isinstance(block, dict):
            return []

        lines = self._render_block(block, depth=depth)

        has_children = bool(block.get("has_children"))
        block_id = block.get("id")
        if has_children and isinstance(block_id, str) and block_id and depth < 5:
            children = await self._list_all_child_blocks(
                block_id=block_id, max_blocks=500
            )
            for ch in children:
                child_lines = await self._render_block_recursive(ch, depth=depth + 1)
                if child_lines:
                    lines.extend(child_lines)

        return lines

    def _render_block(self, block: BlockObj, *, depth: int) -> List[str]:
        if not isinstance(block, dict):
            return []

        btype = block.get("type")
        if not isinstance(btype, str) or not btype:
            return []

        data = block.get(btype, {}) or {}
        if not isinstance(data, dict):
            data = {}

        indent = "  " * max(0, depth)

        if btype == "heading_1":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            return [f"{indent}# {text}".rstrip(), ""]

        if btype == "heading_2":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            return [f"{indent}## {text}".rstrip(), ""]

        if btype == "heading_3":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            return [f"{indent}### {text}".rstrip(), ""]

        if btype == "paragraph":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            if not (text or "").strip():
                return [""]
            return [f"{indent}{text}".rstrip()]

        if btype == "bulleted_list_item":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            if not (text or "").strip():
                return []
            return [f"{indent}- {text}".rstrip()]

        if btype == "numbered_list_item":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            if not (text or "").strip():
                return []
            # numbering is not preserved across siblings here; keep markdown-friendly "1."
            return [f"{indent}1. {text}".rstrip()]

        if btype == "to_do":
            text = self._rich_text_to_plain(data.get("rich_text", []))
            checked = bool(data.get("checked"))
            box = "x" if checked else " "
            if not (text or "").strip():
                return []
            return [f"{indent}- [{box}] {text}".rstrip()]

        if btype == "divider":
            return [f"{indent}---", ""]

        # fallback: pokušaj izvući rich_text / caption u plain; inače ignoriši
        text = ""
        if "rich_text" in data:
            text = self._rich_text_to_plain(data.get("rich_text", []))
        elif "caption" in data:
            text = self._rich_text_to_plain(data.get("caption", []))

        text = (text or "").strip()
        return [f"{indent}{text}".rstrip()] if text else []

    def _extract_page_title(self, page: PageObj) -> str:
        """
        Robust title extraction:
        - database pages: properties contain a title-type property
        - regular pages: often "title" property exists
        """
        if not isinstance(page, dict):
            return ""

        props = page.get("properties") or {}
        if isinstance(props, dict):
            # common: direct "title" key
            t0 = props.get("title")
            if isinstance(t0, dict) and t0.get("type") == "title":
                items = t0.get("title") or []
                if isinstance(items, list):
                    return self._rich_text_to_plain(items).strip()

            # scan for any title-type property
            for prop in props.values():
                if not isinstance(prop, dict):
                    continue
                if prop.get("type") != "title":
                    continue
                title_items = prop.get("title") or []
                if isinstance(title_items, list):
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


# ------------------------------------------------------------
# Module-level helper for gateway endpoint (read-only, no approval)
# ------------------------------------------------------------
async def read_page_as_markdown(query: str) -> Dict[str, str]:
    notion = get_notion_service()
    svc = NotionReadService(notion)
    return await svc.read_page_as_markdown(query)
