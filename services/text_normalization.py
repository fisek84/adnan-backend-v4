from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List


_SMART_QUOTES = {
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u00ab": '"',
    "\u00bb": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
}


def normalize_text(s: str) -> str:
    """Normalize text for deterministic KB retrieval.

    Properties:
    - Lowercase
    - Normalize smart quotes
    - Strip diacritics (NFKD + remove combining marks)
    - Collapse whitespace
    - Strip surrounding quotes/punctuation

    No external deps; safe for offline/test use.
    """

    if s is None:
        return ""

    t = str(s)
    if not t:
        return ""

    # Normalize common curly quotes first.
    for k, v in _SMART_QUOTES.items():
        if k in t:
            t = t.replace(k, v)

    # Unicode normalize + remove diacritics.
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))

    t = t.lower()

    # Collapse whitespace to single spaces.
    t = re.sub(r"\s+", " ", t).strip()

    # Strip surrounding quotes/punctuation.
    t = t.strip("\"'`.,;:!?()[]{}<>")

    return t


def tokenize_normalized(s: str) -> List[str]:
    """Tokenize already-normalized text into ASCII-ish word tokens."""
    t = normalize_text(s)
    if not t:
        return []
    return re.findall(r"[a-z0-9]+", t)


def kb_entry_searchable_text(entry: Dict[str, Any]) -> str:
    """Build a stable searchable text blob for a KB entry."""
    if not isinstance(entry, dict):
        return ""

    parts: List[str] = []

    for k in ("id", "slug", "name", "title"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())

    tags = entry.get("tags")
    if isinstance(tags, list):
        parts.extend([str(x) for x in tags if isinstance(x, str) and x.strip()])
    elif isinstance(tags, str) and tags.strip():
        parts.append(tags.strip())

    for k in ("content", "body", "text", "snippet"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())

    # Allow extra searchable fields (non-breaking; ignore if absent).
    keywords = entry.get("keywords") or entry.get("keyword")
    if isinstance(keywords, list):
        parts.extend([str(x) for x in keywords if isinstance(x, str) and x.strip()])
    elif isinstance(keywords, str) and keywords.strip():
        parts.append(keywords.strip())

    return " \n".join(parts)
