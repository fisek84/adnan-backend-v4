from __future__ import annotations

import ast
from typing import Any, Dict


def _ensure_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _ensure_str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


class _SafeArithmetic:
    _ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
    _ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)

    @classmethod
    def eval_expr(cls, expr: str) -> float:
        src = _ensure_str(expr)
        if not src:
            raise ValueError("missing_expression")

        try:
            tree = ast.parse(src, mode="eval")
        except SyntaxError as exc:
            raise ValueError("invalid_expression") from exc

        def _eval(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return _eval(node.body)

            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)

            # Python <3.8 compatibility: Num
            if isinstance(node, ast.Num) and isinstance(node.n, (int, float)):
                return float(node.n)

            if isinstance(node, ast.UnaryOp) and isinstance(
                node.op, cls._ALLOWED_UNARYOPS
            ):
                v = _eval(node.operand)
                return v if isinstance(node.op, ast.UAdd) else -v

            if isinstance(node, ast.BinOp) and isinstance(node.op, cls._ALLOWED_BINOPS):
                left = _eval(node.left)
                right = _eval(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return left / right

            raise ValueError("expression_contains_disallowed_syntax")

        return _eval(tree)


async def execute(
    action: str,
    params: dict,
    *,
    agent_id: str,
    execution_id: str,
) -> dict:
    """Production-safe offline tool runtime.

    HARD RULES:
    - No network
    - No external writes
    - Read-only or draft generation only
    """

    action_norm = _ensure_str(action)
    params_norm = _ensure_dict(params)
    agent_id_norm = _ensure_str(agent_id)
    execution_id_norm = _ensure_str(execution_id)

    if not action_norm:
        raise ValueError("missing_action")
    if not agent_id_norm:
        raise ValueError("missing_agent_id")
    if not execution_id_norm:
        raise ValueError("missing_execution_id")

    # ------------------- READ-ONLY -------------------
    if action_norm == "read_only.query":
        q = _ensure_str(params_norm.get("query") or params_norm.get("q") or "")
        meta: Dict[str, Any] = {
            "source": "local",
            "query": q,
            "router_version": "read_only.query.ops.v1",
            "missing_inputs": [],
        }

        snapshot: Dict[str, Any] = {}
        try:
            from services.knowledge_snapshot_service import KnowledgeSnapshotService

            snapshot = KnowledgeSnapshotService.get_snapshot()
            snapshot = snapshot if isinstance(snapshot, dict) else {}
        except Exception:
            snapshot = {}

        if not q:
            meta["missing_inputs"] = ["query"]
            data = {
                "kind": "read_only.query",
                "supported_queries": [
                    "ops.daily_brief",
                    "ops.snapshot_health",
                    "ops.kpi_weekly_summary_preview",
                ],
            }
            return {
                "ok": True,
                "success": True,
                "execution_state": "COMPLETED",
                "action": action_norm,
                "agent_id": agent_id_norm,
                "data": data,
                "meta": meta,
            }

        if q == "ops.snapshot_health":
            if not snapshot:
                meta["missing_inputs"] = ["knowledge_snapshot"]
            data = {
                "kind": "ops.snapshot_health",
                "snapshot_meta": {
                    "schema_version": snapshot.get("schema_version"),
                    "status": snapshot.get("status"),
                    "generated_at": snapshot.get("generated_at"),
                    "last_sync": snapshot.get("last_sync"),
                    "expired": bool(snapshot.get("expired")),
                    "ready": bool(snapshot.get("ready")),
                    "ttl_seconds": snapshot.get("ttl_seconds"),
                    "age_seconds": snapshot.get("age_seconds"),
                },
            }
            return {
                "ok": True,
                "success": True,
                "execution_state": "COMPLETED",
                "action": action_norm,
                "agent_id": agent_id_norm,
                "data": data,
                "meta": meta,
            }

        if q == "ops.daily_brief":
            pending_count = None
            try:
                from services.approval_state_service import get_approval_state

                pending = get_approval_state().list_pending()
                if isinstance(pending, list):
                    pending_count = len(pending)
            except Exception:
                pending_count = None

            if not snapshot:
                meta["missing_inputs"] = ["knowledge_snapshot"]

            data = {
                "kind": "ops.daily_brief",
                "snapshot_health": {
                    "ready": bool(snapshot.get("ready")),
                    "status": snapshot.get("status"),
                    "age_seconds": snapshot.get("age_seconds"),
                    "expired": bool(snapshot.get("expired")),
                },
                "approvals": {
                    "pending_count": pending_count,
                },
                "brief": {
                    "highlights": [
                        "Review pending approvals and unblock executions.",
                        "Check snapshot health before acting on stale data.",
                    ],
                    "next_actions": [
                        "Run ops.snapshot_health and confirm snapshot ready.",
                        "Approve/reject pending items as needed.",
                    ],
                },
            }
            return {
                "ok": True,
                "success": True,
                "execution_state": "COMPLETED",
                "action": action_norm,
                "agent_id": agent_id_norm,
                "data": data,
                "meta": meta,
            }

        if q == "ops.kpi_weekly_summary_preview":
            if not snapshot:
                meta["missing_inputs"] = ["knowledge_snapshot"]
            data = {
                "kind": "ops.kpi_weekly_summary_preview",
                "note": "Preview only (read-only). Uses local snapshot metadata; KPI extraction is best-effort.",
                "snapshot_meta": {
                    "ready": bool(snapshot.get("ready")),
                    "status": snapshot.get("status"),
                    "generated_at": snapshot.get("generated_at"),
                },
                "kpis": {},
            }
            return {
                "ok": True,
                "success": True,
                "execution_state": "COMPLETED",
                "action": action_norm,
                "agent_id": agent_id_norm,
                "data": data,
                "meta": meta,
            }

        # Unknown read-only query: deterministic response.
        data = {
            "kind": "read_only.query",
            "query": q,
            "supported_queries": [
                "ops.daily_brief",
                "ops.snapshot_health",
                "ops.kpi_weekly_summary_preview",
            ],
        }
        return {
            "ok": True,
            "success": True,
            "execution_state": "COMPLETED",
            "action": action_norm,
            "agent_id": agent_id_norm,
            "data": data,
            "meta": meta,
        }

    if action_norm in {"sop.query", "process.query"}:
        q = _ensure_str(params_norm.get("query") or params_norm.get("q") or "")
        data = {
            "source": "local",
            "query": q,
            "items": [],
        }
        return {
            "ok": True,
            "success": True,
            "execution_state": "COMPLETED",
            "action": action_norm,
            "agent_id": agent_id_norm,
            "data": data,
        }

    if action_norm == "analysis.run":
        expr = (
            params_norm.get("expression")
            or params_norm.get("expr")
            or params_norm.get("input")
            or ""
        )
        expr_str = _ensure_str(expr)
        result = _SafeArithmetic.eval_expr(expr_str)
        data = {
            "source": "local",
            "expression": expr_str,
            "result": result,
        }
        return {
            "ok": True,
            "success": True,
            "execution_state": "COMPLETED",
            "action": action_norm,
            "agent_id": agent_id_norm,
            "data": data,
        }

    # ------------------- DRAFTS -------------------
    if action_norm == "draft.outreach":
        to = _ensure_str(params_norm.get("to") or "")
        subject = _ensure_str(params_norm.get("subject") or "")
        context = _ensure_str(params_norm.get("context") or "")
        text = (
            f"Subject: {subject or '[no subject]'}\n"
            f"To: {to or '[no recipient]'}\n\n"
            f"Hi,\n\n{context or 'Quick note — following up.'}\n\nBest,\n"
        )
        return {
            "ok": True,
            "success": True,
            "execution_state": "COMPLETED",
            "action": action_norm,
            "agent_id": agent_id_norm,
            "output": {"text": text},
        }

    if action_norm == "draft.spec":
        title = _ensure_str(params_norm.get("title") or params_norm.get("name") or "")
        problem = _ensure_str(params_norm.get("problem") or "")
        text = (
            f"Spec: {title or '[untitled]'}\n\n"
            f"Problem:\n{problem or '-'}\n\n"
            "Scope:\n-\n\nAcceptance Criteria:\n-\n"
        )
        return {
            "ok": True,
            "success": True,
            "execution_state": "COMPLETED",
            "action": action_norm,
            "agent_id": agent_id_norm,
            "output": {"text": text},
        }

    if action_norm == "draft.issue":
        title = _ensure_str(params_norm.get("title") or "")
        body = _ensure_str(
            params_norm.get("body") or params_norm.get("description") or ""
        )
        text = (
            f"Issue: {title or '[untitled]'}\n\n"
            f"Description:\n{body or '-'}\n\n"
            "Tasks:\n- [ ]\n"
        )
        return {
            "ok": True,
            "success": True,
            "execution_state": "COMPLETED",
            "action": action_norm,
            "agent_id": agent_id_norm,
            "output": {"text": text},
        }

    raise NotImplementedError(action_norm)
