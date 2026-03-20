from __future__ import annotations

import re
from urllib.parse import urlsplit
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class SpokenTextResult:
    spoken_text: str
    full_text_chars: int
    spoken_text_chars: int
    changed: bool
    shortened: bool
    normalized: bool
    strategy: str  # passthrough | normalized | normalized_shortened


_BHS_LANGS = {"bs", "hr", "sr"}


def _lang_group(lang: Optional[str]) -> str:
    l0 = (lang or "").strip().lower()
    base = l0.split("-", 1)[0].split("_", 1)[0]
    if base in _BHS_LANGS:
        return "bhs"
    if base in {"en", "de"}:
        return base
    return "bhs"


def _tokens_for_lang(lang_group: str) -> Dict[str, str]:
    if lang_group == "en":
        return {
            "link": "link",
            "email": "email",
            "dot": "dot",
            "slash": "slash",
            "dash": "dash",
            "colon": "colon",
            "at": "at",
            "plus": "plus",
            "percent": "percent",
            "hash": "hash",
            "underscore": "underscore",
            "equals": "equals",
            "and": "and",
            "question": "question mark",
            "code_omitted": "code omitted",
            "details_on_screen": "Details are on screen.",
        }
    if lang_group == "de":
        return {
            "link": "Link",
            "email": "E-Mail",
            "dot": "Punkt",
            "slash": "Schrägstrich",
            "dash": "Bindestrich",
            "colon": "Doppelpunkt",
            "at": "ät",
            "plus": "Plus",
            "percent": "Prozent",
            "hash": "Raute",
            "underscore": "Unterstrich",
            "equals": "gleich",
            "and": "und",
            "question": "Fragezeichen",
            "code_omitted": "Code ausgelassen",
            "details_on_screen": "Details stehen im Text.",
        }

    # bhs
    return {
        "link": "link",
        "email": "email",
        "dot": "tačka",
        "slash": "kosa crta",
        "dash": "crta",
        "colon": "dvotačka",
        "at": "et",
        "plus": "plus",
        "percent": "posto",
        "hash": "taraba",
        "underscore": "donja crta",
        "equals": "jednako",
        "and": "i",
        "question": "upitnik",
        "code_omitted": "kod izostavljen",
        "details_on_screen": "Detalji su u tekstu.",
    }


_URL_RE = re.compile(r"\bhttps?://[^\s]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")

_STRUCTURED_TOKEN_RE = re.compile(r"\b[0-9A-Za-z]+(?:[\/#@:%+_=\-][0-9A-Za-z]+)+\b")

_DECIMAL_RE = re.compile(r"\b(\d{1,6})([\.,])(\d{1,2})\b")


def _strip_markdown(text: str, *, tokens: Dict[str, str]) -> tuple[str, bool]:
    t = text or ""
    changed = False

    # Code fences: replace with short placeholder.
    def _repl_code(_m: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f" ({tokens['code_omitted']}) "

    t2 = re.sub(r"```[\s\S]*?```", _repl_code, t)
    t = t2

    # Inline code: remove backticks.
    if "`" in t:
        t2 = re.sub(r"`([^`]+)`", r"\1", t)
        if t2 != t:
            changed = True
            t = t2

    # Markdown links: [label](url) -> label (keep label only)
    t2 = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", t)
    if t2 != t:
        changed = True
        t = t2

    return t, changed


def _verbalize_structured(s: str, *, tokens: Dict[str, str]) -> str:
    # Make structured strings speakable by inserting spaces and verbal tokens.
    # Keep it deterministic and conservative.
    rep = {
        ".": f" {tokens['dot']} ",
        "/": f" {tokens['slash']} ",
        "-": f" {tokens['dash']} ",
        ":": f" {tokens['colon']} ",
        "@": f" {tokens['at']} ",
        "+": f" {tokens['plus']} ",
        "%": f" {tokens['percent']} ",
        "#": f" {tokens['hash']} ",
        "_": f" {tokens['underscore']} ",
        "=": f" {tokens['equals']} ",
        "&": f" {tokens['and']} ",
        "?": f" {tokens['question']} ",
    }

    out = []
    for ch in s:
        out.append(rep.get(ch, ch))

    # Collapse whitespace.
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _simplify_url_for_speech(
    url: str, *, tokens: Dict[str, str], max_chars: int
) -> Optional[str]:
    """Return a shorter speakable form for long URLs, or None to keep full URL.

    This is intentionally conservative: we only shorten when the URL is long
    enough that spelling it out degrades UX.
    """

    u = (url or "").strip()
    if not u:
        return None

    # Heuristic: for small caps, be more aggressive.
    if len(u) < 60 and max_chars >= 200:
        return None

    try:
        parts = urlsplit(u)
        host = (parts.netloc or "").strip()
        if not host:
            return None

        # Strip credentials/ports if present.
        if "@" in host:
            host = host.split("@", 1)[-1]
        if ":" in host:
            host = host.split(":", 1)[0]

        if host.lower().startswith("www."):
            host = host[4:]

        if not host:
            return None

        spoken_host = _verbalize_structured(host, tokens=tokens)
        return f"{tokens['link']} {spoken_host}".strip()
    except Exception:
        return None


def _simplify_email_for_speech(email: str, *, tokens: Dict[str, str]) -> Optional[str]:
    e = (email or "").strip()
    if not e:
        return None

    # Keep normal emails readable; shorten only when very long.
    if len(e) <= 40:
        return None

    try:
        if "@" not in e:
            return None
        domain = e.split("@", 1)[-1].strip()
        if not domain:
            return None
        spoken_domain = _verbalize_structured(domain, tokens=tokens)
        return f"{tokens['email']} {spoken_domain}".strip()
    except Exception:
        return None


def _normalize_decimals(text: str, *, lang_group: str) -> tuple[str, bool]:
    """Normalize simple decimals in a safe way.

    Only matches decimals with 1-2 fractional digits (e.g. 12.5, 3,25).
    Avoids thousands separators like 1,234 or 1.234.
    """

    t = text or ""
    changed = False

    if lang_group == "en":
        sep = "point"
    elif lang_group == "de":
        sep = "Komma"
    else:
        sep = "zarez"

    def _repl(m: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f"{m.group(1)} {sep} {m.group(3)}"

    t2 = _DECIMAL_RE.sub(_repl, t)
    return t2, t2 != t or changed


def _normalize_dates_times(text: str, *, lang_group: str) -> tuple[str, bool]:
    t = text or ""
    changed = False

    # Times: 17:30
    def _repl_time(m: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        hh = m.group(1)
        mm = m.group(2)
        if lang_group == "de":
            return f"{hh} Uhr {mm}"
        if lang_group == "bhs":
            return f"{hh} i {mm}"
        return f"{hh} {mm}"

    t2 = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", _repl_time, t)
    t = t2

    # ISO date: 2026-03-20 -> 20.03.2026 (better for bhs/de) / keep order for en.
    def _repl_iso_date(m: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        if lang_group == "en":
            return f"{yyyy} {mm} {dd}"
        return f"{dd}.{mm}.{yyyy}"

    t2 = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", _repl_iso_date, t)
    t = t2

    # Dots in date: 20.03.2026 -> space after dots for nicer pacing.
    t2 = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", r"\1. \2. \3", t)
    if t2 != t:
        changed = True
        t = t2

    return t, changed


def _normalize_percent_and_currency(text: str, *, lang_group: str) -> tuple[str, bool]:
    t = text or ""
    changed = False

    percent_word = (
        "percent"
        if lang_group == "en"
        else "Prozent"
        if lang_group == "de"
        else "posto"
    )

    t2 = re.sub(
        r"(\d+(?:[\.,]\d{1,2})?)\s*%(?=\s|$)",
        rf"\1 {percent_word}",
        t,
    )
    if t2 != t:
        changed = True
        t = t2

    # Currency symbols (minimal and neutral forms).
    if lang_group == "en":
        repl = {
            "€": " euros ",
            "$": " dollars ",
            "KM": " marks ",
            "EUR": " euros ",
            "USD": " dollars ",
        }
    elif lang_group == "de":
        repl = {
            "€": " Euro ",
            "$": " Dollar ",
            "KM": " Mark ",
            "EUR": " Euro ",
            "USD": " Dollar ",
        }
    else:
        repl = {
            "€": " euro ",
            "$": " dolar ",
            "KM": " marka ",
            "EUR": " euro ",
            "USD": " dolar ",
        }

    for k, v in repl.items():
        if k in t:
            t = t.replace(k, v)
            changed = True

    # Normalize whitespace after replacements.
    if changed:
        t = re.sub(r"\s+", " ", t).strip()

    return t, changed


def _normalize_newlines_for_pacing(text: str) -> tuple[str, bool]:
    t = text or ""
    if "\n" not in t:
        return t, False

    # Convert newlines to sentence pauses.
    t2 = re.sub(r"\n+", ". ", t)
    t2 = re.sub(r"\s+", " ", t2).strip()
    return t2, t2 != t


def _ensure_final_punctuation(text: str) -> tuple[str, bool]:
    t = (text or "").strip()
    if not t:
        return t, False
    if t[-1] in {".", "!", "?"}:
        return t, False
    return t + ".", True


def build_spoken_text(
    *,
    text: str,
    output_lang: Optional[str],
    max_chars: int,
) -> SpokenTextResult:
    full = str(text or "")
    full_n = len(full)
    lang_group = _lang_group(output_lang)
    tokens = _tokens_for_lang(lang_group)

    spoken = full.strip()
    normalized = False

    try:
        spoken, md_changed = _strip_markdown(spoken, tokens=tokens)
        normalized = normalized or md_changed

        # Structured strings (URL/email) verbalization.
        def _repl_url(m: re.Match[str]) -> str:
            raw = m.group(0)
            short = _simplify_url_for_speech(raw, tokens=tokens, max_chars=max_chars)
            return (
                short
                if isinstance(short, str) and short.strip()
                else _verbalize_structured(raw, tokens=tokens)
            )

        def _repl_email(m: re.Match[str]) -> str:
            raw = m.group(0)
            short = _simplify_email_for_speech(raw, tokens=tokens)
            return (
                short
                if isinstance(short, str) and short.strip()
                else _verbalize_structured(raw, tokens=tokens)
            )

        t2 = _URL_RE.sub(_repl_url, spoken)
        if t2 != spoken:
            normalized = True
            spoken = t2

        t2 = _EMAIL_RE.sub(_repl_email, spoken)
        if t2 != spoken:
            normalized = True
            spoken = t2

        # Speakable structured tokens outside URLs/emails (ticket ids, short paths, etc.).
        def _repl_structured(m: re.Match[str]) -> str:
            raw = m.group(0)
            if "://" in raw:
                return raw
            # Avoid turning regular hyphenated words into "dash" speech.
            has_digit = any(ch.isdigit() for ch in raw)
            has_nondash_symbol = any(ch in "/#@:%+_=" for ch in raw)
            if not (has_digit or has_nondash_symbol):
                return raw
            return _verbalize_structured(raw, tokens=tokens)

        t2 = _STRUCTURED_TOKEN_RE.sub(_repl_structured, spoken)
        if t2 != spoken:
            normalized = True
            spoken = t2

        t2, ch1 = _normalize_dates_times(spoken, lang_group=lang_group)
        if ch1:
            normalized = True
            spoken = t2

        t2, ch2 = _normalize_percent_and_currency(spoken, lang_group=lang_group)
        if ch2:
            normalized = True
            spoken = t2

        t2, ch2b = _normalize_decimals(spoken, lang_group=lang_group)
        if ch2b:
            normalized = True
            spoken = t2

        t2, ch3 = _normalize_newlines_for_pacing(spoken)
        if ch3:
            normalized = True
            spoken = t2

        # Basic bullet/list cleanup.
        t2 = re.sub(r"\s*\b[-*]\s+", " ", spoken)
        if t2 != spoken:
            normalized = True
            spoken = re.sub(r"\s+", " ", t2).strip()

    except Exception:
        # Fail-safe: do not block voice; fall back to raw text.
        spoken = full.strip()
        normalized = False

    shortened = False
    if max_chars and len(spoken) > max_chars:
        shortened = True

        # Prefer sentence boundary; else cut at whitespace.
        cut = max_chars
        boundary = max(
            spoken.rfind(".", 0, max_chars),
            spoken.rfind("!", 0, max_chars),
            spoken.rfind("?", 0, max_chars),
        )
        if boundary >= int(max_chars * 0.6):
            cut = boundary + 1
        else:
            ws = spoken.rfind(" ", 0, max_chars)
            if ws >= int(max_chars * 0.6):
                cut = ws

        spoken = (spoken[:cut].strip() + " " + tokens["details_on_screen"]).strip()

    spoken, punct_changed = _ensure_final_punctuation(spoken)
    normalized = normalized or punct_changed

    spoken_n = len(spoken)
    changed = spoken.strip() != full.strip()

    if shortened:
        strategy = "normalized_shortened" if normalized else "shortened"
    else:
        strategy = "normalized" if normalized else "passthrough"

    return SpokenTextResult(
        spoken_text=spoken,
        full_text_chars=full_n,
        spoken_text_chars=spoken_n,
        changed=changed,
        shortened=shortened,
        normalized=normalized,
        strategy=strategy,
    )
