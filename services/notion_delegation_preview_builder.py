from __future__ import annotations

from typing import Any, Dict

from services.notion_task_to_agent_builder import build_agent_task_from_snapshot


def build_delegate_agent_task_preview_from_snapshot(
    *,
    task_item: Any,
    agent_id: str,
) -> Dict[str, Any]:
    """Build a read-only delegation preview from a Notion snapshot task item.

    This is a pure helper:
    - no execution
    - no approval creation
    - no Notion write

    Output contract:
      {
        "command": "delegate_agent_task",
        "intent": "delegate_agent_task",
        "read_only": True,
        "validated": False,
        "params": {
          "agent_id": "...",
          "task_text": "...",
          "source_task": {"notion_id": "...", "url": "..."}
        }
      }
    """

    agent_id_s = (agent_id or "").strip()

    built = build_agent_task_from_snapshot(task_item)
    task_text = built.get("task_text") if isinstance(built, dict) else None
    source_task = built.get("source_task") if isinstance(built, dict) else None

    if not isinstance(task_text, str):
        task_text = ""

    source_task_out: Dict[str, Any] = {}
    if isinstance(source_task, dict):
        notion_id = source_task.get("notion_id")
        url = source_task.get("url")
        if isinstance(notion_id, str) and notion_id.strip():
            source_task_out["notion_id"] = notion_id.strip()
        if isinstance(url, str) and url.strip():
            source_task_out["url"] = url.strip()

    return {
        "command": "delegate_agent_task",
        "intent": "delegate_agent_task",
        "read_only": True,
        "validated": False,
        "params": {
            "agent_id": agent_id_s,
            "task_text": task_text,
            "source_task": source_task_out,
        },
    }
