from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple


_KV_PAIR_RE = re.compile(
    r"(?i)(?:^|[,;]|\s{2,})\s*[A-Za-z][A-Za-z0-9 _&/\-]{0,60}\s*[:\-–—]\s*\S+"
)


def extract_prompt_kv_patch(prompt_text: str) -> Dict[str, Any]:
    """Best-effort extraction of arbitrary Notion fields from a prompt.

    Contract:
      - Extracts only explicit `Key: Value` segments.
      - Special-cases Description/Opis to capture the full tail.
      - Ignores any appended JSON after a `{`.

    Returns a dict of raw (string) values. No schema mapping is done here.
    """

    if not isinstance(prompt_text, str) or not prompt_text.strip():
        return {}

    s = prompt_text.strip()

    # Drop any appended JSON blob (often pasted for debugging)
    if "{" in s:
        s = s.split("{", 1)[0].strip()

    s = s.replace("\r\n", "\n").replace("\r", "\n")

    out: Dict[str, Any] = {}

    # Capture Description/Opis as the full tail (can contain commas)
    m_desc = re.search(r"(?is)\b(description|opis)\s*[:\-–—]\s*(.+)$", s)
    if m_desc:
        out["Description"] = (m_desc.group(2) or "").strip().strip(",;")
        s = s[: m_desc.start()].strip()

    # Normalize remaining text for splitting
    s2 = re.sub(r"[\n\t]+", ", ", s)
    s2 = re.sub(r"\s*,\s*", ", ", s2)
    s2 = re.sub(r"\s+", " ", s2).strip()

    for seg in re.split(r"\s*[,;]\s*", s2):
        if not seg:
            continue
        m = re.match(
            r"^\s*([A-Za-z][A-Za-z0-9 _&/\-]{0,60})\s*[:\-–—]\s*(.+?)\s*$",
            seg,
        )
        if not m:
            continue
        key = (m.group(1) or "").strip()
        val = (m.group(2) or "").strip()
        if not key or not val:
            continue

        # Avoid accidentally treating the leading command phrase as a field.
        if re.search(
            r"(?i)\b(kreiraj|napravi|create)\s+(cilj|goal|task|zadatak|project|projekat|projekt)\b",
            key,
        ):
            continue

        out[key] = val

    return out


def normalize_prompt_for_property_parse(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    t = re.sub(r"[\r\n]+", ", ", t)
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def strip_prefixes_for_title(text: str) -> str:
    """Derive a clean title from a prompt by stripping command prefixes
    and cutting off at the first `Key: Value` pair.
    """

    t = (text or "").strip()
    if not t:
        return t

    t2 = re.sub(r"^(task|zadatak)\s*[:\-–—]\s*", "", t, flags=re.IGNORECASE).strip()
    t2 = re.sub(
        r"^(kreiraj|napravi|create)\s+(task|zadatak|project|projekat|projekt|goal|cilj)\w*\s*(?:u\s+notionu)?\s*[:\-–—,;]?\s*",
        "",
        t2,
        flags=re.IGNORECASE,
    ).strip()

    # Prefer known fields, but also support any explicit KV pair.
    prop_pat = re.compile(
        r"(?i)(?:^|[,;]|\s{2,})\s*(status|priority|deadline|due\s+date|description)\b\s*(?:[:\-–—]|\s+)"
    )
    m1 = prop_pat.search(t2)
    start1 = m1.start() if (m1 and m1.start() > 0) else None

    m2 = _KV_PAIR_RE.search(t2)
    start2 = m2.start() if (m2 and m2.start() > 0) else None

    cut_at: Optional[int] = None
    if start1 is not None and start2 is not None:
        cut_at = min(start1, start2)
    elif start1 is not None:
        cut_at = start1
    elif start2 is not None:
        cut_at = start2

    if cut_at is not None:
        cut = t2[:cut_at].strip().rstrip(",;:-–—")
        return cut or t2

    return t2 or t


def merge_prompt_patch_with_wrapper_patch(
    *, prompt: str, wrapper_patch: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Merge prompt-derived patch with explicit wrapper_patch (UI wins)."""

    pp = extract_prompt_kv_patch(prompt)
    out: Dict[str, Any] = {}
    if isinstance(pp, dict) and pp:
        out.update(pp)
    if isinstance(wrapper_patch, dict) and wrapper_patch:
        out.update(wrapper_patch)
    return out


def normalize_wrapper_prompt_and_patch(
    *, prompt: str, wrapper_patch: Optional[Dict[str, Any]]
) -> Tuple[str, Dict[str, Any]]:
    """Return (clean_title, merged_patch) for the wrapper prompt."""

    p = (prompt or "").strip()
    merged = merge_prompt_patch_with_wrapper_patch(
        prompt=p, wrapper_patch=wrapper_patch
    )
    title = strip_prefixes_for_title(normalize_prompt_for_property_parse(p))
    return title, merged


def looks_like_title_contains_kv(name_text: str) -> bool:
    if not isinstance(name_text, str) or not name_text.strip():
        return False
    return _KV_PAIR_RE.search(name_text) is not None


def coerce_create_page_name_from_prompt(
    *, prompt: str, property_specs: Dict[str, Any]
) -> Dict[str, Any]:
    """If property_specs.Name looks polluted with KV pairs, rewrite it from prompt."""

    if not isinstance(property_specs, dict):
        return property_specs

    name_spec = property_specs.get("Name")
    if not isinstance(name_spec, dict):
        return property_specs

    name_text = name_spec.get("text")
    if not looks_like_title_contains_kv(
        str(name_text) if name_text is not None else ""
    ):
        return property_specs

    clean_title = strip_prefixes_for_title(normalize_prompt_for_property_parse(prompt))
    if not isinstance(clean_title, str) or not clean_title.strip():
        return property_specs

    ps = dict(property_specs)
    ns = dict(name_spec)
    ns["text"] = clean_title.strip()
    ps["Name"] = ns
    return ps
