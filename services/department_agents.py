from __future__ import annotations

import json
from typing import Any, Dict, List

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from models.canon import PROPOSAL_WRAPPER_INTENT
from services.ceo_advisor_agent import create_ceo_advisor_agent


def _is_dept_ops_strict(agent_input: Any, agent_id: str) -> tuple[bool, str]:
    """Explicit-only strict backend trigger for Dept Ops.

    Returns:
      (True, "preferred_agent_id") when preferred_agent_id == "dept_ops"
      (True, "prefix") when message starts with "dept ops:"
      (False, "") otherwise

    Note: Accepts both AgentInput-like objects and dict payloads.
    """

    if (agent_id or "").strip() != "dept_ops":
        return (False, "")

    preferred = getattr(agent_input, "preferred_agent_id", None)
    if preferred is None:
        getter = getattr(agent_input, "get", None)
        if callable(getter):
            preferred = getter("preferred_agent_id")

    if isinstance(preferred, str) and preferred.strip() == "dept_ops":
        return (True, "preferred_agent_id")

    msg = getattr(agent_input, "message", None)
    if msg is None:
        getter = getattr(agent_input, "get", None)
        if callable(getter):
            msg = getter("message")

    msg_norm = (msg if isinstance(msg, str) else "").strip().lower()
    if msg_norm.startswith("dept ops:"):
        return (True, "prefix")

    return (False, "")


def _dept_ops_select_query(message: str) -> str:
    """Deterministically map message -> ops query (no LLM)."""

    m = (message or "").lower()
    # Order must match spec: snapshot_health, then kpi, else default.
    if "snapshot_health" in m:
        return "ops.snapshot_health"
    if "kpi" in m:
        return "ops.kpi_weekly_summary_preview"
    return "ops.daily_brief"


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
    summary: str,
    recommendation: str,
    evidence_lines: List[str],
    proposed_commands: List[ProposedCommand],
) -> str:
    sm = (summary or "").strip()
    if not sm:
        sm = "No summary available."

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

    # MUST: EXACT 4 sections in order.
    return (
        "Summary\n"
        f"{sm}\n\n"
        "Evidence\n"
        f"{ev}\n\n"
        "Recommendation\n"
        f"{rec}\n\n"
        "Proposed Actions\n"
        f"{pa}".strip()
    )


def _format_ops_daily_brief(*, recommendation: str) -> str:
    base = (recommendation or "").strip()
    if not base:
        base = "No recommendation available. Provide a clearer prompt or more snapshot context."

    # Standardized, repeatable brief header.
    # NOTE: This is still proposal-only; execution remains approval-gated.
    return (
        "Daily Ops Brief\n"
        "- Snapshot: check ops.snapshot_health before acting\n"
        "- Approvals: review pending approvals and unblock runs\n"
        "- Priorities: focus on the top 3 operational blockers\n\n"
        f"{base}".strip()
    )


def _ops_default_proposals(*, brief_text: str) -> List[ProposedCommand]:
    desc = (brief_text or "").strip()
    if not desc:
        desc = "Ops daily brief (no content)."

    # Deterministic minimal proposals that create a Notion handoff artifact.
    # These remain dry_run + requires_approval and rely on existing approval pipeline.
    pcs: List[ProposedCommand] = []

    pcs.append(
        ProposedCommand(
            command="create_task",
            args={
                "title": "handoff:ops.daily_brief",
                "description": desc,
            },
            reason="Create a Notion handoff task for the daily ops brief (proposal-only).",
            requires_approval=True,
            dry_run=True,
            risk="LOW",
            scope="api_execute_raw",
            payload_summary={
                "endpoint": "/api/execute/raw",
                "canon": "DEPT_OPS_DAILY_BRIEF",
            },
        )
    )

    pcs.append(
        ProposedCommand(
            command="create_page",
            args={
                "title": "Ops Daily Brief",
                "content": desc,
            },
            reason="Create a Notion page artifact for the daily ops brief (proposal-only).",
            requires_approval=True,
            dry_run=True,
            risk="LOW",
            scope="api_execute_raw",
            payload_summary={
                "endpoint": "/api/execute/raw",
                "canon": "DEPT_OPS_DAILY_BRIEF",
            },
        )
    )

    return pcs


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
    # Dept Ops strict backend: ONLY for explicit invocations.
    # Must be tool-only (read_only.query) and must not touch ctx/KB/memory/LLM.
    strict, selected_by = _is_dept_ops_strict(agent_input, agent_id)
    if strict:
        from services.tool_runtime_executor import execute as tool_execute

        message = getattr(agent_input, "message", None) or ""
        query = _dept_ops_select_query(message)
        conv_id = getattr(agent_input, "conversation_id", None)
        execution_id = f"{conv_id or 'dept_ops'}:{query}"

        res = await tool_execute(
            "read_only.query",
            {"query": query},
            agent_id="dept_ops",
            execution_id=execution_id,
        )

        data = res.get("data") if isinstance(res, dict) else None
        if not isinstance(data, dict):
            data = {"kind": query, "data": data}

        text = json.dumps(data, ensure_ascii=False, sort_keys=True)

        return AgentOutput(
            text=text,
            proposed_commands=[],
            agent_id="dept_ops",
            read_only=True,
            trace={
                "dept_ops_strict_backend": True,
                "selected_query": query,
                "selected_by": selected_by,
                "department_agent": True,
                "department_agent_id": "dept_ops",
                "selected_agent_id": "dept_ops",
                "selected_entrypoint": "services.department_agents:dept_ops_agent",
            },
        )

    # Reuse CEO Advisor executor/parsing exactly (no new LLM plumbing) by delegating,
    # while adding a deterministic prefix to steer the advisory output.
    pref = (
        f"You are the {dept_label} department agent. Stay in read/propose mode. "
        f"Do not execute writes. If proposing actions, use the existing proposal wrapper flow.\n\n"
    )

    if agent_id == "dept_ops":
        pref = (
            "You are the Operations department agent.\n"
            "Constraints: proposal-only, read-only context, no execution.\n"
            "Output must follow a Daily Ops Brief structure and include concrete Notion proposals (create_task/create_page).\n\n"
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

    delegated_text = getattr(delegated, "text", "") or ""
    if agent_id == "dept_ops":
        # Ensure ops always has concrete Notion proposals even if delegated output is vague.
        # Keep it deterministic and proposal-only.
        dept_pcs = _ops_default_proposals(brief_text=delegated_text) + dept_pcs

    evidence_lines = _evidence_lines_from_inputs(agent_input=agent_input, ctx=ctx2)

    # Dept Ops: enrich Summary with deterministic snapshot-driven data.
    summary_lines: List[str] = []
    if agent_id == "dept_ops":
        try:
            from services.tool_runtime_executor import execute as tool_execute

            conv_id = getattr(agent_input, "conversation_id", None)
            exec_id = f"{conv_id or 'dept_ops'}:ops.daily_brief"
            res = await tool_execute(
                "read_only.query",
                {"action": "read_only.query", "query": "ops.daily_brief"},
                agent_id="dept_ops",
                execution_id=exec_id,
            )
            data = res.get("data") if isinstance(res, dict) else None
            if isinstance(data, dict) and data.get("kind") == "ops.daily_brief":
                counts = (
                    data.get("summary", {}).get("counts")
                    if isinstance(data.get("summary"), dict)
                    and isinstance(data.get("summary", {}).get("counts"), dict)
                    else {}
                )
                open_tasks = counts.get("open_tasks")
                overdue = counts.get("overdue_tasks")
                active_goals = counts.get("active_goals")
                active_projects = counts.get("active_projects")
                summary_lines.append(
                    "Daily Ops Brief (snapshot-driven): "
                    + f"open_tasks={open_tasks} overdue_tasks={overdue} "
                    + f"active_goals={active_goals} active_projects={active_projects}"
                )
        except Exception:
            summary_lines.append("Daily Ops Brief (snapshot-driven): unavailable")

        # KPI preview only if user asked about KPI/weekly.
        try:
            msg = (getattr(agent_input, "message", None) or "").lower()
        except Exception:
            msg = ""
        if any(tok in msg for tok in ("kpi", "weekly", "tjed", "week", "metric")):
            try:
                from services.tool_runtime_executor import execute as tool_execute

                conv_id = getattr(agent_input, "conversation_id", None)
                exec_id = f"{conv_id or 'dept_ops'}:ops.kpi_weekly_summary_preview"
                res = await tool_execute(
                    "read_only.query",
                    {
                        "action": "read_only.query",
                        "query": "ops.kpi_weekly_summary_preview",
                    },
                    agent_id="dept_ops",
                    execution_id=exec_id,
                )
                data = res.get("data") if isinstance(res, dict) else None
                if (
                    isinstance(data, dict)
                    and data.get("kind") == "ops.kpi_weekly_summary_preview"
                ):
                    periods = (
                        data.get("periods")
                        if isinstance(data.get("periods"), dict)
                        else {}
                    )
                    metrics = (
                        data.get("metrics")
                        if isinstance(data.get("metrics"), list)
                        else []
                    )
                    summary_lines.append(
                        "KPI weekly preview (snapshot-driven): "
                        + f"period_current={periods.get('current')} metrics={len(metrics)}"
                    )
            except Exception:
                summary_lines.append(
                    "KPI weekly preview (snapshot-driven): unavailable"
                )

    if not summary_lines:
        summary_lines.append(
            "Read-only + proposal-only. Execution requires approval for writes."
        )

    rec_text = delegated_text
    if agent_id == "dept_ops":
        rec_text = _format_ops_daily_brief(recommendation=delegated_text)

    text = _format_dept_text(
        summary="\n".join(
            f"- {ln}" for ln in summary_lines if isinstance(ln, str) and ln.strip()
        ),
        recommendation=rec_text,
        evidence_lines=evidence_lines,
        proposed_commands=dept_pcs,
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
