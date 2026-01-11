# services/recommendation_classifier.py
# CANONICAL, deterministic, production-safe
# Purpose: classify recommendation semantics for CEO-level decisions

from __future__ import annotations

from typing import Dict, Any, Literal

RecommendationType = Literal[
    "STRATEGIC",
    "OPERATIONAL",
    "DEFENSIVE",
    "EXPERIMENTAL",
    "INFORMATIONAL",
]


def classify_recommendation(
    *,
    prompt: str,
    proposed_command: Dict[str, Any] | None,
    risk_level: str | None,
    behaviour_mode: str | None,
) -> RecommendationType:
    """
    Deterministic, explainable classification.

    INPUTS:
      - prompt: original CEO input (NL)
      - proposed_command: single proposal dict (may be None)
      - risk_level: low / medium / high (string, case-insensitive)
      - behaviour_mode: advisory / executive / red_alert / silent

    OUTPUT:
      - RecommendationType (enum-like Literal)

    IMPORTANT:
      - No ML
      - No guessing
      - Stable rules only
    """

    p = (prompt or "").lower()
    r = (risk_level or "").lower()
    b = (behaviour_mode or "").lower()

    cmd = ""
    intent = ""
    if isinstance(proposed_command, dict):
        cmd = str(proposed_command.get("command") or "").lower()
        intent = str(proposed_command.get("intent") or "").lower()

    # 1️⃣ DEFENSIVE — risk containment / damage control
    if r == "high" or b in {"red_alert"}:
        return "DEFENSIVE"

    # 2️⃣ STRATEGIC — goals, direction, priorities, structure
    if any(
        k in p
        for k in [
            "strategy",
            "strategic",
            "direction",
            "prioritet",
            "priority",
            "goal",
            "cilj",
            "roadmap",
            "plan",
        ]
    ):
        return "STRATEGIC"

    # 3️⃣ OPERATIONAL — concrete execution / changes
    if any(
        k in p
        for k in [
            "create",
            "kreiraj",
            "napravi",
            "update",
            "azuriraj",
            "assign",
            "dodaj",
            "remove",
            "delete",
            "task",
            "zadatak",
        ]
    ):
        return "OPERATIONAL"

    if intent and intent != "ceo.command.propose":
        return "OPERATIONAL"

    # 4️⃣ EXPERIMENTAL — probing / testing / unknown outcomes
    if any(k in p for k in ["try", "test", "experiment", "eksperiment"]):
        return "EXPERIMENTAL"

    # 5️⃣ INFORMATIONAL — default, safe
    return "INFORMATIONAL"
