from typing import Dict, Any


class FinalResponseEngine:
    """
    Final Response Engine — FAZA 2

    Pravila:
    - chat mora zvučati prirodno
    - CEO razmišlja, NE izvršava
    - follow-up pitanja samo ako postoji nejasnoća ili više opcija
    - final_answer uvijek string
    - READ-ONLY (bez side-effecta)
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

        # READ-ONLY KNOWLEDGE
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

        # CEO FOLLOW-UP (samo ako ima nejasnoće)
        follow_up = self._maybe_add_follow_up(
            context_type=context_type,
            result=result,
        )

        if follow_up:
            final_text = f"{final_text}\n\n{follow_up}"

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

        if context_type in {"business", "notion", "knowledge"}:
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
    # CEO FOLLOW-UP LOGIC (READ-ONLY)
    # ============================================================
    def _maybe_add_follow_up(
        self,
        context_type: str,
        result: Dict[str, Any],
    ) -> str | None:
        """
        CEO postavlja pitanje samo ako:
        - postoji nejasnoća
        - postoji više opcija
        """

        if context_type not in {"chat", "business", "knowledge"}:
            return None

        if not isinstance(result, dict):
            return None

        signals = result.get("signals", {})

        ambiguous = signals.get("ambiguous")
        multiple_options = signals.get("multiple_options")
        missing_info = signals.get("missing_info")

        if not (ambiguous or multiple_options or missing_info):
            return None

        # CEO-style follow-up
        if multiple_options:
            return "Koju od ovih opcija smatraš prioritetnom i zašto?"

        if missing_info:
            return "Šta trenutno nedostaje da bismo mogli donijeti jasnu odluku?"

        if ambiguous:
            return "Možeš li precizirati šta tačno želiš postići u ovom kontekstu?"

        return None

    # ============================================================
    # KNOWLEDGE FORMATTER (SAFE)
    # ============================================================
    def _format_knowledge(self, result: Dict[str, Any]) -> str:
        response = result.get("response")

        if isinstance(response, str):
            return response

        if not isinstance(response, dict):
            return "Nema dostupnih podataka."

        topic = response.get("topic")

        if topic == "full_report":
            lines = ["📊 Pregled poslovnog sistema:"]
            databases = response.get("databases", {})
            for key, db in databases.items():
                label = db.get("label", key)
                count = len(db.get("items", []))
                lines.append(f"- {label}: {count}")
            return "\n".join(lines)

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
            # CEO samo konstatuje, ne izvršava
            return "Delegacija je zabilježena."

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
