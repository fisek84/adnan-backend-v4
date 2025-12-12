from typing import Dict, Any, Tuple


class FinalResponseEngine:
    """
    Final Response Engine — FAZA 2 + FAZA 10

    Pravila:
    - chat mora zvučati prirodno
    - CEO / direktnost samo kad treba
    - final_answer uvijek string
    - FAZA 10: READ-ONLY explainability (bez side-effecta)
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

        # KNOWLEDGE (READ-ONLY REPORTING)
        if context_type == "knowledge":
            text = self._format_knowledge(result)
            return {"final_answer": text}

        raw = result.get("response") if isinstance(result, dict) else result

        style = self._derive_style(identity_reasoning, context_type)
        final_text = self._compose_final_text(
            context_type=context_type,
            raw=raw,
            style=style,
            result=result,
        )

        return {"final_answer": final_text}

    # ============================================================
    # STYLE
    # ============================================================
    def _derive_style(
        self,
        reasoning: Dict[str, Any],
        context_type: str,
    ) -> Dict[str, Any]:

        style = {
            "direct": False,
            "focused": False,
            "precise": False,
        }

        if context_type in {"business", "notion", "sop", "agent", "knowledge"}:
            style.update({
                "direct": True,
                "focused": True,
                "precise": True,
            })

        if context_type == "identity":
            style.update({
                "direct": True,
                "focused": True,
            })

        return style

    # ============================================================
    # KNOWLEDGE FORMATTER (SAFE)
    # ============================================================
    def _format_knowledge(self, result: Dict[str, Any]) -> str:
        """
        Sigurno formatiranje READ-ONLY znanja.
        """
        response = result.get("response")

        # FALLBACK: ako je string
        if isinstance(response, str):
            return response

        if not isinstance(response, dict):
            return "Nema dostupnih podataka."

        topic = response.get("topic")

        # GLOBAL REPORT
        if topic == "full_report":
            lines = ["📊 Pregled poslovne zgrade:"]
            databases = response.get("databases", {})
            for key, db in databases.items():
                label = db.get("label", key)
                count = len(db.get("items", []))
                lines.append(f"- {label}: {count}")
            return "\n".join(lines)

        # POJEDINAČNA BAZA
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
        style: Dict[str, Any],
        result: Dict[str, Any],
    ) -> str:

        if context_type == "identity":
            return raw or "Ja sam Adnan.AI."

        if context_type == "chat":
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
            return "Razumijem."

        if context_type == "memory":
            return "Zabilježeno."

        if context_type == "meta":
            return "Status je provjeren."

        if result.get("type") == "delegation":
            return "Zadatak je delegiran agentima."

        return self._format_generic(raw)

    # ============================================================
    # GENERIC FORMAT
    # ============================================================
    def _format_generic(self, raw: Any) -> str:
        if raw is None:
            return "U redu."

        if isinstance(raw, str):
            return raw

        if isinstance(raw, dict):
            return raw.get("summary") or "Operacija je završena."

        return str(raw)
