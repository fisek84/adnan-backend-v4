from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.notion_schema_registry import NotionSchemaRegistry


def _ensure_str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def normalize_value(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return s
    while s.endswith(",") or s.endswith(";"):
        s = s[:-1].rstrip()
    if s.startswith('"') and s.endswith('"') and s.count('"') >= 4:
        pass
    elif s.startswith("'") and s.endswith("'") and s.count("'") >= 4:
        pass
    else:
        s = strip_outer_quotes(s)
    while s.endswith(",") or s.endswith(";"):
        s = s[:-1].rstrip()
    return s


def strip_outer_quotes(value: str) -> str:
    t = (value or "").strip()
    if not t:
        return t

    pairs = [
        ('"', '"'),
        ("'", "'"),
        ("\u201c", "\u201d"),  # “ ”
        ("\u201e", "\u201d"),  # „ ”
        ("\u00ab", "\u00bb"),  # « »
    ]
    for lq, rq in pairs:
        if t.startswith(lq) and t.endswith(rq) and len(t) >= 2:
            return t[1:-1].strip()
    return t


def _as_list_of_str(v: Any) -> List[str]:
    if isinstance(v, list):
        return [normalize_value(_ensure_str(x)) for x in v if _ensure_str(x)]
    s = _ensure_str(v)
    s = normalize_value(s)
    if not s:
        return []
    return [
        normalize_value(x) for x in s.split(",") if isinstance(x, str) and x.strip()
    ]


@dataclass(frozen=True)
class BuildWarning:
    code: str
    field: Optional[str] = None
    resolved_field: Optional[str] = None
    provided: Any = None
    allowed: Optional[List[str]] = None
    source: Optional[str] = None  # wrapper_patch | property_specs
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"code": self.code}
        if self.field:
            out["field"] = self.field
        if self.resolved_field:
            out["resolved_field"] = self.resolved_field
        if self.source:
            out["source"] = self.source
        if self.message:
            out["message"] = self.message
        if self.provided is not None:
            out["provided"] = self.provided
        if self.allowed is not None:
            out["allowed"] = self.allowed
        return out


def _resolve_option(
    *,
    provided: str,
    options: Sequence[str],
) -> Tuple[Optional[str], Optional[BuildWarning]]:
    """Return (canonical_option, warning).

    Matching rules:
    - If provided matches exactly (case-sensitive), accept.
    - Else casefold match; if exactly one match, canonicalize to that option.
    - Else ambiguous/invalid.
    """

    val = normalize_value(provided or "")
    if not val:
        return None, None

    opts = [o for o in options if isinstance(o, str) and o.strip()]
    if not opts:
        # No options known; accept as-is (best effort) but warn.
        return val, BuildWarning(
            code="options_unknown",
            provided=val,
            allowed=None,
            message="No option list available in offline schema snapshot; passing through as-is.",
        )

    if val in opts:
        return val, None

    cf = val.casefold()
    matches = [o for o in opts if o.casefold() == cf]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, BuildWarning(
            code="ambiguous_option",
            provided=val,
            allowed=list(opts),
            message=f"Ambiguous option '{val}' (matches multiple schema options by casefold).",
        )

    return None, BuildWarning(
        code="invalid_option",
        provided=val,
        allowed=list(opts),
        message=f"Invalid option '{val}' for select/status/multi_select.",
    )


def _extract_raw_from_property_spec(spec: Dict[str, Any]) -> Any:
    stype = _ensure_str(spec.get("type")).lower()
    if stype in {"title", "rich_text", "text"}:
        return _ensure_str(spec.get("text") or spec.get("value") or "")
    if stype in {"select", "status"}:
        return _ensure_str(spec.get("name") or spec.get("value") or "")
    if stype == "multi_select":
        raw = spec.get("names")
        if isinstance(raw, list):
            return [_ensure_str(x) for x in raw if _ensure_str(x)]
        return _ensure_str(spec.get("value") or "")
    if stype == "date":
        return _ensure_str(spec.get("start") or spec.get("value") or "")
    if stype == "number":
        return (
            spec.get("number") if spec.get("number") is not None else spec.get("value")
        )
    if stype == "checkbox":
        return (
            spec.get("checkbox")
            if spec.get("checkbox") is not None
            else spec.get("value")
        )
    if stype == "people":
        return (
            spec.get("ids")
            or spec.get("emails")
            or spec.get("names")
            or spec.get("value")
        )
    if stype == "relation":
        return spec.get("ids") or spec.get("id") or spec.get("value")
    return spec


def _normalize_value_for_model(
    *,
    model: NotionSchemaRegistry.PropertyModel,
    raw_value: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[BuildWarning]]:
    """Normalize a raw value into a property_specs entry for this model.

    Returns (spec_or_none, warning_or_none). If spec is None -> drop.
    """

    if model.read_only or not model.write_type:
        return None, BuildWarning(
            code="read_only",
            message=f"Field '{model.name}' is read-only ({model.notion_type}).",
        )

    wt = model.write_type

    if wt == "title":
        s = _ensure_str(raw_value)
        if not s:
            return None, None
        return {"type": "title", "text": s}, None

    if wt == "rich_text":
        s = _ensure_str(raw_value)
        if not s:
            return None, None
        return {"type": "rich_text", "text": s}, None

    if wt in {"select", "status"}:
        s = normalize_value(_ensure_str(raw_value))
        if not s:
            return None, None
        canon, warn = _resolve_option(provided=s, options=model.options or [])
        if canon is None:
            return None, warn
        return {"type": wt, "name": canon}, warn

    if wt == "multi_select":
        names = _as_list_of_str(raw_value)
        if not names:
            return None, None

        allowed = model.options or []
        normed: List[str] = []
        warn_out: Optional[BuildWarning] = None
        for n in names:
            canon, warn = _resolve_option(provided=n, options=allowed)
            if canon is None:
                # Drop invalid individual options deterministically.
                warn_out = warn
                continue
            normed.append(canon)
        if not normed:
            return None, warn_out
        return {"type": "multi_select", "names": normed}, warn_out

    if wt == "date":
        s = normalize_value(_ensure_str(raw_value))
        if not s:
            return None, None
        # Accept ISO YYYY-MM-DD; leave natural language to other layers.
        return {"type": "date", "start": s}, None

    if wt == "number":
        if raw_value is None:
            return None, None
        try:
            return {"type": "number", "number": float(raw_value)}, None
        except Exception:
            return None, BuildWarning(
                code="invalid_number",
                provided=raw_value,
                message=f"Invalid number for '{model.name}'.",
            )

    if wt == "checkbox":
        v = raw_value
        if isinstance(v, str):
            sv = v.strip().lower()
            if sv in {"true", "yes", "da", "1"}:
                v = True
            elif sv in {"false", "no", "ne", "0"}:
                v = False
        if isinstance(v, bool):
            return {"type": "checkbox", "checkbox": v}, None
        return None, BuildWarning(
            code="invalid_checkbox",
            provided=raw_value,
            message=f"Invalid checkbox for '{model.name}'.",
        )

    if wt == "people":
        # Keep names/emails tokens; execution can resolve IDs.
        tokens = _as_list_of_str(raw_value)
        if not tokens:
            return None, None
        # Heuristic: treat '@' as email.
        emails = [t for t in tokens if "@" in t]
        names = [t for t in tokens if "@" not in t]
        spec: Dict[str, Any] = {"type": "people"}
        if emails:
            spec["emails"] = emails
        if names:
            spec["names"] = names
        return spec, None

    if wt == "relation":
        ids = _as_list_of_str(raw_value)
        if not ids:
            return None, None
        return {"type": "relation", "ids": ids}, BuildWarning(
            code="requires_ids",
            provided=raw_value,
            message=f"Relation '{model.name}' requires page IDs; leaving as IDs list.",
        )

    # Unknown write type: drop deterministically.
    return None, BuildWarning(
        code="unsupported_type",
        provided=raw_value,
        message=f"Unsupported write_type '{wt}' for '{model.name}'.",
    )


def validate_and_build_property_specs(
    *,
    db_key: str,
    property_specs_in: Optional[Dict[str, Any]] = None,
    wrapper_patch_in: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build canonical property_specs from (property_specs + wrapper_patch).

    Rules:
    - DB-specific and deterministic using NotionSchemaRegistry offline schema model.
    - Unknown fields never enter property_specs.
    - Read-only fields never enter property_specs.
    - Invalid/ambiguous options never enter property_specs.
    - Dropped fields are retained in wrapper_patch_out.

    Returns a dict:
      {
        property_specs: Dict[str, Any],
        wrapper_patch_out: Dict[str, Any],
        warnings: List[Dict[str, Any]],
        validated: bool
      }
    """

    dk = (db_key or "").strip()
    models = NotionSchemaRegistry.get_property_models(dk)

    schema = NotionSchemaRegistry.offline_validation_schema(dk)
    try:
        from services.notion_patch_validation import SchemaNameResolver  # noqa: PLC0415

        resolver = SchemaNameResolver(schema)
    except Exception:
        resolver = None

    def _resolve(field: str) -> str:
        if resolver is None:
            return ""
        return resolver.resolve(field)

    warnings: List[BuildWarning] = []
    wrapper_patch_out: Dict[str, Any] = {}
    out_specs: Dict[str, Any] = {}

    # 1) Normalize explicit property_specs (structured input)
    ps_in = property_specs_in if isinstance(property_specs_in, dict) else {}
    for raw_field, raw_spec in ps_in.items():
        if not isinstance(raw_field, str) or not raw_field.strip():
            continue
        if not isinstance(raw_spec, dict):
            wrapper_patch_out[raw_field] = raw_spec
            warnings.append(
                BuildWarning(
                    code="invalid_property_spec",
                    field=raw_field.strip(),
                    source="property_specs",
                    provided=raw_spec,
                    message="property_specs entry must be an object.",
                )
            )
            continue

        resolved = raw_field.strip()
        rr = _resolve(resolved)
        if rr:
            resolved = rr

        model = models.get(resolved)
        if model is None:
            wrapper_patch_out[raw_field.strip()] = _extract_raw_from_property_spec(
                raw_spec
            )
            warnings.append(
                BuildWarning(
                    code="unknown_field",
                    field=raw_field.strip(),
                    resolved_field=resolved if resolved != raw_field.strip() else None,
                    source="property_specs",
                    provided=_extract_raw_from_property_spec(raw_spec),
                    message=f"Unknown field '{raw_field.strip()}' for db_key='{dk}'.",
                )
            )
            continue

        raw_val = _extract_raw_from_property_spec(raw_spec)
        spec, warn = _normalize_value_for_model(model=model, raw_value=raw_val)
        if warn is not None:
            warnings.append(
                BuildWarning(
                    **{
                        **warn.__dict__,
                        "field": raw_field.strip(),
                        "resolved_field": model.name
                        if model.name != raw_field.strip()
                        else None,
                        "source": "property_specs",
                    }
                )
            )
        if spec is None:
            wrapper_patch_out[raw_field.strip()] = raw_val
            continue

        out_specs[model.name] = spec

    # 2) Apply wrapper_patch on top (raw user fields)
    wp_in = wrapper_patch_in if isinstance(wrapper_patch_in, dict) else {}
    for raw_field, raw_val in wp_in.items():
        if not isinstance(raw_field, str) or not raw_field.strip():
            continue

        resolved = _resolve(raw_field.strip())
        if not resolved:
            # keep unknown
            wrapper_patch_out[raw_field.strip()] = raw_val
            warnings.append(
                BuildWarning(
                    code="unknown_field",
                    field=raw_field.strip(),
                    source="wrapper_patch",
                    provided=raw_val,
                    message=f"Unknown field '{raw_field.strip()}' for db_key='{dk}'.",
                )
            )
            continue

        model = models.get(resolved)
        if model is None:
            wrapper_patch_out[raw_field.strip()] = raw_val
            warnings.append(
                BuildWarning(
                    code="unknown_field",
                    field=raw_field.strip(),
                    resolved_field=resolved,
                    source="wrapper_patch",
                    provided=raw_val,
                    message=f"Unknown field '{raw_field.strip()}' for db_key='{dk}'.",
                )
            )
            continue

        spec, warn = _normalize_value_for_model(model=model, raw_value=raw_val)
        if warn is not None:
            warnings.append(
                BuildWarning(
                    **{
                        **warn.__dict__,
                        "field": raw_field.strip(),
                        "resolved_field": model.name
                        if model.name != raw_field.strip()
                        else None,
                        "source": "wrapper_patch",
                        "provided": raw_val,
                    }
                )
            )

        if spec is None:
            wrapper_patch_out[raw_field.strip()] = raw_val
            continue

        out_specs[model.name] = spec

    validated = not any(
        w.code in {"unknown_field", "read_only", "invalid_option", "ambiguous_option"}
        for w in warnings
    )

    return {
        "property_specs": out_specs,
        "wrapper_patch_out": wrapper_patch_out,
        "warnings": [w.to_dict() for w in warnings],
        "validated": validated,
    }
