from typing import Dict, Any


class FinalResponseEngine:
    """
    FINAL RESPONSE ENGINE — FAZA 2 + FAZA 10

    FAZA 10:
    - READ-ONLY explainability
    - confidence signal (low / medium / high)
    - NEMA izvršenja
    - NEMA memorije
    - NEMA logike odlučivanja
    """

    def __init__(self, identity: Dict[str, Any]):
        self.identity = identity

    # ============================================================
    # PUBLIC API
    # ============================================================
    def format_response(
        self,
        identity_reasoning: Dict[str, Any],
        classification: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:

        context_type = classification.get("context_type")

        # -----------------------------
        # KNOWLEDGE (READ-ONLY)
        # -----------------------------
        if context_type == "knowledge":
            return {
                "final_answer": self._format_knowledge(result),
                "explainability": self._explain_read_only(context_type),
            }

        raw = result.get("response") if isinstance(result, dict) else result

        final_text = self._compose_final_text(
            context_type=context_type,
            raw=raw,
            result=result,
        )

        return {
            "final_answer": final_text,
            "explainability": self._build_explainability(
                context_type=context_type,
                result=result,
            ),
        }

    # ============================================================
    # FAZA 10 — EXPLAINABILITY
    # ============================================================
    def _build_explainability(
        self,
        context_type: str,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:

        explanation = {
            "context_type": context_type,
            "confidence": self._confidence_level(context_type, result),
            "reasoning": [],
            "read_only": True,
        }

        if context_type in {"chat", "identity", "meta"}:
            explanation["reasoning"].append(
                "Ovo je informativni odgovor bez poslovne odluke."
            )

        if result.get("type") == "decision_candidate":
            explanation["reasoning"].append(
                "Prepoznata je potencijalna odluka, ali nije izvršena."
            )

        if result.get("type") == "delegation":
            explanation["reasoning"].append(
                "Odluka je potvrđena od strane korisnika i delegirana."
            )

        if "recommendation" in result:
            explanation["reasoning"].append(
                "Preporuka je bazirana na historijskim podacima (READ-ONLY)."
            )

        return explanation

    def _confidence_level(
        self,
        context_type: str,
        result: Dict[str, Any],
    ) -> str:

        if context_type in {"chat", "identity"}:
            return "high"

        if result.get("type") == "decision_candidate":
            return "medium"

        if result.get("type") == "delegation":
            return "high"

        return "low"

    def _explain_read_only(self, context_type: str) -> Dict[str, Any]:
        return {
            "context_type": context_type,
            "confidence": "high",
            "reasoning": [
                "Sistem je u READ-ONLY režimu.",
                "Nema odluka niti izvršenja.",
            ],
            "read_only": True,
        }

    # ============================================================
    # TEXT COMPOSITION
    # ============================================================
    def _compose_final_text(
        self,
        context_type: str,
        raw: Any,
        result: Dict[str, Any],
    ) -> str:

        if context_type == "identity":
            return raw or "Ja sam Adnan.AI."

        if context_type == "chat":
            return raw.strip() if isinstance(raw, str) else "Razumijem."

        if context_type == "memory":
            return "Zabilježeno."

        if result.get("type") == "decision_candidate":
            return result.get("message", "Prepoznata je potencijalna odluka.")

        if result.get("type") == "delegation":
            return result.get(
                "system_response",
                "Odluka je delegirana odgovarajućem agentu."
            )

        return self._format_generic(raw)

    # ============================================================
    # KNOWLEDGE FORMAT
    # ============================================================
    def _format_knowledge(self, result: Dict[str, Any]) -> str:
        response = result.get("response")

        if isinstance(response, str):
            return response

        if not isinstance(response, dict):
            return "Nema dostupnih podataka."

        topic = response.get("topic")

        if topic == "full_report":
            lines = ["Pregled sistema:"]
            for key, db in response.get("databases", {}).items():
                label = db.get("label", key)
                count = len(db.get("items", []))
                lines.append(f"- {label}: {count}")
            return "\n".join(lines)

        items = response.get("items", [])
        if not items:
            return "Nema zapisa."

        lines = [f"{topic.upper()}:"]
        for item in items:
            lines.append(f"- {item}")

        return "\n".join(lines)

    # ============================================================
    # GENERIC
    # ============================================================
    def _format_generic(self, raw: Any) -> str:
        if raw is None:
            return "U redu."

        if isinstance(raw, str):
            return raw

        if isinstance(raw, dict):
            return raw.get("summary") or "Operacija završena."

        return str(raw)
