from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Callable, Optional


class DateParseKind(str, Enum):
    EMPTY = "empty"
    ABSOLUTE = "absolute"
    RELATIVE = "relative"
    INVALID = "invalid"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class DateParsingPolicy:
    """Enterprise-grade date parsing policy.

    Defaults are conservative (no guessing).
    """

    allow_us_dotted: bool = False
    allow_ambiguous_dotted_guess: bool = False
    ambiguous_dotted_assumption: str = "dmy"  # "dmy" or "mdy" when guessing is enabled


@dataclass(frozen=True)
class ParseResult:
    iso: Optional[str]
    issues: list[str] = field(default_factory=list)
    normalized_input: str = ""
    kind: DateParseKind = DateParseKind.INVALID


def parse_date(
    value: str,
    *,
    policy: DateParsingPolicy,
    now_provider: Callable[[], date],
) -> ParseResult:
    raw = value if isinstance(value, str) else ""
    v = raw.strip()
    if not v:
        return ParseResult(iso=None, issues=[], normalized_input="", kind=DateParseKind.EMPTY)

    normalized_input = v
    lv = v.lower()

    if lv in {"danas", "today"}:
        d = now_provider()
        return ParseResult(
            iso=d.isoformat(),
            issues=[],
            normalized_input=normalized_input,
            kind=DateParseKind.RELATIVE,
        )
    if lv in {"sutra", "tomorrow"}:
        d = now_provider() + timedelta(days=1)
        return ParseResult(
            iso=d.isoformat(),
            issues=[],
            normalized_input=normalized_input,
            kind=DateParseKind.RELATIVE,
        )
    if lv in {"prekosutra"}:
        d = now_provider() + timedelta(days=2)
        return ParseResult(
            iso=d.isoformat(),
            issues=[],
            normalized_input=normalized_input,
            kind=DateParseKind.RELATIVE,
        )

    # ISO-ish: YYYY-MM-DD or YYYY/MM/DD
    import re

    m = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})$", v)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return ParseResult(
                iso=date(y, mo, d).isoformat(),
                issues=[],
                normalized_input=normalized_input,
                kind=DateParseKind.ABSOLUTE,
            )
        except ValueError:
            return ParseResult(
                iso=None,
                issues=["invalid_calendar_date"],
                normalized_input=normalized_input,
                kind=DateParseKind.INVALID,
            )

    # Dotted: DD.MM.YYYY or MM.DD.YYYY
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})\.?$", v)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))

        # Clearly EU: day>12 and month<=12
        if a > 12 and b <= 12:
            try:
                return ParseResult(
                    iso=date(y, b, a).isoformat(),
                    issues=[],
                    normalized_input=normalized_input,
                    kind=DateParseKind.ABSOLUTE,
                )
            except ValueError:
                return ParseResult(
                    iso=None,
                    issues=["invalid_calendar_date"],
                    normalized_input=normalized_input,
                    kind=DateParseKind.INVALID,
                )

        # Clearly US: month<=12 and day>12
        if b > 12 and a <= 12:
            if not policy.allow_us_dotted:
                return ParseResult(
                    iso=None,
                    issues=["us_dotted_not_allowed"],
                    normalized_input=normalized_input,
                    kind=DateParseKind.INVALID,
                )
            try:
                return ParseResult(
                    iso=date(y, a, b).isoformat(),
                    issues=[],
                    normalized_input=normalized_input,
                    kind=DateParseKind.ABSOLUTE,
                )
            except ValueError:
                return ParseResult(
                    iso=None,
                    issues=["invalid_calendar_date"],
                    normalized_input=normalized_input,
                    kind=DateParseKind.INVALID,
                )

        # Invalid dotted where both parts are > 12
        if a > 12 and b > 12:
            return ParseResult(
                iso=None,
                issues=["invalid_calendar_date"],
                normalized_input=normalized_input,
                kind=DateParseKind.INVALID,
            )

        # Ambiguous: both <= 12
        if a <= 12 and b <= 12:
            if not policy.allow_ambiguous_dotted_guess:
                return ParseResult(
                    iso=None,
                    issues=["ambiguous_dotted_date"],
                    normalized_input=normalized_input,
                    kind=DateParseKind.AMBIGUOUS,
                )

            assumption = (policy.ambiguous_dotted_assumption or "dmy").strip().lower()
            if assumption not in {"dmy", "mdy"}:
                assumption = "dmy"

            # Keep an issue marker even when guessing is enabled.
            issues = ["ambiguous_dotted_date"]
            try:
                if assumption == "mdy":
                    iso = date(y, a, b).isoformat()
                else:
                    iso = date(y, b, a).isoformat()
                return ParseResult(
                    iso=iso,
                    issues=issues,
                    normalized_input=normalized_input,
                    kind=DateParseKind.ABSOLUTE,
                )
            except ValueError:
                return ParseResult(
                    iso=None,
                    issues=issues + ["invalid_calendar_date"],
                    normalized_input=normalized_input,
                    kind=DateParseKind.INVALID,
                )

    return ParseResult(
        iso=None,
        issues=["unsupported_format"],
        normalized_input=normalized_input,
        kind=DateParseKind.INVALID,
    )
