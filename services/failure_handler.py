# services/failure_handler.py

"""
FAILURE HANDLER — FAZA 15 (READ-ONLY)

Uloga:
- standardizuje failure modove sistema
- klasificira greške (policy, safety, execution, agent, system)
- definiše dozvoljene recovery opcije (DESCRIPTIVE, ne izvršne)
- surfacuje jasan signal CEO / UI sloju
- NEMA retry
- NEMA automatskog oporavka
- NEMA izvršenja
"""

from typing import Dict, Any, Optional
from datetime import datetime


class FailureHandler:
    # ------------------------------------------------------------
    # FAILURE CATEGORIES
    # ------------------------------------------------------------
    CATEGORY_POLICY = "policy_block"
    CATEGORY_SAFETY = "safety_block"
    CATEGORY_EXECUTION = "execution_failure"
    CATEGORY_AGENT = "agent_failure"
    CATEGORY_SYSTEM = "system_error"
    CATEGORY_UNKNOWN = "unknown"

    # ------------------------------------------------------------
    # RECOVERY OPTIONS (DESCRIPTIVE ONLY)
    # ------------------------------------------------------------
    RECOVERY_OPTIONS = {
        CATEGORY_POLICY: [
            "Promijeniti ulogu ili prava pristupa.",
            "Izmijeniti tip akcije.",
            "Zatražiti administrativno odobrenje.",
        ],
        CATEGORY_SAFETY: [
            "Izmijeniti parametre akcije.",
            "Razbiti workflow u manje korake.",
            "Kontaktirati administratora.",
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

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------
    def classify_failure(
        self,
        *,
        source: Optional[str] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ulaz:
        - source: gdje je greška nastala (policy | safety | workflow | agent | system)
        - error: tekstualni opis greške
        - metadata: dodatni kontekst

        Izlaz:
        - standardizovan failure payload
        """

        category = self._resolve_category(source, error)

        return {
            "failed": True,
            "category": category,
            "error": error or "Unknown error",
            "source": source or "unknown",
            "recovery_options": self.RECOVERY_OPTIONS.get(category, []),
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": True,
            "metadata": metadata or {},
        }

    # ------------------------------------------------------------
    # INTERNALS
    # ------------------------------------------------------------
    def _resolve_category(
        self,
        source: Optional[str],
        error: Optional[str],
    ) -> str:

        if source in {"policy"}:
            return self.CATEGORY_POLICY

        if source in {"safety"}:
            return self.CATEGORY_SAFETY

        if source in {"execution", "workflow"}:
            return self.CATEGORY_EXECUTION

        if source in {"agent"}:
            return self.CATEGORY_AGENT

        if source in {"system"}:
            return self.CATEGORY_SYSTEM

        if error:
            err = error.lower()
            if "policy" in err:
                return self.CATEGORY_POLICY
            if "safety" in err or "blocked" in err:
                return self.CATEGORY_SAFETY
            if "agent" in err:
                return self.CATEGORY_AGENT
            if "execute" in err or "execution" in err:
                return self.CATEGORY_EXECUTION

        return self.CATEGORY_UNKNOWN

    # ------------------------------------------------------------
    # SNAPSHOT (UI FRIENDLY)
    # ------------------------------------------------------------
    def get_failure_overview(self) -> Dict[str, Any]:
        """
        Statički pregled failure kategorija i recovery opcija.
        """
        return {
            "categories": {
                self.CATEGORY_POLICY: self.RECOVERY_OPTIONS[self.CATEGORY_POLICY],
                self.CATEGORY_SAFETY: self.RECOVERY_OPTIONS[self.CATEGORY_SAFETY],
                self.CATEGORY_EXECUTION: self.RECOVERY_OPTIONS[self.CATEGORY_EXECUTION],
                self.CATEGORY_AGENT: self.RECOVERY_OPTIONS[self.CATEGORY_AGENT],
                self.CATEGORY_SYSTEM: self.RECOVERY_OPTIONS[self.CATEGORY_SYSTEM],
                self.CATEGORY_UNKNOWN: self.RECOVERY_OPTIONS[self.CATEGORY_UNKNOWN],
            },
            "read_only": True,
        }
