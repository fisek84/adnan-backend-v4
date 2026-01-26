from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from models.agent_contract import AgentInput, AgentOutput
from services.agent_router.executor_factory import get_executor
from services.agent_router.openai_responses_executor import OpenAIResponsesExecutor


_REVENUE_GROWTH_OPERATOR_SYSTEM_PROMPT = """You are Revenue & Growth Operator.

Purpose:
- Operational execution support for sales and growth.
- You create concrete artifacts: outreach/email drafts, sequences, meeting briefs/minutes, funnel update proposals, sales content.

Hard constraints (non-negotiable):
- You never make final decisions. All approvals and decisions belong to CEO Advisor.
- You MUST NOT write to Notion or any external system.
- NO tool calls. NO side effects.
- If required input is missing, populate requests_from_ceo.

Output:
- Return ONLY a single JSON object matching this schema (no markdown, no extra text):

{
  "agent": "revenue_growth_operator",
  "task_id": "<string|null>",
  "objective": "<string>",
  "context_ref": {
    "lead_id": "<string|null>",
    "account_id": "<string|null>",
    "meeting_id": "<string|null>",
    "campaign_id": "<string|null>"
  },
  "work_done": [
    {
      "type": "email_draft|outreach_sequence|meeting_brief|meeting_minutes|funnel_update_proposal|content_asset",
      "title": "<string>",
      "content": "<string>",
      "meta": {"...": "..."}
    }
  ],
  "next_steps": [
    {"action": "<string>", "owner": "ceo_advisor|me|other", "due": "<string|null>"}
  ],
  "recommendations_to_ceo": [
    {
      "decision_needed": true,
      "decision": "<string>",
      "options": ["..."],
      "recommended_option": "<string>",
      "rationale": "<string>"
    }
  ],
  "requests_from_ceo": [
    {"info_needed": "<string>", "why": "<string>"}
  ],
  "notion_ops_proposal": [
    {
      "action": "create|update",
      "object": "lead|deal|meeting|task|campaign|partner",
      "fields": {"...": "..."}
    }
  ]
}
"""


def _resolve_env_binding(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.upper().startswith("ENV:"):
        key = raw.split(":", 1)[1].strip()
        if not key:
            return None
        resolved = (os.getenv(key) or "").strip()
        return resolved or None
    return raw


def _ensure_contract_shape(obj: Any, *, objective_fallback: str) -> Dict[str, Any]:
    out: Dict[str, Any] = obj if isinstance(obj, dict) else {}

    # Enforce required top-level keys with safe defaults.
    out.setdefault("agent", "revenue_growth_operator")
    out.setdefault("task_id", None)
    out.setdefault("objective", objective_fallback)

    ctx = out.get("context_ref")
    if not isinstance(ctx, dict):
        ctx = {}
    ctx.setdefault("lead_id", None)
    ctx.setdefault("account_id", None)
    ctx.setdefault("meeting_id", None)
    ctx.setdefault("campaign_id", None)
    out["context_ref"] = ctx

    for k in (
        "work_done",
        "next_steps",
        "recommendations_to_ceo",
        "requests_from_ceo",
        "notion_ops_proposal",
    ):
        if not isinstance(out.get(k), list):
            out[k] = []

    return out


async def revenue_growth_operator_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    """LLM worker-agent: Revenue & Growth Operator (read-only, JSON-only)."""

    md = getattr(ctx.get("registry_entry"), "metadata", None)
    if not isinstance(md, dict):
        md = {}

    message = (getattr(agent_input, "message", None) or "").strip()

    # Prefer assistant_id from registry metadata (must be ENV-bound, not hardcoded).
    assistant_id = _resolve_env_binding(md.get("assistant_id"))

    # Build a deterministic envelope for the LLM.
    envelope: Dict[str, Any] = {
        "agent": "revenue_growth_operator",
        "objective": message or "(missing objective)",
        "task_id": md.get("task_id") if isinstance(md.get("task_id"), str) else None,
        "context_ref": {
            "lead_id": None,
            "account_id": None,
            "meeting_id": None,
            "campaign_id": None,
        },
        "inputs": {
            "message": message,
            "metadata": getattr(agent_input, "metadata", None)
            if isinstance(getattr(agent_input, "metadata", None), dict)
            else {},
            "identity_pack": getattr(agent_input, "identity_pack", None)
            if isinstance(getattr(agent_input, "identity_pack", None), dict)
            else {},
            "snapshot": getattr(agent_input, "snapshot", None)
            if isinstance(getattr(agent_input, "snapshot", None), dict)
            else {},
        },
        "constraints": {
            "read_only": True,
            "no_tools": True,
            "no_side_effects": True,
            "manager": "ceo_advisor",
        },
    }

    mode = (os.getenv("OPENAI_API_MODE") or "assistants").strip().lower()

    try:
        if mode == "responses":
            model_env = str(
                md.get("responses_model_env") or "REVENUE_GROWTH_OPERATOR_MODEL"
            )
            executor = OpenAIResponsesExecutor(model_env=model_env)
            result = await executor.execute(
                {
                    "input": json.dumps(envelope, ensure_ascii=False),
                    "instructions": _REVENUE_GROWTH_OPERATOR_SYSTEM_PROMPT,
                    "temperature": 0,
                    "allow_tools": False,
                }
            )
        else:
            if not assistant_id:
                raise RuntimeError(
                    "Missing assistant binding: set REVENUE_GROWTH_OPERATOR_ASSISTANT_ID"
                )

            executor = get_executor(purpose="agent_router")
            result = await executor.execute(
                {
                    "assistant_id": assistant_id,
                    "content": json.dumps(envelope, ensure_ascii=False),
                    "instructions": _REVENUE_GROWTH_OPERATOR_SYSTEM_PROMPT,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "parse_mode": "text_json",
                    "limit": 10,
                    "input": json.dumps(envelope, ensure_ascii=False),
                    "allow_tools": False,
                }
            )

        contract = _ensure_contract_shape(
            result, objective_fallback=envelope["objective"]
        )

        return AgentOutput(
            text=json.dumps(contract, ensure_ascii=False),
            proposed_commands=[],
            agent_id="revenue_growth_operator",
            read_only=True,
            trace={
                "agent": "revenue_growth_operator",
                "mode": mode,
                "no_tools": True,
                "contract_ok": True,
            },
        )

    except Exception as e:  # noqa: BLE001
        fallback = _ensure_contract_shape(
            {
                "agent": "revenue_growth_operator",
                "objective": envelope["objective"],
                "requests_from_ceo": [
                    {
                        "info_needed": "Clarify objective and provide any lead/account/meeting context.",
                        "why": f"agent_execution_failed: {e}",
                    }
                ],
            },
            objective_fallback=envelope["objective"],
        )

        return AgentOutput(
            text=json.dumps(fallback, ensure_ascii=False),
            proposed_commands=[],
            agent_id="revenue_growth_operator",
            read_only=True,
            trace={
                "agent": "revenue_growth_operator",
                "mode": mode,
                "no_tools": True,
                "contract_ok": False,
                "error": str(e),
            },
        )
