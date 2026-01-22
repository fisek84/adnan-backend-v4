from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


_READ_ONLY_TYPES = {
    "created_by",
    "created_time",
    "last_edited_by",
    "last_edited_time",
    "formula",
    "rollup",
    "unique_id",
}


def _ensure_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return str(v)
    except Exception:
        return ""


def _as_trimmed_str(v: Any) -> str:
    return _ensure_str(v).strip()


def _as_list_of_str(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out: List[str] = []
        for x in v:
            s = _as_trimmed_str(x)
            if s:
                out.append(s)
        return out
    s = _as_trimmed_str(v)
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _looks_like_uuidish(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    if s.count("-") >= 4:
        return True
    return bool(re.fullmatch(r"[0-9a-fA-F]{32}", s))


@dataclass(frozen=True)
class PatchIssue:
    severity: str  # "warning" | "error" (we only emit errors)
    code: str
    field: Optional[str] = None
    message: str = ""
    provided: Any = None
    allowed: Optional[List[str]] = None
    source: str = "patches"
    op_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "source": self.source,
        }
        if self.field is not None:
            out["field"] = self.field
        if self.op_id is not None:
            out["op_id"] = self.op_id
        if self.message:
            out["message"] = self.message
        if self.provided is not None:
            out["provided"] = self.provided
        if self.allowed is not None:
            out["allowed"] = self.allowed
        return out


def _issue(
    code: str,
    *,
    op_id: Optional[str] = None,
    field: Optional[str] = None,
    message: str,
    provided: Any = None,
    allowed: Optional[Sequence[str]] = None,
) -> PatchIssue:
    return PatchIssue(
        severity="error",
        code=code,
        field=field,
        message=message,
        provided=provided,
        allowed=list(allowed) if allowed is not None else None,
        source="patches",
        op_id=op_id,
    )


def _infer_db_key(op_intent: str, payload: Dict[str, Any]) -> Optional[str]:
    dk = payload.get("db_key")
    if isinstance(dk, str) and dk.strip():
        return dk.strip()

    oi = (op_intent or "").strip().lower()
    if oi == "create_goal":
        return "goals"
    if oi == "create_task":
        return "tasks"
    if oi == "create_project":
        return "projects"
    return None


def _normalize_change_to_property_spec(
    *,
    field_name: str,
    schema_type: str,
    value: Any,
    all_op_ids: Sequence[str],
) -> Tuple[Optional[Dict[str, Any]], List[PatchIssue]]:
    """Convert a patch value to a property_specs entry.

    We keep this deliberately minimal and strict, because raw execution must be 1:1.
    """

    issues: List[PatchIssue] = []
    t = (schema_type or "").strip().lower()

    if t == "title":
        s = _as_trimmed_str(value)
        if not s:
            # allow clearing by setting empty -> drop
            return None, issues
        return {"type": "title", "text": s}, issues

    if t in {"rich_text", "text"}:
        s = _as_trimmed_str(value)
        if not s:
            return None, issues
        return {"type": "rich_text", "text": s}, issues

    if t in {"select", "status"}:
        s = _as_trimmed_str(value)
        if not s:
            return None, issues
        return {"type": t, "name": s}, issues

    if t == "multi_select":
        names = _as_list_of_str(value)
        if not names:
            return None, issues
        return {"type": "multi_select", "names": names}, issues

    if t == "date":
        s = _as_trimmed_str(value)
        if not s:
            return None, issues
        return {"type": "date", "start": s}, issues

    if t == "number":
        if value is None:
            return None, issues
        try:
            num = float(value)
        except Exception:
            issues.append(
                _issue(
                    "invalid_number",
                    field=field_name,
                    message=f"Invalid number for '{field_name}'.",
                    provided=value,
                )
            )
            return None, issues
        return {"type": "number", "number": num}, issues

    if t == "checkbox":
        v = value
        if isinstance(v, str):
            sv = v.strip().lower()
            if sv in {"true", "yes", "da", "1"}:
                v = True
            elif sv in {"false", "no", "ne", "0"}:
                v = False
        if not isinstance(v, bool):
            issues.append(
                _issue(
                    "invalid_checkbox",
                    field=field_name,
                    message=f"Invalid checkbox for '{field_name}'.",
                    provided=value,
                )
            )
            return None, issues
        return {"type": "checkbox", "checkbox": v}, issues

    if t == "people":
        tokens = _as_list_of_str(value)
        if not tokens:
            return None, issues
        emails = [t0 for t0 in tokens if "@" in t0]
        names = [t0 for t0 in tokens if "@" not in t0]
        spec: Dict[str, Any] = {"type": "people"}
        if emails:
            spec["emails"] = emails
        if names:
            spec["names"] = names
        return spec, issues

    if t == "relation":
        tokens = _as_list_of_str(value)
        if not tokens:
            return None, issues

        ok_ids: List[str] = []
        for tok in tokens:
            if tok.startswith("$") and len(tok) > 1:
                ref = tok[1:].strip()
                if ref and ref in set(all_op_ids):
                    ok_ids.append(tok)
                else:
                    issues.append(
                        _issue(
                            "invalid_relation_ref",
                            field=field_name,
                            message=f"Relation ref '{tok}' does not match any op_id in this batch.",
                            provided=tok,
                        )
                    )
                continue

            if _looks_like_uuidish(tok):
                ok_ids.append(tok)
            else:
                issues.append(
                    _issue(
                        "invalid_relation_id",
                        field=field_name,
                        message=f"Relation value for '{field_name}' must be a Notion page_id (uuid-ish) or '$op_id' reference.",
                        provided=tok,
                    )
                )

        if issues:
            return None, issues

        return {"type": "relation", "ids": ok_ids}, issues

    issues.append(
        _issue(
            "unsupported_type",
            field=field_name,
            message=f"Unsupported field type '{schema_type}' for patches.",
            provided=value,
        )
    )
    return None, issues


def apply_patches_to_batch_operations(
    *,
    operations: List[Dict[str, Any]],
    patches: Any,
    schema_by_db_key: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """Apply enterprise preview patches to batch operations.

    Returns:
      (patched_operations, issues_by_op_id, global_issues)

    Notes:
    - Never mutates input operations.
    - Only writes into op.payload.property_specs.
    - Validates op_id existence, field existence, and read-only properties.
    """

    ops_in = operations if isinstance(operations, list) else []
    all_op_ids = [
        _as_trimmed_str(op.get("op_id"))
        for op in ops_in
        if isinstance(op, dict) and _as_trimmed_str(op.get("op_id"))
    ]

    global_issues: List[Dict[str, Any]] = []
    issues_by_op_id: Dict[str, List[Dict[str, Any]]] = {}

    if patches is None:
        # No-op
        return (
            [dict(op) if isinstance(op, dict) else {} for op in ops_in],
            issues_by_op_id,
            global_issues,
        )

    if not isinstance(patches, list):
        global_issues.append(
            _issue(
                "invalid_patches",
                message="'patches' must be a list of {op_id, changes} objects.",
                provided=patches,
            ).to_dict()
        )
        return (
            [dict(op) if isinstance(op, dict) else {} for op in ops_in],
            issues_by_op_id,
            global_issues,
        )

    # Build deterministic list of patch entries (in given order)
    patch_entries: List[Tuple[str, Dict[str, Any]]] = []
    for p in patches:
        if not isinstance(p, dict):
            global_issues.append(
                _issue(
                    "invalid_patch",
                    message="Each patch entry must be an object.",
                    provided=p,
                ).to_dict()
            )
            continue
        op_id = _as_trimmed_str(p.get("op_id"))
        changes = p.get("changes")
        if not op_id:
            global_issues.append(
                _issue(
                    "missing_op_id",
                    message="Patch entry missing non-empty 'op_id'.",
                    provided=p,
                ).to_dict()
            )
            continue
        if not isinstance(changes, dict) or not changes:
            global_issues.append(
                _issue(
                    "missing_changes",
                    op_id=op_id,
                    message="Patch entry missing non-empty 'changes' object.",
                    provided=p,
                ).to_dict()
            )
            continue

        patch_entries.append((op_id, dict(changes)))

    # Fast index
    op_by_id: Dict[str, Dict[str, Any]] = {}
    for op in ops_in:
        if not isinstance(op, dict):
            continue
        oid = _as_trimmed_str(op.get("op_id"))
        if oid:
            op_by_id[oid] = op

    for op_id, _ in patch_entries:
        if op_id not in op_by_id:
            global_issues.append(
                _issue(
                    "unknown_op_id",
                    op_id=op_id,
                    message=f"Unknown op_id '{op_id}' (not found in operations).",
                ).to_dict()
            )

    # Apply patches (copy-on-write)
    patched_ops: List[Dict[str, Any]] = []

    # Pre-group changes per op_id to reduce copies.
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for op_id, changes in patch_entries:
        grouped.setdefault(op_id, []).append(changes)

    for op in ops_in:
        if not isinstance(op, dict):
            continue

        op_id = _as_trimmed_str(op.get("op_id"))
        if not op_id or op_id not in grouped:
            patched_ops.append(dict(op))
            continue

        op_out = dict(op)
        payload0 = op.get("payload")
        payload = dict(payload0) if isinstance(payload0, dict) else {}

        op_intent = _as_trimmed_str(op.get("intent"))
        db_key = _infer_db_key(op_intent, payload) or ""
        schema = schema_by_db_key.get(db_key) or {}

        try:
            from services.notion_patch_validation import SchemaNameResolver  # noqa: PLC0415

            resolver = SchemaNameResolver(schema if isinstance(schema, dict) else {})
        except Exception:
            resolver = None

        def _resolve_field(raw_field: str) -> str:
            if resolver is None:
                return raw_field.strip() if isinstance(raw_field, str) else ""
            return resolver.resolve(raw_field)

        specs0 = payload.get("property_specs")
        specs = dict(specs0) if isinstance(specs0, dict) else {}

        for changes in grouped.get(op_id, []):
            for raw_field, raw_value in changes.items():
                if not isinstance(raw_field, str) or not raw_field.strip():
                    issues_by_op_id.setdefault(op_id, []).append(
                        _issue(
                            "invalid_field",
                            op_id=op_id,
                            message="Patch field name must be a non-empty string.",
                            provided=raw_field,
                        ).to_dict()
                    )
                    continue

                resolved = _resolve_field(raw_field)
                if not resolved:
                    issues_by_op_id.setdefault(op_id, []).append(
                        _issue(
                            "unknown_field",
                            op_id=op_id,
                            field=raw_field.strip(),
                            message=f"Unknown field '{raw_field.strip()}' for db_key='{db_key}'.",
                            provided=raw_value,
                        ).to_dict()
                    )
                    continue

                st = schema.get(resolved)
                st = st if isinstance(st, dict) else {}
                schema_type = _as_trimmed_str(st.get("type"))
                is_ro = bool(st.get("read_only") is True) or (
                    schema_type.strip().lower() in _READ_ONLY_TYPES
                )
                if is_ro:
                    issues_by_op_id.setdefault(op_id, []).append(
                        _issue(
                            "read_only_field",
                            op_id=op_id,
                            field=resolved,
                            message=f"Field '{resolved}' is read-only and cannot be patched.",
                            provided=raw_value,
                        ).to_dict()
                    )
                    continue

                spec, spec_issues = _normalize_change_to_property_spec(
                    field_name=resolved,
                    schema_type=schema_type,
                    value=raw_value,
                    all_op_ids=all_op_ids,
                )
                if spec_issues:
                    for it in spec_issues:
                        issues_by_op_id.setdefault(op_id, []).append(
                            PatchIssue(
                                **{
                                    **it.__dict__,
                                    "op_id": op_id,
                                }
                            ).to_dict()
                            if isinstance(it, PatchIssue)
                            else it.to_dict()
                        )
                    continue

                # allow clearing
                if spec is None:
                    if resolved in specs:
                        del specs[resolved]
                    continue

                specs[resolved] = spec

        payload["property_specs"] = specs
        op_out["payload"] = payload
        patched_ops.append(op_out)

    return patched_ops, issues_by_op_id, global_issues
