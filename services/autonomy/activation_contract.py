# services/autonomy/activation_contract.py

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class AutonomyProposal:
    """
    Data-only advisory package emitted by autonomy.

    RULES:
    - No execution semantics
    - No CSI mutation
    - No confidence scoring
    - Decision Engine is the sole authority
    """

    proposal_type: str
    rationale: str
    signals: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None
