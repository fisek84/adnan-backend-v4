from __future__ import annotations

from typing import Any, Dict

from services.notion_delegation_preview_builder import (
    build_delegate_agent_task_preview_from_snapshot,
)


def build_execute_raw_payload_from_delegate_agent_task_preview(
    *,
    preview: Dict[str, Any],
    initiator: str = "ceo_chat",
) -> Dict[str, Any]:
    """Convert PR#2 delegation preview into an /api/execute/raw payload.

    Canon:
    - Reuses existing /api/execute/raw -> approval -> /api/ai-ops/approval/approve -> resume.
    - Does NOT introduce a new protocol.
    - MUST NOT be read_only for the execution step.
    """

    params = preview.get("params") if isinstance(preview, dict) else None
    params = params if isinstance(params, dict) else {}

    command = preview.get("command") if isinstance(preview, dict) else None
    intent = preview.get("intent") if isinstance(preview, dict) else None

    command_s = (command or "").strip() if isinstance(command, str) else ""
    intent_s = (intent or "").strip() if isinstance(intent, str) else ""

    if not command_s:
        command_s = "delegate_agent_task"
    if not intent_s:
        intent_s = command_s

    return {
        "command": command_s,
        "intent": intent_s,
        "params": params,
        "initiator": (initiator or "ceo").strip() or "ceo",
        "read_only": False,
        "metadata": {
            "canon": "notion_task_delegation_execute_raw_bridge.v1",
            "source_task": params.get("source_task")
            if isinstance(params, dict)
            else None,
        },
    }


def build_execute_raw_payload_from_notion_task_snapshot(
    *,
    task_item: Any,
    agent_id: str,
    initiator: str = "ceo_chat",
) -> Dict[str, Any]:
    """Notion task snapshot -> PR#2 preview -> /api/execute/raw payload."""

    preview = build_delegate_agent_task_preview_from_snapshot(
        task_item=task_item,
        agent_id=agent_id,
    )
    return build_execute_raw_payload_from_delegate_agent_task_preview(
        preview=preview,
        initiator=initiator,
    )
