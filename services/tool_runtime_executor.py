from __future__ import annotations

import ast
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _ensure_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _ensure_str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _ensure_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _now_utc_date_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _parse_date_iso(s: Any) -> Optional[datetime]:
    if not isinstance(s, str):
        return None
    ss = s.strip()
    if not ss:
        return None
    # Accept full ISO or date-only.
    try:
        if len(ss) == 10 and ss[4] == "-" and ss[7] == "-":
            return datetime.fromisoformat(ss).replace(tzinfo=timezone.utc)
        if ss.endswith("Z"):
            ss = ss[:-1] + "+00:00"
        dt = datetime.fromisoformat(ss)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _truncate(s: str, max_len: int) -> str:
    txt = _ensure_str(s)
    if max_len <= 0:
        return ""
    if len(txt) <= max_len:
        return txt
    return txt[: max(0, max_len - 1)].rstrip() + "…"


def _snapshot_payload(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
    return payload if isinstance(payload, dict) else {}


def _snapshot_databases(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    payload = _snapshot_payload(snapshot)
    dbs = payload.get("databases")
    return dbs if isinstance(dbs, dict) else {}


def _db_items(snapshot: Dict[str, Any], *keys: str) -> List[Dict[str, Any]]:
    """Return snapshot payload databases[db_key].items for the first present key.

    Backward-compatible:
    - falls back to payload[db_key] list (KnowledgeSnapshotService mirrors it)
    """

    payload = _snapshot_payload(snapshot)
    dbs = _snapshot_databases(snapshot)

    for k in keys:
        kk = _ensure_str(k).lower()
        if not kk:
            continue
        section = dbs.get(kk)
        if isinstance(section, dict):
            items = section.get("items")
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]

        items2 = payload.get(kk)
        if isinstance(items2, list):
            return [x for x in items2 if isinstance(x, dict)]

    return []


def _item_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    fields = item.get("fields")
    return fields if isinstance(fields, dict) else {}


def _pick_field_value(fields: Dict[str, Any], candidates: Iterable[str]) -> Any:
    # Case-insensitive exact match, then normalized punctuation/space match.
    by_lower = {str(k).strip().lower(): k for k in fields.keys() if isinstance(k, str)}
    for name in candidates:
        n = (name or "").strip().lower()
        if not n:
            continue
        k = by_lower.get(n)
        if k is not None:
            return fields.get(k)
    return None


def _as_text(v: Any, *, max_len: int = 140) -> str:
    if isinstance(v, str):
        return _truncate(v, max_len)
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        parts = [str(x).strip() for x in v if str(x).strip()]
        return _truncate(", ".join(parts), max_len)
    return ""


def _priority_score(v: Any) -> int:
    s = _ensure_str(v).lower()
    if not s:
        return 0
    if any(x in s for x in ("urgent", "p0", "critical", "high")):
        return 3
    if any(x in s for x in ("medium", "p1", "normal")):
        return 2
    if any(x in s for x in ("low", "p2", "p3")):
        return 1
    return 0


def _is_done_status(v: Any) -> bool:
    s = _ensure_str(v).lower()
    if not s:
        return False
    done_markers = ("done", "completed", "complete", "closed", "archived", "resolved")
    return any(m in s for m in done_markers)


def _extract_due_date(fields: Dict[str, Any]) -> Optional[datetime]:
    v = _pick_field_value(
        fields,
        (
            "Due",
            "Due Date",
            "Deadline",
            "Target Deadline",
            "End Date",
            "Date",
        ),
    )
    if isinstance(v, dict):
        # Some snapshot builders may store {"start": "..."}
        v = v.get("start")
    return _parse_date_iso(v)


def _stable_sort_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(it: Dict[str, Any]) -> Tuple[str, str]:
        title = _ensure_str(it.get("title") or "")
        iid = _ensure_str(it.get("id") or it.get("notion_id") or "")
        return (title.lower(), iid)

    return sorted(items, key=key)


def _cap_items(items: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    if n <= 0:
        return []
    return list(items[:n])


def _ops_daily_brief_from_snapshot(
    snapshot: Dict[str, Any],
    *,
    max_items: int = 10,
    max_text_len: int = 140,
) -> Dict[str, Any]:
    tasks = _db_items(snapshot, "tasks", "task")
    goals = _db_items(snapshot, "goals", "goal")
    projects = _db_items(snapshot, "projects", "project")

    today = datetime.now(timezone.utc).date()

    open_tasks: List[Dict[str, Any]] = []
    overdue_tasks: List[Dict[str, Any]] = []
    scored_tasks: List[Tuple[int, Dict[str, Any]]] = []

    for it in tasks:
        fields = _item_fields(it)
        status = _pick_field_value(fields, ("Status", "State"))
        priority = _pick_field_value(fields, ("Priority", "Prio"))
        due_dt = _extract_due_date(fields)
        is_done = _is_done_status(status)
        if not is_done:
            open_tasks.append(it)
        is_overdue = bool((not is_done) and due_dt and due_dt.date() < today)
        if is_overdue:
            overdue_tasks.append(it)

        score = 0
        score += _priority_score(priority)
        if is_overdue:
            score += 2
        if not is_done:
            score += 1

        scored_tasks.append((score, it))

    scored_tasks_sorted = sorted(
        scored_tasks,
        key=lambda x: (
            -int(x[0]),
            _ensure_str(x[1].get("title") or "").lower(),
            _ensure_str(x[1].get("id") or x[1].get("notion_id") or ""),
        ),
    )

    top_urgent: List[Dict[str, Any]] = []
    for score, it in scored_tasks_sorted:
        if len(top_urgent) >= 5:
            break
        if int(score) <= 0:
            continue
        top_urgent.append(it)

    def _format_item(it: Dict[str, Any]) -> Dict[str, Any]:
        fields = _item_fields(it)
        title = _truncate(_ensure_str(it.get("title") or ""), max_text_len)
        status = _as_text(_pick_field_value(fields, ("Status", "State")), max_len=60)
        priority = _as_text(_pick_field_value(fields, ("Priority", "Prio")), max_len=40)
        due_dt = _extract_due_date(fields)
        blockers = _as_text(
            _pick_field_value(fields, ("Blockers", "Blocked By", "Blocking", "Risks")),
            max_len=120,
        )
        progress = _pick_field_value(fields, ("Progress", "%", "Percent"))
        try:
            progress_num = float(progress) if isinstance(progress, (int, float, str)) and str(progress).strip() else None
        except Exception:
            progress_num = None

        return {
            "id": _ensure_str(it.get("id") or it.get("notion_id") or ""),
            "title": title,
            "status": status,
            "priority": priority,
            "due_date": (due_dt.date().isoformat() if due_dt else None),
            "blockers": blockers or None,
            "progress": progress_num,
            "url": _ensure_str(it.get("url") or "") or None,
        }

    active_goals = [g for g in goals if not _is_done_status(_pick_field_value(_item_fields(g), ("Status", "State")))]
    active_projects = [p for p in projects if not _is_done_status(_pick_field_value(_item_fields(p), ("Status", "State")))]

    active_goals = _stable_sort_items(active_goals)
    active_projects = _stable_sort_items(active_projects)

    payload = {
        "kind": "ops.daily_brief",
        "summary": {
            "as_of_date": _now_utc_date_iso(),
            "snapshot": {
                "ready": bool(snapshot.get("ready")),
                "status": snapshot.get("status"),
                "age_seconds": snapshot.get("age_seconds"),
                "expired": bool(snapshot.get("expired")),
            },
            "counts": {
                "open_tasks": int(len(open_tasks)),
                "overdue_tasks": int(len(overdue_tasks)),
                "active_goals": int(len(active_goals)),
                "active_projects": int(len(active_projects)),
            },
        },
        "tasks": {
            "open_count": int(len(open_tasks)),
            "overdue_count": int(len(overdue_tasks)),
            "top_urgent": [_format_item(x) for x in _cap_items(top_urgent, max_items)],
        },
        "goals": {
            "active_count": int(len(active_goals)),
            "items": [_format_item(x) for x in _cap_items(active_goals, max_items)],
        },
        "projects": {
            "active_count": int(len(active_projects)),
            "items": [_format_item(x) for x in _cap_items(active_projects, max_items)],
        },
        "approvals": {"pending_count": None},
        "recommendations": [],
    }

    # Deterministic recommendations (best-effort).
    recs: List[str] = []
    if int(len(overdue_tasks)) > 0:
        recs.append(f"Triage overdue tasks: {len(overdue_tasks)}")
    if int(len(top_urgent)) > 0:
        recs.append("Focus on top urgent tasks first")
    if not recs:
        recs.append("No urgent issues detected from snapshot")
    payload["recommendations"] = recs[:5]

    return payload


def _ops_kpi_weekly_preview_from_snapshot(
    snapshot: Dict[str, Any],
    *,
    max_metrics: int = 8,
    max_text_len: int = 120,
) -> Dict[str, Any]:
    items = _db_items(snapshot, "kpi", "kpis")
    stable_items = list(items)

    def _row_sort_key(it: Dict[str, Any]) -> Tuple[int, str, str]:
        fields = _item_fields(it)
        period = _pick_field_value(fields, ("Period", "Week", "Cycle", "Date", "Start"))
        dt = _parse_date_iso(period)
        ts = int(dt.timestamp()) if dt else 0
        title = _ensure_str(it.get("title") or "").lower()
        iid = _ensure_str(it.get("id") or it.get("notion_id") or "")
        return (ts, title, iid)

    stable_items = sorted(stable_items, key=_row_sort_key, reverse=True)

    latest = stable_items[0] if stable_items else None
    prev = stable_items[1] if len(stable_items) > 1 else None

    known = [
        "Outreach",
        "Outreach Count",
        "Leads",
        "Leads Count",
        "Conversions",
        "ConversionsCount",
        "Revenue",
        "RevenueMomentum",
        "MRR",
        "ARR",
        "Meetings",
        "Calls",
    ]

    def _numeric_fields(it: Optional[Dict[str, Any]]) -> Dict[str, float]:
        if not isinstance(it, dict):
            return {}
        fields = _item_fields(it)
        out: Dict[str, float] = {}
        for k, v in fields.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out[k.strip()] = float(v)
                continue
            if isinstance(v, str) and v.strip():
                try:
                    out[k.strip()] = float(v.strip())
                except Exception:
                    continue
        return out

    latest_nums = _numeric_fields(latest)
    prev_nums = _numeric_fields(prev)

    # Choose metrics deterministically: known first (case-insensitive), then other numeric keys alpha.
    chosen: List[str] = []
    latest_by_lc = {k.lower(): k for k in latest_nums.keys()}
    for k in known:
        kk = (k or "").strip().lower()
        if not kk:
            continue
        actual = latest_by_lc.get(kk)
        if actual and actual not in chosen:
            chosen.append(actual)
        if len(chosen) >= max_metrics:
            break
    if len(chosen) < max_metrics:
        rest = sorted([k for k in latest_nums.keys() if k not in set(chosen)])
        for k in rest:
            chosen.append(k)
            if len(chosen) >= max_metrics:
                break

    def _period_label(it: Optional[Dict[str, Any]]) -> str:
        if not isinstance(it, dict):
            return ""
        fields = _item_fields(it)
        p = _pick_field_value(fields, ("Period", "Week", "Cycle", "Date", "Start"))
        if isinstance(p, str) and p.strip():
            return _truncate(p.strip(), 32)
        # fallback: title
        return _truncate(_ensure_str(it.get("title") or ""), 32)

    latest_period = _period_label(latest)
    prev_period = _period_label(prev)

    metrics: List[Dict[str, Any]] = []
    for k in chosen:
        cur = latest_nums.get(k)
        prevv = prev_nums.get(k)
        direction = "flat"
        delta = None
        if cur is not None and prevv is not None:
            delta = float(cur) - float(prevv)
            if abs(delta) < 1e-9:
                direction = "flat"
            elif delta > 0:
                direction = "up"
            else:
                direction = "down"
        metrics.append(
            {
                "name": _truncate(k, max_text_len),
                "current": cur,
                "previous": prevv,
                "delta": delta,
                "trend": direction,
            }
        )

    data = {
        "kind": "ops.kpi_weekly_summary_preview",
        "note": "Preview only (read-only). Best-effort KPI extraction from snapshot payload (no writes).",
        "snapshot": {
            "ready": bool(snapshot.get("ready")),
            "status": snapshot.get("status"),
            "generated_at": snapshot.get("generated_at"),
            "age_seconds": snapshot.get("age_seconds"),
        },
        "periods": {
            "current": latest_period or None,
            "previous": prev_period or None,
            "row_count": int(len(items)),
        },
        "metrics": metrics,
    }

    if not items:
        data["missing_reason"] = "no_kpi_rows_in_snapshot"
    elif not metrics:
        data["missing_reason"] = "no_numeric_kpi_fields_in_snapshot"

    return data


def _ops_snapshot_health_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    dbs = _snapshot_databases(snapshot)
    keys = sorted([k for k in dbs.keys() if isinstance(k, str) and k.strip()])
    db_counts: Dict[str, int] = {}
    db_errors: Dict[str, Any] = {}
    for k in keys:
        section = dbs.get(k)
        if not isinstance(section, dict):
            continue
        row_count = section.get("row_count")
        try:
            db_counts[k] = int(row_count) if row_count is not None else int(len(_ensure_list(section.get("items"))))
        except Exception:
            db_counts[k] = int(len(_ensure_list(section.get("items"))))

        last_err = section.get("last_error")
        if last_err:
            db_errors[k] = last_err

    return {
        "kind": "ops.snapshot_health",
        "snapshot_meta": {
            "schema_version": snapshot.get("schema_version"),
            "status": snapshot.get("status"),
            "status_detail": snapshot.get("status_detail"),
            "generated_at": snapshot.get("generated_at"),
            "last_sync": snapshot.get("last_sync"),
            "expired": bool(snapshot.get("expired")),
            "ready": bool(snapshot.get("ready")),
            "ttl_seconds": snapshot.get("ttl_seconds"),
            "age_seconds": snapshot.get("age_seconds"),
        },
        "databases": {
            "present_keys": keys,
            "counts": db_counts,
            "errors": db_errors,
        },
    }


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
            data = _ops_snapshot_health_from_snapshot(snapshot)
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

            data = _ops_daily_brief_from_snapshot(snapshot)
            # Preserve approvals in stable location.
            try:
                approvals = data.get("approvals") if isinstance(data.get("approvals"), dict) else {}
                approvals["pending_count"] = pending_count
                data["approvals"] = approvals
            except Exception:
                pass

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
            data = _ops_kpi_weekly_preview_from_snapshot(snapshot)
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
