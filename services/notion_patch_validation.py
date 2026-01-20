from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


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


def _looks_like_iso_date(s: str) -> bool:
    # Minimal, deterministic (no time) check.
    # Notion accepts YYYY-MM-DD (and also datetime); keep strict for safety.
    if not s:
        return False
    import re

    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()))


@dataclass(frozen=True)
class ValidationIssue:
    severity: str  # "warning" | "error"
    code: str
    field: Optional[str] = None
    message: str = ""
    provided: Any = None
    allowed: Optional[List[str]] = None
    source: Optional[str] = None  # "wrapper_patch" | "property_specs" | ...

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
        }
        if self.field is not None:
            out["field"] = self.field
        if self.message:
            out["message"] = self.message
        if self.provided is not None:
            out["provided"] = self.provided
        if self.allowed is not None:
            out["allowed"] = self.allowed
        if self.source is not None:
            out["source"] = self.source
        return out


class SchemaNameResolver:
    def __init__(self, schema: Dict[str, Any]):
        self.schema = schema if isinstance(schema, dict) else {}
        schema_names = [
            k for k in self.schema.keys() if isinstance(k, str) and k.strip()
        ]
        self.schema_by_cf = {k.casefold(): k for k in schema_names}
        self.title_props = [
            k for k in schema_names if (self.schema.get(k) or {}).get("type") == "title"
        ]

    def resolve(self, raw_name: str) -> str:
        cand = (raw_name or "").strip()
        if not cand:
            return ""

        # Prefer the writable date field when both exist (Tasks DB can have
        # a computed 'Deadline' plus a writable 'Due Date').
        if cand in self.schema:
            if cand in {"Deadline", "Due Date"}:
                t = _as_trimmed_str((self.schema.get(cand) or {}).get("type"))
                if t and t != "date":
                    alt = "Due Date" if cand == "Deadline" else "Deadline"
                    t_alt = _as_trimmed_str((self.schema.get(alt) or {}).get("type"))
                    if t_alt == "date":
                        return alt
            return cand

        cf = cand.casefold()
        if cf in self.schema_by_cf:
            return self.schema_by_cf[cf]

        internal = ""
        try:
            from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415

            internal = NotionKeywordMapper.translate_property_name(cand)
            km = NotionKeywordMapper.normalize_field_name(cand)
            if isinstance(km, str) and km in self.schema:
                return km
            if isinstance(km, str) and km.casefold() in self.schema_by_cf:
                return self.schema_by_cf[km.casefold()]
        except Exception:
            internal = ""

        if internal in {"name", "title"} and self.title_props:
            return self.title_props[0]

        if internal == "due_date":
            if (
                "Due Date" in self.schema
                and _as_trimmed_str((self.schema.get("Due Date") or {}).get("type"))
                == "date"
            ):
                return "Due Date"
            if (
                "Deadline" in self.schema
                and _as_trimmed_str((self.schema.get("Deadline") or {}).get("type"))
                == "date"
            ):
                return "Deadline"
        if internal == "deadline":
            if (
                "Due Date" in self.schema
                and _as_trimmed_str((self.schema.get("Due Date") or {}).get("type"))
                == "date"
            ):
                return "Due Date"
            if (
                "Deadline" in self.schema
                and _as_trimmed_str((self.schema.get("Deadline") or {}).get("type"))
                == "date"
            ):
                return "Deadline"

        return ""


def _validation_mode(mode: Optional[str]) -> str:
    m = (mode or "").strip().lower()
    return "strict" if m == "strict" else "warn"


def _severity_for(code: str, *, mode: str) -> str:
    # warn: never blocks
    if mode != "strict":
        return "warning"

    # strict: errors that should block approval
    if code in {
        "unknown_field",
        "requires_ids",
        "invalid_option",
        "invalid_date",
        "invalid_number",
        "invalid_checkbox",
        "unsupported_type",
    }:
        return "error"

    # keep these as warnings even in strict (informational)
    return "warning"


def _issue(
    code: str,
    *,
    mode: str,
    field: Optional[str] = None,
    message: str = "",
    provided: Any = None,
    allowed: Optional[List[str]] = None,
    source: Optional[str] = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity=_severity_for(code, mode=mode),
        code=code,
        field=field,
        message=message,
        provided=provided,
        allowed=allowed,
        source=source,
    )


def _validate_select_like(
    *,
    mode: str,
    field: str,
    provided: Any,
    schema_type: str,
    schema_options: Sequence[str],
    source: str,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    val = _as_trimmed_str(provided)
    if not val:
        return issues

    opts = [o for o in schema_options if isinstance(o, str) and o.strip()]
    if opts and val not in opts:
        # If only casing differs, accept (execution will normalize/should use exact option).
        cf = val.casefold()
        cf_matches = [o for o in opts if o.casefold() == cf]
        if len(cf_matches) == 1:
            return issues
        issues.append(
            _issue(
                "invalid_option",
                mode=mode,
                field=field,
                provided=val,
                allowed=list(opts),
                source=source,
                message=f"Invalid {schema_type} option for '{field}': '{val}'.",
            )
        )
    return issues


def validate_wrapper_patch_against_schema(
    *,
    db_key: str,
    schema: Dict[str, Any],
    wrapper_patch: Optional[Dict[str, Any]],
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    mode_n = _validation_mode(mode)
    issues: List[ValidationIssue] = []

    patch = wrapper_patch if isinstance(wrapper_patch, dict) else {}
    if not patch:
        return {
            "mode": mode_n,
            "db_key": (db_key or "").strip() or None,
            "issues": [],
            "can_approve": True,
            "summary": {"errors": 0, "warnings": 0},
        }

    resolver = SchemaNameResolver(schema)

    for raw_field, raw_val in patch.items():
        if not isinstance(raw_field, str) or not raw_field.strip():
            continue

        resolved = resolver.resolve(raw_field)
        if not resolved:
            issues.append(
                _issue(
                    "unknown_field",
                    mode=mode_n,
                    field=raw_field.strip(),
                    provided=raw_val,
                    source="wrapper_patch",
                    message=f"Unknown field '{raw_field.strip()}' for db_key='{(db_key or '').strip()}'.",
                )
            )
            continue

        st = schema.get(resolved)
        st = st if isinstance(st, dict) else {}
        p_type = _as_trimmed_str(st.get("type"))
        if not p_type:
            continue

        if p_type in {"created_by", "last_edited_by", "formula", "rollup"}:
            issues.append(
                _issue(
                    "unsupported_type",
                    mode=mode_n,
                    field=resolved,
                    provided=raw_val,
                    source="wrapper_patch",
                    message=f"Field '{resolved}' is computed/read-only ({p_type}).",
                )
            )
            continue

        if p_type == "relation":
            issues.append(
                _issue(
                    "requires_ids",
                    mode=mode_n,
                    field=resolved,
                    provided=raw_val,
                    source="wrapper_patch",
                    message=f"Field '{resolved}' is a relation and requires IDs.",
                )
            )
            continue

        if p_type in {"select", "status"}:
            opts = st.get("options") if isinstance(st.get("options"), list) else []
            issues.extend(
                _validate_select_like(
                    mode=mode_n,
                    field=resolved,
                    provided=raw_val,
                    schema_type=p_type,
                    schema_options=opts,
                    source="wrapper_patch",
                )
            )
            continue

        if p_type == "date":
            s = _as_trimmed_str(raw_val)
            if s and not _looks_like_iso_date(s):
                # We allow natural language in execution via COOTranslationService.
                # Validation stays conservative: warn/err in strict to avoid silent miswrites.
                issues.append(
                    _issue(
                        "invalid_date",
                        mode=mode_n,
                        field=resolved,
                        provided=s,
                        source="wrapper_patch",
                        message=f"Date for '{resolved}' should be ISO YYYY-MM-DD.",
                    )
                )
            continue

        if p_type == "number":
            if raw_val is None:
                continue
            try:
                float(raw_val)
            except Exception:
                issues.append(
                    _issue(
                        "invalid_number",
                        mode=mode_n,
                        field=resolved,
                        provided=raw_val,
                        source="wrapper_patch",
                        message=f"Number for '{resolved}' is not parseable.",
                    )
                )
            continue

        if p_type == "checkbox":
            v = raw_val
            if isinstance(v, str):
                sv = v.strip().lower()
                if sv in {"true", "yes", "da", "1", "false", "no", "ne", "0"}:
                    continue
                issues.append(
                    _issue(
                        "invalid_checkbox",
                        mode=mode_n,
                        field=resolved,
                        provided=v,
                        source="wrapper_patch",
                        message=f"Checkbox for '{resolved}' should be true/false.",
                    )
                )
            elif not isinstance(v, bool):
                issues.append(
                    _issue(
                        "invalid_checkbox",
                        mode=mode_n,
                        field=resolved,
                        provided=v,
                        source="wrapper_patch",
                        message=f"Checkbox for '{resolved}' should be boolean.",
                    )
                )
            continue

    errors = sum(1 for it in issues if it.severity == "error")
    warnings = sum(1 for it in issues if it.severity == "warning")

    return {
        "mode": mode_n,
        "db_key": (db_key or "").strip() or None,
        "issues": [it.to_dict() for it in issues],
        "can_approve": errors == 0,
        "summary": {"errors": errors, "warnings": warnings},
    }


def validate_property_specs_against_schema(
    *,
    db_key: str,
    schema: Dict[str, Any],
    property_specs: Optional[Dict[str, Any]],
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    mode_n = _validation_mode(mode)
    issues: List[ValidationIssue] = []

    specs = property_specs if isinstance(property_specs, dict) else {}
    if not specs:
        return {
            "mode": mode_n,
            "db_key": (db_key or "").strip() or None,
            "issues": [],
            "can_approve": True,
            "summary": {"errors": 0, "warnings": 0},
        }

    resolver = SchemaNameResolver(schema)

    for raw_field, spec in specs.items():
        if not isinstance(raw_field, str) or not raw_field.strip():
            continue
        if not isinstance(spec, dict):
            continue

        resolved = resolver.resolve(raw_field)
        if not resolved:
            issues.append(
                _issue(
                    "unknown_field",
                    mode=mode_n,
                    field=raw_field.strip(),
                    provided=spec,
                    source="property_specs",
                    message=f"Unknown field '{raw_field.strip()}' for db_key='{(db_key or '').strip()}'.",
                )
            )
            continue

        st = schema.get(resolved)
        st = st if isinstance(st, dict) else {}
        schema_type = _as_trimmed_str(st.get("type"))

        spec_type = _as_trimmed_str(spec.get("type"))
        if not spec_type:
            continue

        # Only validate option membership when we have options.
        if spec_type in {"select", "status"}:
            val = spec.get("name")
            opts = st.get("options") if isinstance(st.get("options"), list) else []
            issues.extend(
                _validate_select_like(
                    mode=mode_n,
                    field=resolved,
                    provided=val,
                    schema_type=spec_type,
                    schema_options=opts,
                    source="property_specs",
                )
            )
            continue

        if spec_type == "date":
            s = _as_trimmed_str(spec.get("start"))
            if s and not _looks_like_iso_date(s):
                issues.append(
                    _issue(
                        "invalid_date",
                        mode=mode_n,
                        field=resolved,
                        provided=s,
                        source="property_specs",
                        message=f"Date for '{resolved}' should be ISO YYYY-MM-DD.",
                    )
                )
            continue

        if spec_type == "number":
            try:
                float(spec.get("number"))
            except Exception:
                issues.append(
                    _issue(
                        "invalid_number",
                        mode=mode_n,
                        field=resolved,
                        provided=spec.get("number"),
                        source="property_specs",
                        message=f"Number for '{resolved}' is not parseable.",
                    )
                )
            continue

        if spec_type == "checkbox":
            v = spec.get("checkbox")
            if not isinstance(v, bool):
                issues.append(
                    _issue(
                        "invalid_checkbox",
                        mode=mode_n,
                        field=resolved,
                        provided=v,
                        source="property_specs",
                        message=f"Checkbox for '{resolved}' should be boolean.",
                    )
                )
            continue

        # If schema says relation but spec isn't ids, flag.
        if schema_type == "relation" and spec_type == "relation":
            # property_specs relation usually carries IDs; preview often can't.
            continue

    errors = sum(1 for it in issues if it.severity == "error")
    warnings = sum(1 for it in issues if it.severity == "warning")

    return {
        "mode": mode_n,
        "db_key": (db_key or "").strip() or None,
        "issues": [it.to_dict() for it in issues],
        "can_approve": errors == 0,
        "summary": {"errors": errors, "warnings": warnings},
    }


def merge_validation_reports(*reports: Dict[str, Any]) -> Dict[str, Any]:
    mode = "warn"
    db_key = None
    issues: List[Dict[str, Any]] = []
    for r in reports:
        if not isinstance(r, dict):
            continue
        mode = _validation_mode(r.get("mode"))
        if db_key is None:
            dk = r.get("db_key")
            if isinstance(dk, str) and dk.strip():
                db_key = dk.strip()
        its = r.get("issues")
        if isinstance(its, list):
            issues.extend([x for x in its if isinstance(x, dict)])

    errors = sum(1 for it in issues if it.get("severity") == "error")
    warnings = sum(1 for it in issues if it.get("severity") == "warning")
    return {
        "mode": mode,
        "db_key": db_key,
        "issues": issues,
        "can_approve": errors == 0,
        "summary": {"errors": errors, "warnings": warnings},
    }


def validate_notion_payload(
    *,
    db_key: str,
    schema: Dict[str, Any],
    wrapper_patch: Optional[Dict[str, Any]] = None,
    property_specs: Optional[Dict[str, Any]] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience: validates wrapper_patch + property_specs and returns one merged report."""

    r1 = validate_wrapper_patch_against_schema(
        db_key=db_key, schema=schema, wrapper_patch=wrapper_patch, mode=mode
    )
    r2 = validate_property_specs_against_schema(
        db_key=db_key, schema=schema, property_specs=property_specs, mode=mode
    )
    return merge_validation_reports(r1, r2)


def fallback_schema_for_db_key(db_key: str) -> Dict[str, Any]:
    """Best-effort offline schema for validation.

    Prefers the SSOT offline model from NotionSchemaRegistry, which merges:
    - services/notion_schema_snapshot_data.py (generated from *_db.json)
    - services/notion_schema_registry.py base metadata
    """

    k = (db_key or "").strip().lower()
    try:
        from services.notion_schema_registry import NotionSchemaRegistry  # noqa: PLC0415

        # Try common pluralization variants.
        candidates = [k]
        if k.endswith("s"):
            candidates.append(k[:-1])
        else:
            candidates.append(k + "s")

        for cand in candidates:
            sch = NotionSchemaRegistry.offline_validation_schema(cand)
            if isinstance(sch, dict) and sch:
                return sch
    except Exception:
        return {}

    return {}
