from typing import Any, Dict, Optional
from datetime import datetime
import copy


class AwarenessService:
    """
    Awareness Service — V1.1 AWARENESS CONTRACT

    PURPOSE:
    - Bridge between Decision Engine (brain) and Response Formatter (voice)
    - Provide situational awareness and human-readable context
    - STRICTLY READ-ONLY
    - NO decisions
    - NO execution
    - NO state mutation
    """

    CONTRACT_VERSION = "1.1"

    def build_snapshot(
        self,
        *,
        command: Any,
        csi_state: Dict[str, Any],
        decision: Optional[Dict[str, Any]] = None,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build an immutable awareness snapshot for the current request lifecycle.
        """

        # -------------------------------------------------
        # READ-ONLY ISOLATION (V1.1)
        # -------------------------------------------------
        safe_csi_state = copy.deepcopy(csi_state)
        safe_decision = copy.deepcopy(decision)
        safe_execution = copy.deepcopy(execution_result)

        snapshot: Dict[str, Any] = {
            "contract_version": self.CONTRACT_VERSION,
            "request_id": getattr(command, "request_id", None),
            "timestamp": datetime.utcnow().isoformat(),
            "awareness_level": self._awareness_level(
                safe_csi_state, safe_decision, safe_execution
            ),
            "where_are_we": self._describe_state(safe_csi_state),
            "what_we_know": self._extract_known_facts(command, safe_csi_state),
            "what_is_happening": self._describe_activity(
                safe_csi_state, safe_decision, safe_execution
            ),
            "what_user_likely_wants": self._infer_user_expectation(
                command, safe_csi_state, safe_decision
            ),
            "next_expected_step": self._next_step_hint(
                safe_csi_state, safe_decision, safe_execution
            ),
        }

        return snapshot

    # =========================================================
    # INTERNAL HELPERS (PURE, DETERMINISTIC)
    # =========================================================

    def _awareness_level(
        self,
        csi_state: Dict[str, Any],
        decision: Optional[Dict[str, Any]],
        execution_result: Optional[Dict[str, Any]],
    ) -> str:
        if csi_state.get("state") == "FAILED":
            return "critical"
        if csi_state.get("state") in {"EXECUTING", "DECISION_PENDING"}:
            return "active"
        return "idle"

    def _describe_state(self, csi_state: Dict[str, Any]) -> str:
        state = csi_state.get("state", "IDLE")

        if state == "DECISION_PENDING":
            return "Čekam tvoju potvrdu prije nastavka."
        if state == "EXECUTING":
            return "Izvršavam zadatak."
        if state == "SOP_ACTIVE":
            return "Pregledavamo aktivni SOP."
        if state == "SOP_LIST":
            return "Biramo odgovarajući SOP."
        if state == "COMPLETED":
            return "Zadatak je završen."
        if state == "FAILED":
            return "Došlo je do greške u procesu."

        return "Spreman sam za sljedeći korak."

    def _extract_known_facts(
        self, command: Any, csi_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        facts: Dict[str, Any] = {}

        if getattr(command, "identity_snapshot", None):
            facts["identity"] = command.identity_snapshot

        if getattr(command, "state_snapshot", None):
            facts["system_state"] = command.state_snapshot

        if csi_state.get("active_sop_id"):
            facts["active_sop"] = csi_state.get("active_sop_id")

        if csi_state.get("pending_decision"):
            facts["pending_decision"] = csi_state.get("pending_decision")

        return facts

    def _describe_activity(
        self,
        csi_state: Dict[str, Any],
        decision: Optional[Dict[str, Any]],
        execution_result: Optional[Dict[str, Any]],
    ) -> str:
        if execution_result is not None:
            if execution_result.get("success"):
                return "Akcija je uspješno izvršena."
            return "Akcija nije uspješno izvršena."

        if decision and decision.get("decision_candidate") and not decision.get("confirmed"):
            return "Pripremio sam prijedlog i čekam tvoju potvrdu."

        if csi_state.get("state") == "EXECUTING":
            return "Radim na zadatku."

        return "Nema aktivnih operacija."

    def _infer_user_expectation(
        self,
        command: Any,
        csi_state: Dict[str, Any],
        decision: Optional[Dict[str, Any]],
    ) -> str:
        if csi_state.get("state") == "DECISION_PENDING":
            return "Očekujem da potvrdiš ili odbiješ prijedlog."

        if decision and decision.get("decision_candidate"):
            return "Vjerovatno želiš da nastavim sa predloženom akcijom."

        if command.command:
            return f"Vjerovatno želiš da izvršim: {command.command}"

        return "Očekujem daljnje upute."

    def _next_step_hint(
        self,
        csi_state: Dict[str, Any],
        decision: Optional[Dict[str, Any]],
        execution_result: Optional[Dict[str, Any]],
    ) -> str:
        if execution_result is not None:
            return "Možemo nastaviti sa sljedećim zadatkom."

        if csi_state.get("state") == "DECISION_PENDING":
            return "Potrebna je tvoja potvrda."

        if csi_state.get("state") == "EXECUTING":
            return "Sačekaj da se izvršenje završi."

        return "Spreman sam za novu naredbu."
