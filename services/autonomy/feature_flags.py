# services/autonomy/feature_flags.py

from dataclasses import dataclass


@dataclass(frozen=True)
class AutonomyFeatureFlags:
    """
    Production feature flags for autonomy.

    FAZA 10.2 — SAFETY DEFAULTS

    PRINCIPLE:
    - Everything OFF by default
    - Explicit enablement only
    """

    # =========================================================
    # MASTER GATE
    # =========================================================
    autonomy_enabled: bool = False

    # =========================================================
    # BEHAVIOR FLAGS
    # =========================================================
    allow_retry: bool = False
    allow_fallback: bool = False
    allow_multi_iteration: bool = False
    allow_self_healing: bool = False

    # =========================================================
    # ACTION EMISSION
    # =========================================================
    allow_action_proposals: bool = False
