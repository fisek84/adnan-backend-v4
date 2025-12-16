# services/failure_handler.py

"""
FAILURE HANDLER — CANONICAL (FAZA 13 / SCALING)

Uloga:
- JEDINO mjesto za semantičku klasifikaciju failure-a
- deterministički FAILURE ENVELOPE
- UI / UX friendly
- NEMA retry
- NEMA automatike
- NEMA execution-a
- NEMA side-effecta
"""

from typing import Dict, Any, Optional
from datetime import datetime


class FailureHandler:
    # =========================================================
    # FAILURE CATEGORIES (CANONICAL)
    # =========================================================
    CATEGORY_POLICY = "policy_block"
    CATEGORY_SAFETY = "safety_block"
    CATEGORY_GOVERNANCE = "governance_block"
    CATEGORY_EXECUTION = "execution_failure"
    CATEGORY_AGENT = "agent_failure"
    CATEGORY_SYSTEM = "system_error"
    CATEGORY_UNKNOWN = "unknown"

    # =========================================================
    # RECOVERY OPTIONS (DESCRIPTIVE ONLY — NO ACTION)
    # =========================================================
    RECOVERY_OPTIONS = {
        CATEGORY_POLICY: [
            "Promijeniti ulogu ili prava pristupa.",
            "Izmijeniti tip akcije.",
            "Zatražiti administrativno odobrenje.",
        ],
        CATEGORY_SAFETY: [
            "Izmijeniti parametre akcije.",
            "Razbiti operaciju u manje korake.",
            "Kontaktirati administratora.",
        ],
        CATEGORY_GOVERNANCE: [
            "Pregledati approval status.",
            "Zatražiti potrebno odobrenje.",
            "Provjeriti policy ograničenja.",
        ],
        CATEGORY_EXECUTION: [
            "Ponovo pokrenuti akciju ručno.",
            "Provjeriti zavisne servise.",
            "Analizirati execution log.",
        ],
        CATEGORY_AGENT: [
            "Provjeriti dostupnost agenta.",
            "Promijeniti ciljni agent.",
            "Izvršiti akciju ručno.",
        ],
        CATEGORY_SYSTEM: [
            "Provjeriti sistemske resurse.",
            "Restartovati servis (ručno).",
            "Kontaktirati DevOps tim.",
        ],
        CATEGORY_UNKNOWN: [
            "Analizirati detalje greške.",
            "Kontaktirati tehničku podršku.",
        ],
    }

    # =========================================================
    # PUBLIC API
    # =========================================================
    def classify(
        self,
        *,
        source: Optional[str],
        reason: Optional[str],
        execution_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Kreira deterministički FAILURE ENVELOPE.
        """

        category = self._resolve_category(source, reason)

        return {
            "execution_id": execution_id,
            "success": False,
            "execution_state": "FAILED",
            "failure": {
                "category": category,
                "reason": reason or "Unknown failure",
                "source": source or "unknown",
                "recovery_options": list(
                    self.RECOVERY_OPTIONS.get(category, [])
                ),
            },
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": True,
            "metadata": metadata or {},
        }

    # =========================================================
    # INTERNALS (DETERMINISTIC MAPPING)
    # =========================================================
    def _resolve_category(
        self,
        source: Optional[str],
        reason: Optional[str],
    ) -> str:

        if source == "policy":
            return self.CATEGORY_POLICY
        if source == "safety":
            return self.CATEGORY_SAFETY
        if source == "governance":
            return self.CATEGORY_GOVERNANCE
        if source in {"execution", "workflow"}:
            return self.CATEGORY_EXECUTION
        if source == "agent":
            return self.CATEGORY_AGENT
        if source == "system":
            return self.CATEGORY_SYSTEM

        if reason:
            lowered = reason.lower()
            if "approval" in lowered:
                return self.CATEGORY_GOVERNANCE
            if "policy" in lowered:
                return self.CATEGORY_POLICY
            if "safety" in lowered or "blocked" in lowered:
                return self.CATEGORY_SAFETY
            if "agent" in lowered:
                return self.CATEGORY_AGENT
            if "execute" in lowered or "execution" in lowered:
                return self.CATEGORY_EXECUTION

        return self.CATEGORY_UNKNOWN

    # =========================================================
    # SNAPSHOT (UI SAFE)
    # =========================================================
    def overview(self) -> Dict[str, Any]:
        return {
            "categories": dict(self.RECOVERY_OPTIONS),
            "read_only": True,
        }
