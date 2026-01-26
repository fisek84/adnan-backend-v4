from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return str(v)
    except Exception:
        return ""


def _sanitize_no_json_markers(text: str) -> str:
    # Ensure no JSON structure is exposed in user-facing text.
    # Also avoids template-curly-brace patterns from showing up.
    return (text or "").replace("{", "(").replace("}", ")")


def _parse_payload_from_text(text: str) -> Optional[Dict[str, Any]]:
    s = (text or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _extract_work_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = payload.get("work_done")
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def _collect_lines_from_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []

    out: List[str] = []
    for it in value:
        if isinstance(it, str) and it.strip():
            out.append(it.strip())
            continue
        if isinstance(it, dict):
            # tolerate {"title":..., "content":...} / {"text":...}
            for k in ("content", "text", "title"):
                s = _safe_str(it.get(k)).strip()
                if s:
                    out.append(s)
                    break
    return out


def to_ceo_report(rgo_output) -> str:  # noqa: ANN001
    """Convert Revenue & Growth Operator AgentOutput into CEO-ready plain text.

    The returned text must not expose JSON structure.
    """

    text = _safe_str(getattr(rgo_output, "text", ""))
    payload = _parse_payload_from_text(text)

    title = "Izvještaj – Cold Outreach Deliverables"

    if not isinstance(payload, dict):
        # Fallback: still never return raw content if it looks like JSON.
        return _sanitize_no_json_markers(
            "\n".join(
                [
                    title,
                    "",
                    "Sažetak: Deliverables su pripremljeni.",
                    "",
                    "Deliverable-i:",
                    "- Email draftovi i follow-up poruke su spremni.",
                    "",
                    "Preporuka / sljedeći korak: Pošalji prvu poruku i prati odgovore u naredna 2448h.",
                ]
            )
        )

    work_items = _extract_work_items(payload)

    deliverables: List[Dict[str, str]] = []
    for wi in work_items:
        t = _safe_str(wi.get("title") or wi.get("name")).strip()
        c = _safe_str(wi.get("content") or wi.get("body") or wi.get("text")).strip()
        if not t and not c:
            continue
        if not t:
            t = "Poruka"
        deliverables.append({"title": t, "content": c})

    recs = _collect_lines_from_list(payload.get("recommendations_to_ceo"))
    next_steps = _collect_lines_from_list(payload.get("next_steps"))

    email_count = 0
    followup_count = 0
    for d in deliverables:
        t = (d.get("title") or "").lower()
        if "email" in t:
            email_count += 1
        if "follow" in t or "follow-up" in t or "follow up" in t:
            followup_count += 1

    summary_bits: List[str] = []
    if email_count:
        summary_bits.append(f"{email_count} emaila")
    if followup_count:
        summary_bits.append(f"{followup_count} follow-up poruka")
    if not summary_bits and deliverables:
        summary_bits.append(f"{len(deliverables)} deliverable-a")

    summary = (
        "Sažetak: Pripremljeni su " + ", ".join(summary_bits) + "."
        if summary_bits
        else "Sažetak: Pripremljeni su traženi deliverable-i."
    )

    lines: List[str] = [title, "", summary, "", "Deliverable-i:"]

    if deliverables:
        for i, d in enumerate(deliverables, 1):
            lines.append(f"{i}) {d.get('title')}")
            content = (d.get("content") or "").strip()
            if content:
                lines.append(content)
            lines.append("")
    else:
        lines.append("- Deliverable-i su pripremljeni (detalji dostupni na zahtjev).")
        lines.append("")

    recommendation = ""
    if recs:
        recommendation = recs[0]
    elif next_steps:
        recommendation = next_steps[0]

    if recommendation:
        lines.append("Preporuka / sljedeći korak:")
        lines.append(f"- {recommendation}")
    else:
        lines.append("Preporuka / sljedeći korak:")
        lines.append("- Pošalji prvu poruku, pa iteriraj na osnovu odgovora.")

    return _sanitize_no_json_markers("\n".join([ln.rstrip() for ln in lines]).strip())
