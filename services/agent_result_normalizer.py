from __future__ import annotations

from typing import Any, Dict, Optional


_ALLOWED_NOTION_PROPOSAL_INTENTS = {
    "batch_request",
    "create_page",
    "create_task",
    "update_page",
}


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "1", "yes", "y"}:
            return True
        if s in {"false", "0", "no", "n"}:
            return False
    return bool(v)


def validate_notion_proposal(proposal: Any) -> Optional[str]:
    """Validate `notion_proposal` structure.

    Contract:
      - proposal is a dict
    - proposal.intent is one of: batch_request | create_page | create_task | update_page
      - proposal.params is a dict

    Returns:
      - None when valid
      - a short error string when invalid
    """

    if proposal is None:
        return "missing"

    if not isinstance(proposal, dict):
        return "not_a_dict"

    intent = proposal.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        return "missing_intent"

    intent_s = intent.strip()
    if intent_s not in _ALLOWED_NOTION_PROPOSAL_INTENTS:
        return "unsupported_intent"

    params = proposal.get("params")
    if not isinstance(params, dict):
        return "missing_params"

    return None


def normalize_agent_result(raw_output: Any) -> Dict[str, Any]:
    """Normalize delegate_agent_task execution result into canonical enterprise shape.

    Expected output (top-level):
      {
        ok: bool,
        execution_state: "COMPLETED" | "FAILED",
        execution_id,
        approval_id,
        result: {
          agent_id,
          output_text,
          requires_notion_write?: bool,
          notion_proposal?: { intent: ..., params: {...} }
        }
      }

    Notes:
      - This function is fail-soft: it never raises.
      - If `requires_notion_write` is true but proposal is invalid, it normalizes to FAILED.
    """

    out: Dict[str, Any] = _as_dict(raw_output)
    if not out:
        out = {}

    # Ensure nested result exists
    res = _as_dict(out.get("result"))
    out["result"] = res

    # Ensure base fields
    ok_val = out.get("ok")
    if not isinstance(ok_val, bool):
        # Infer from execution_state if present.
        st = out.get("execution_state")
        if isinstance(st, str) and st.strip().upper() in {"FAILED", "COMPLETED"}:
            ok_val = st.strip().upper() == "COMPLETED"
        else:
            ok_val = True
    out["ok"] = bool(ok_val)

    st0 = out.get("execution_state")
    st = st0.strip().upper() if isinstance(st0, str) and st0.strip() else None
    if st not in {"COMPLETED", "FAILED"}:
        st = "COMPLETED" if out.get("ok") is True else "FAILED"
    out["execution_state"] = st

    # Normalize expected result keys
    agent_id = res.get("agent_id")
    if not isinstance(agent_id, str):
        agent_id = ""
    res["agent_id"] = agent_id

    output_text = res.get("output_text")
    if output_text is None:
        output_text = res.get("text")
    if not isinstance(output_text, str):
        output_text = ""
    res["output_text"] = output_text

    # Optional notion proposal
    requires = _as_bool(res.get("requires_notion_write"))
    notion_proposal = res.get("notion_proposal")
    if requires:
        err = validate_notion_proposal(notion_proposal)
        if err is not None:
            # Mark as terminal failure; do not allow auto-proposal creation.
            out["ok"] = False
            out["execution_state"] = "FAILED"
            out.setdefault(
                "failure",
                {
                    "reason": f"invalid_notion_proposal:{err}",
                    "error_type": "ValidationError",
                },
            )
            res["requires_notion_write"] = False
            res.pop("notion_proposal", None)
            return out

        res["requires_notion_write"] = True
        res["notion_proposal"] = notion_proposal
    else:
        # Clean up invalid leftovers
        res.pop("notion_proposal", None)
        res.pop("requires_notion_write", None)

    return out
