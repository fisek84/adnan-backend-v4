from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Literal, Optional


IntentCategory = Literal[
    "CONTROL_TURN",
    "PENDING_PROPOSAL_CONFIRM",
    "PENDING_PROPOSAL_DISMISS",
    "META_ASSISTANT",
    "NORMAL_QUESTION",
    "AMBIGUOUS",
]


ReasonCode = Literal[
    "control.allowlist_hit",
    "pending.confirm.allowlist_hit",
    "pending.dismiss.allowlist_hit",
    "meta.anchor.allowlist_hit",
    "ambiguous.empty_or_whitespace",
    "ambiguous.too_short_no_anchor",
    "normal.default",
    "normal.current_turn_wins_over_pending",
    "meta.current_turn_wins_over_pending",
    "ambiguous.current_turn_wins_over_pending",
]


# Regression-locked threshold (spec: implementation-defined but fixed in tests).
MIN_INTERPRETABLE_LEN_CHARS = 4


@dataclass(frozen=True)
class GateInput:
    current_message: str
    pending_present: bool
    prior_meta_intent: Optional[Literal["assistant_memory", "assistant_identity"]] = (
        None
    )
    prior_meta_intent_age_seconds: Optional[int] = None
    request_flags: Optional[Dict[str, Optional[str]]] = None


@dataclass(frozen=True)
class GateDecision:
    intent_category: IntentCategory
    reason_code: ReasonCode
    allowlist_hit: bool
    ambiguous_flag: bool
    current_turn_wins: bool


def _norm_bhs_ascii(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return ""
    return (
        t.replace("č", "c")
        .replace("ć", "c")
        .replace("š", "s")
        .replace("đ", "dj")
        .replace("ž", "z")
    )


def _bounded_eval_view(text: str) -> str:
    # Gate evaluates only a bounded view for determinism.
    raw = (text or "").strip()
    return raw[:300]


def _tokenize_for_exact_phrase(text: str) -> str:
    # Deterministic normalization for allowlist checks.
    t = _norm_bhs_ascii(text)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = " ".join(t.split())
    return t


_CONTROL_ALLOWLIST = {
    # Notion Ops activation (existing canon keywords).
    "notion ops active",
    "notion ops aktivan",
    "notion ops aktiviraj",
    "notion ops ukljuci",
    "notion ops ukljuce",
    "notion ops ukljuci",  # duplicate-safe
    "notion ops uključi",
    # Notion Ops deactivation (existing canon keywords).
    "stop notion ops",
    "notion ops deaktiviraj",
    "notion ops ugasi",
    "notion ops iskljuci",
    "notion ops iskljuce",
    "notion ops isključi",
    "notion ops deactivate",
}


_PENDING_CONFIRM_ALLOWLIST = {
    # Explicit proposal replay/approve phrases.
    "ponovi prijedlog",
    "ponovi predlog",
    "odobri",
    "odobri prijedlog",
    "odobri predlog",
    "odobravam",
    "neka",
    # Strict short confirmations.
    "da",
    "yes",
    "y",
    "ok",
    "okay",
    "u redu",
    "uredu",
    "slazem se",
    "uradi to",
    "go ahead",
    "proceed",
    "confirm",
}


_PENDING_DISMISS_ALLOWLIST = {
    # Explicit cancellation phrases.
    "otkazi prijedlog",
    "otkazi predlog",
    "otkazi",
    "otkazi to",
    "otkazujem",
    "ne odobravam",
    "ne odobravam prijedlog",
    "ne odobravam predlog",
    # Strict short declines.
    "ne",
    "no",
    "n",
    "nemoj",
    "cancel",
    "dismiss",
    "stop",
}


_META_ANCHOR_PATTERNS = [
    # Memory anchors (BHS + EN)
    r"\bmemorij\w*\b",
    r"\bpamcenj\w*\b",
    r"\bmemory\b",
    r"\bsnapshot\b",
    # Identity anchors
    r"\bko\s+si\s+ti\b",
    r"\bwho\s+are\s+you\b",
    # Governance/system anchors
    r"\bgovernance\b",
    r"\bsistem\w*\b",
    r"\bsystem\b",
    # Explicit how-it-works anchors (must reference assistant/system)
    r"\bhow\s+do\s+you\s+work\b",
    r"\bkako\s+radis\b",
]


def _has_meta_anchor(text: str) -> bool:
    t = _tokenize_for_exact_phrase(text)
    if not t:
        return False
    for pat in _META_ANCHOR_PATTERNS:
        if re.search(pat, t, flags=re.IGNORECASE):
            return True
    return False


def evaluate_turn_gate(gate_input: GateInput) -> GateDecision:
    """Deterministic Turn Interpretation Authority Gate.

    Contract:
      - No I/O, no LLM, no state mutation.
      - Uses only GateInput signals.
      - Returns a stable GateDecision with exact reason_code strings.
    """

    pending_present = bool(gate_input.pending_present is True)

    raw_view = _bounded_eval_view(gate_input.current_message)
    trimmed = (raw_view or "").strip()

    # 1) CONTROL_TURN — strict allowlist.
    t_phrase = _tokenize_for_exact_phrase(trimmed)
    if t_phrase and t_phrase in {
        _tokenize_for_exact_phrase(x) for x in _CONTROL_ALLOWLIST
    }:
        return GateDecision(
            intent_category="CONTROL_TURN",
            reason_code="control.allowlist_hit",
            allowlist_hit=True,
            ambiguous_flag=False,
            current_turn_wins=False,
        )

    # 2) Pending confirm/dismiss — strict allowlist only, and ONLY if pending exists.
    if pending_present:
        # Defensive: do not treat normal questions like "da li ..." as confirmations/declines.
        if t_phrase.startswith("da li ") or t_phrase.startswith("da l "):
            pass
        else:
            if t_phrase and t_phrase in _PENDING_CONFIRM_ALLOWLIST:
                return GateDecision(
                    intent_category="PENDING_PROPOSAL_CONFIRM",
                    reason_code="pending.confirm.allowlist_hit",
                    allowlist_hit=True,
                    ambiguous_flag=False,
                    current_turn_wins=False,
                )

            if t_phrase and t_phrase in _PENDING_DISMISS_ALLOWLIST:
                return GateDecision(
                    intent_category="PENDING_PROPOSAL_DISMISS",
                    reason_code="pending.dismiss.allowlist_hit",
                    allowlist_hit=True,
                    ambiguous_flag=False,
                    current_turn_wins=False,
                )

    # 3) META_ASSISTANT — only with explicit meta anchor.
    if _has_meta_anchor(trimmed):
        if pending_present:
            return GateDecision(
                intent_category="META_ASSISTANT",
                reason_code="meta.current_turn_wins_over_pending",
                allowlist_hit=True,
                ambiguous_flag=False,
                current_turn_wins=True,
            )
        return GateDecision(
            intent_category="META_ASSISTANT",
            reason_code="meta.anchor.allowlist_hit",
            allowlist_hit=True,
            ambiguous_flag=False,
            current_turn_wins=False,
        )

    # 4) AMBIGUOUS — empty/whitespace or too-short without anchor.
    if not trimmed:
        if pending_present:
            return GateDecision(
                intent_category="AMBIGUOUS",
                reason_code="ambiguous.current_turn_wins_over_pending",
                allowlist_hit=False,
                ambiguous_flag=True,
                current_turn_wins=True,
            )
        return GateDecision(
            intent_category="AMBIGUOUS",
            reason_code="ambiguous.empty_or_whitespace",
            allowlist_hit=False,
            ambiguous_flag=True,
            current_turn_wins=False,
        )

    if len(trimmed) < MIN_INTERPRETABLE_LEN_CHARS:
        if pending_present:
            return GateDecision(
                intent_category="AMBIGUOUS",
                reason_code="ambiguous.current_turn_wins_over_pending",
                allowlist_hit=False,
                ambiguous_flag=True,
                current_turn_wins=True,
            )
        return GateDecision(
            intent_category="AMBIGUOUS",
            reason_code="ambiguous.too_short_no_anchor",
            allowlist_hit=False,
            ambiguous_flag=True,
            current_turn_wins=False,
        )

    # 5) NORMAL_QUESTION — default.
    if pending_present:
        return GateDecision(
            intent_category="NORMAL_QUESTION",
            reason_code="normal.current_turn_wins_over_pending",
            allowlist_hit=False,
            ambiguous_flag=False,
            current_turn_wins=True,
        )

    return GateDecision(
        intent_category="NORMAL_QUESTION",
        reason_code="normal.default",
        allowlist_hit=False,
        ambiguous_flag=False,
        current_turn_wins=False,
    )
