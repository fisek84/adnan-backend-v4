# services/autonomy/feature_flags.py

from dataclasses import dataclass


@dataclass(frozen=True)
class AutonomyFeatureFlags:
    """
    Production feature flags for autonomy.
    """
    allow_retry: bool = True
    allow_fallback: bool = True
    allow_multi_iteration: bool = False
    allow_self_healing: bool = False

    # ===============================
    # BLOK 9 — CONTROLLED ACTIVATION
    # ===============================
    allow_action_proposals: bool = False
