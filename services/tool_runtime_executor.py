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

            if isinstance(node, ast.UnaryOp) and isinstance(node.op, cls._ALLOWED_UNARYOPS):
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
        data = {
            "source": "local",
            "echo": {k: v for k, v in params_norm.items() if k != "action"},
        }
        return {
            "ok": True,
            "success": True,
            "execution_state": "COMPLETED",
            "action": action_norm,
            "agent_id": agent_id_norm,
            "data": data,
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
        body = _ensure_str(params_norm.get("body") or params_norm.get("description") or "")
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
