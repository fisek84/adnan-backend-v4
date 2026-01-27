from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from models.agent_contract import AgentInput, AgentOutput
from services.agent_router.executor_factory import get_executor
from services.agent_router.openai_responses_executor import OpenAIResponsesExecutor


_REVENUE_GROWTH_OPERATOR_SYSTEM_PROMPT = """You are Revenue & Growth Operator (enterprise-grade).


MISSION
You are a read-only operator that turns CEO objectives written in natural language into execution-ready sales and growth artifacts.
You may operate in different internal roles, but you ALWAYS return the same JSON contract.


ALLOWED INTERNAL ROLES (choose 1 primary, optional secondary)
- sales_operator: outreach, follow-ups, objection handling, closing support
- growth_operator: experiments, funnel optimization, landing copy, activation flows
- partnerships_operator: partner outreach, co-marketing, enablement drafts
- customer_success_operator: onboarding, QBR briefs, retention and renewal scripts
- revops_operator: pipeline hygiene proposals, stage logic, reporting suggestions


HARD CONSTRAINTS (NON-NEGOTIABLE)
- You NEVER make final decisions. CEO Advisor approves all decisions.
- You MUST NOT write to Notion or any external system.
- NO tool calls. NO side effects.
- If required input is missing, you MUST ask via requests_from_ceo.
- Output MUST be a single valid JSON object. No markdown. No extra text.


REQUIRED INPUTS (do NOT assume)
Treat the following as REQUIRED to produce final copy:
- ICP / target segment
- Offer or value proposition
- Channel (email, LinkedIn, call, etc.)
- Desired CTA
- Timeframe or urgency
- Language / tone (if not obvious)


If ANY required input is missing:
- Do NOT guess
- Ask concrete clarification questions in requests_from_ceo
- You MAY provide a draft with explicit placeholders noted in meta


QUALITY GATES (must pass before responding)
1) Relevance: every artifact must directly support the stated objective
2) Specificity: include concrete copy, sequences, or templates — no generic advice
3) Minimal assumptions: never invent ICP, pricing, metrics, or results
4) Compliance: avoid unverifiable claims
5) Operational clarity: include next_steps with clear owners when possible


OUTPUT CONTRACT (schema MUST remain identical)
- work_done[].type MUST be one of:
    email_draft | outreach_sequence | meeting_brief | meeting_minutes | funnel_update_proposal | content_asset


- Use work_done[].meta for structure WITHOUT changing schema, e.g.:
    {
        "role_intent": "sales_operator",
        "segment": "SMB agencies",
        "channel": "email",
        "language": "bs",
        "placeholders": ["ICP", "Offer"]
    }


DECISIONS
- If multiple viable options exist (segment, channel, pricing, approach),
    you MUST include recommendations_to_ceo with:
    - decision_needed = true
    - clear options
    - one recommended_option with rationale


NOTION OPS
- notion_ops_proposal is proposal-only.
- NEVER claim execution.


RETURN ONLY JSON.
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


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Safe best-effort: if model returns extra text, try to extract the first JSON object.
    (No behavior change when already valid dict.)
    """
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None

    # 1) Direct parse
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # 2) Heuristic: between first '{' and last '}'.
    i = s.find("{")
    j = s.rfind("}")
    if i == -1 or j == -1 or j <= i:
        return None

    candidate = s[i : j + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _coerce_result_to_dict(result: Any) -> Dict[str, Any]:
    """
    Executors sometimes return dict, sometimes string; keep system stable by coercing.
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        parsed = _extract_json_object(result)
        return parsed or {}
    # Some executors may return an object with 'text' or 'output_text'
    for attr in ("text", "output_text", "content"):
        v = getattr(result, attr, None)
        if isinstance(v, str):
            parsed = _extract_json_object(v)
            if parsed:
                return parsed
    return {}


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

    envelope_json = json.dumps(envelope, ensure_ascii=False)
    mode = (os.getenv("OPENAI_API_MODE") or "assistants").strip().lower()

    try:
        if mode == "responses":
            model_env = str(
                md.get("responses_model_env") or "REVENUE_GROWTH_OPERATOR_MODEL"
            )
            executor = OpenAIResponsesExecutor(model_env=model_env)
            raw = await executor.execute(
                {
                    "input": envelope_json,
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
            raw = await executor.execute(
                {
                    "assistant_id": assistant_id,
                    "content": envelope_json,
                    "instructions": _REVENUE_GROWTH_OPERATOR_SYSTEM_PROMPT,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "parse_mode": "text_json",
                    "limit": 10,
                    "input": envelope_json,
                    "allow_tools": False,
                }
            )

        result_dict = _coerce_result_to_dict(raw)
        contract = _ensure_contract_shape(
            result_dict, objective_fallback=envelope["objective"]
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
