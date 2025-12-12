from typing import Dict, Any


class FinalResponseEngine:
    """
    Final Response Engine — FAZA 2

    - CEO govori jasno
    - decision_candidate mora imati jasan odgovor
    - NEMA executiona
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

        # KNOWLEDGE (READ-ONLY)
        if context_type == "knowledge":
            return {"final_answer": self._format_knowledge(result)}

        # 🔧 FIX: decision_candidate mora koristiti "message"
        if isinstance(result, dict) and result.get("type") == "decision_candidate":
            return {
                "final_answer": result.get(
                    "message",
                    "Prepoznata je potencijalna odluka. Da li potvrđuješ?"
                )
            }

        raw = result.get("response") if isinstance(result, dict) else result

        final_text = self._compose_final_text(
            context_type=context_type,
            raw=raw,
            result=result,
        )

        return {"final_answer": final_text}

    # ============================================================
    # KNOWLEDGE FORMATTER
    # ============================================================
    def _format_knowledge(self, result: Dict[str, Any]) -> str:
        response = result.get("response")

        if isinstance(response, str):
            return response

        if not isinstance(response, dict):
            return "Nema dostupnih podataka."

        topic = response.get("topic")
        items = response.get("items", [])
        count = response.get("count", len(items))

        if not items:
            return "Nema zapisa."

        lines = [f"📌 {topic.upper()} ({count}):"]
        for item in items:
            lines.append(f"- {item}")

        return "\n".join(lines)

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
            return raw.strip() if isinstance(raw, str) and raw.strip() else "Razumijem."

        if context_type == "memory":
            return "Zabilježeno."

        if context_type == "meta":
            return "Status je provjeren."

        return self._format_generic(raw)

    # ============================================================
    # GENERIC FORMAT
    # ============================================================
    def _format_generic(self, raw: Any) -> str:
        if raw is None:
            return "Razumijem."

        if isinstance(raw, str):
            return raw

        if isinstance(raw, dict):
            return raw.get("summary") or "U redu."

        return str(raw)
