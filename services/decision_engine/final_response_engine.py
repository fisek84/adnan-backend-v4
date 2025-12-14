from typing import Dict, Any


class FinalResponseEngine:
    """
    FINAL RESPONSE ENGINE
    ROLE:
    - Formats final output only
    - No decision logic
    - No confidence scoring
    - Read-only explainability
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
            ),
        }

    # ============================================================
    # EXPLAINABILITY (READ-ONLY, NO CONFIDENCE)
    # ============================================================
    def _build_explainability(
        self,
        context_type: str,
    ) -> Dict[str, Any]:

        return {
            "context_type": context_type,
            "reasoning": [
                "Ovaj odgovor je generisan u read-only režimu.",
                "Nema operativnih implikacija.",
            ],
            "read_only": True,
        }

    def _explain_read_only(self, context_type: str) -> Dict[str, Any]:
        return {
            "context_type": context_type,
            "reasoning": ["READ-ONLY odgovor."],
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
        if isinstance(raw, str):
            return raw
        return "U redu."

    # ============================================================
    # KNOWLEDGE FORMAT
    # ============================================================
    def _format_knowledge(self, result: Dict[str, Any]) -> str:
        response = result.get("response")

        if isinstance(response, str):
            return response

        if not isinstance(response, dict):
            return "Nema zapisa."

        items = response.get("items", [])
        if not items:
            return "Nema zapisa."

        topic = (
            response.get("topic")
            or result.get("type")
            or "informacije"
        )

        lines = [f"{str(topic).upper()}:"]

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
        return str(raw)
