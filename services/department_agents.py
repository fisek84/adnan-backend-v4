from __future__ import annotations

from typing import Any, Dict, List

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from models.canon import PROPOSAL_WRAPPER_INTENT
from services.ceo_advisor_agent import create_ceo_advisor_agent


def _clone_agent_input_with_prefix(
    agent_input: AgentInput,
    *,
    message_prefix: str,
    agent_id: str,
) -> AgentInput:
    base = (getattr(agent_input, "message", None) or "").strip()
    msg = f"{message_prefix}{base}" if base else message_prefix.strip()

    identity_pack = (
        agent_input.identity_pack
        if isinstance(getattr(agent_input, "identity_pack", None), dict)
        else {}
    )
    snapshot = (
        agent_input.snapshot
        if isinstance(getattr(agent_input, "snapshot", None), dict)
        else {}
    )

    md0 = (
        agent_input.metadata
        if isinstance(getattr(agent_input, "metadata", None), dict)
        else {}
    )
    md = dict(md0)
    md.setdefault("department_agent", True)
    md["department_agent_id"] = agent_id

    # Keep preferred_agent_id as-is; router decides selection.
    preferred = getattr(agent_input, "preferred_agent_id", None)

    return AgentInput(
        message=msg,
        identity_pack=identity_pack,
        snapshot=snapshot,
        conversation_id=getattr(agent_input, "conversation_id", None),
        history=getattr(agent_input, "history", None),
        preferred_agent_id=preferred,
        metadata=md,
    )


def _evidence_lines_from_inputs(
    *,
    agent_input: AgentInput,
    ctx: Dict[str, Any],
) -> List[str]:
    lines: List[str] = []

    ip = (
        agent_input.identity_pack
        if isinstance(getattr(agent_input, "identity_pack", None), dict)
        else {}
    )
    snap = (
        agent_input.snapshot
        if isinstance(getattr(agent_input, "snapshot", None), dict)
        else {}
    )

    lines.append(f"identity_pack.keys={sorted(list(ip.keys()))[:24]}")
    lines.append(f"snapshot.keys={sorted(list(snap.keys()))[:24]}")

    gp = ctx.get("grounding_pack") if isinstance(ctx, dict) else None
    gp = gp if isinstance(gp, dict) else {}
    if gp:
        try:
            ip2 = (
                gp.get("identity_pack")
                if isinstance(gp.get("identity_pack"), dict)
                else {}
            )
            identity_hash = ip2.get("hash")
            if isinstance(identity_hash, str) and identity_hash.strip():
                lines.append(
                    f"grounding_pack.identity_pack.hash={identity_hash.strip()}"
                )
        except Exception:
            pass

        try:
            kb = (
                gp.get("kb_retrieved")
                if isinstance(gp.get("kb_retrieved"), dict)
                else {}
            )
            used = kb.get("used_entry_ids")
            used_ids = [x for x in (used or []) if isinstance(x, str) and x.strip()]
            if used_ids:
                lines.append(f"grounding_pack.kb_used_entry_ids={used_ids[:16]}")
            else:
                lines.append("grounding_pack.kb_used_entry_ids=[]")
        except Exception:
            pass
    else:
        lines.append("grounding_pack=missing")

    return lines


def _format_dept_text(
    *,
    recommendation: str,
    evidence_lines: List[str],
    proposed_commands: List[ProposedCommand],
    risks: List[str],
) -> str:
    rec = (recommendation or "").strip()
    if not rec:
        rec = "No recommendation available. Provide a clearer prompt or more snapshot context."

    ev = "\n".join(f"- {ln}" for ln in evidence_lines) if evidence_lines else "- (none)"

    if proposed_commands:
        pcs = []
        for pc in proposed_commands:
            cmd = getattr(pc, "command", None)
            reason = getattr(pc, "reason", None)
            risk = getattr(pc, "risk", None)
            pcs.append(
                f"- {str(cmd or '').strip() or 'unknown'}"
                + (f" (risk={risk})" if risk else "")
                + (
                    f": {str(reason).strip()}"
                    if isinstance(reason, str) and reason.strip()
                    else ""
                )
            )
        pa = "\n".join(pcs)
    else:
        pa = "- (no proposed actions)"

    rk = "\n".join(f"- {r}" for r in risks) if risks else "- (none)"

    # MUST: EXACT 4 sections in order.
    return (
        "Recommendation\n"
        f"{rec}\n\n"
        "Evidence\n"
        f"{ev}\n\n"
        "Proposed Actions\n"
        f"{pa}\n\n"
        "Risks / Dependencies\n"
        f"{rk}".strip()
    )


def _normalize_proposals_for_dept(
    pcs: Any,
    *,
    dept_agent_id: str,
) -> List[ProposedCommand]:
    out: List[ProposedCommand] = []
    raw_list = pcs if isinstance(pcs, list) else []
    for item in raw_list:
        if isinstance(item, ProposedCommand):
            pc = item
        elif isinstance(item, dict):
            args = item.get("args") if isinstance(item.get("args"), dict) else {}
            pc = ProposedCommand(
                command=str(item.get("command") or ""),
                args=args,
                reason=item.get("reason"),
                requires_approval=True,
                risk=item.get("risk"),
                dry_run=True,
                scope=item.get("scope"),
                payload_summary=item.get("payload_summary")
                if isinstance(item.get("payload_summary"), dict)
                else None,
            )
        else:
            continue

        # Dept agent contract: proposal-only, approval-gated.
        try:
            pc.dry_run = True
        except Exception:
            pass
        try:
            pc.requires_approval = True
        except Exception:
            pass

        # Encourage canonical wrapper execution path without forcing new shapes.
        try:
            if getattr(pc, "command", None) == PROPOSAL_WRAPPER_INTENT:
                pc.scope = "api_execute_raw"
        except Exception:
            pass

        out.append(pc)

    return out


async def _dept_entrypoint(
    agent_input: AgentInput,
    ctx: Dict[str, Any],
    *,
    agent_id: str,
    dept_label: str,
) -> AgentOutput:
    # Reuse CEO Advisor executor/parsing exactly (no new LLM plumbing) by delegating,
    # while adding a deterministic prefix to steer the advisory output.
    pref = (
        f"You are the {dept_label} department agent. Stay in read/propose mode. "
        f"Do not execute writes. If proposing actions, use the existing proposal wrapper flow.\n\n"
    )

    dept_input = _clone_agent_input_with_prefix(
        agent_input,
        message_prefix=pref,
        agent_id=agent_id,
    )

    ctx2 = ctx if isinstance(ctx, dict) else {}
    delegated = await create_ceo_advisor_agent(dept_input, ctx2)

    # Normalize proposed_commands to dept contract (approval-gated, dry_run).
    dept_pcs = _normalize_proposals_for_dept(
        getattr(delegated, "proposed_commands", None),
        dept_agent_id=agent_id,
    )

    evidence_lines = _evidence_lines_from_inputs(agent_input=agent_input, ctx=ctx2)
    risks = [
        "All actions are proposals only; execution requires approval.",
        "Notion writes (if any) must go through the existing approval + orchestrator pipeline.",
        "Recommendations may be limited by missing SSOT snapshot/grounding coverage.",
    ]

    text = _format_dept_text(
        recommendation=getattr(delegated, "text", "") or "",
        evidence_lines=evidence_lines,
        proposed_commands=dept_pcs,
        risks=risks,
    )

    out = AgentOutput(
        text=text,
        proposed_commands=dept_pcs,
        agent_id=agent_id,
        read_only=True,
        trace={
            "department_agent": True,
            "department_agent_id": agent_id,
            # These are required for direct calls; AgentRouterService will also set
            # selected_agent_id/selected_entrypoint when routed via registry.
            "selected_agent_id": agent_id,
            "selected_entrypoint": f"services.department_agents:dept_{agent_id.split('dept_', 1)[-1]}_agent",
        },
    )
    return out


async def dept_growth_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    return await _dept_entrypoint(
        agent_input,
        ctx,
        agent_id="dept_growth",
        dept_label="Growth",
    )


async def dept_product_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    return await _dept_entrypoint(
        agent_input,
        ctx,
        agent_id="dept_product",
        dept_label="Product",
    )


async def dept_finance_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    return await _dept_entrypoint(
        agent_input,
        ctx,
        agent_id="dept_finance",
        dept_label="Finance",
    )


async def dept_ops_agent(agent_input: AgentInput, ctx: Dict[str, Any]) -> AgentOutput:
    return await _dept_entrypoint(
        agent_input,
        ctx,
        agent_id="dept_ops",
        dept_label="Operations",
    )
