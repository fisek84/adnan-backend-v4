from typing import Dict, Any


class FinalResponseEngine:
    """
    Adaptive Communication Layer
    -----------------------------
    Prima:
        - identity_reasoning
        - classification
        - raw_result (od orchestratora)
        - context_type

    Vraća:
        - final_response: str (u Adnan.AI stilu)
    """

    def __init__(self, identity: Dict[str, Any]):
        self.identity = identity

    def format_response(
        self,
        identity_reasoning: Dict[str, Any],
        classification: Dict[str, Any],
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Centralna funkcija — spaja sve informacije i generiše finalni
        komunikacijski stil Adnan.AI klona.
        """

        context = classification.get("context_type")
        raw = result.get("response") if isinstance(result, dict) else result

        # 1) Identitetski filter — tvoje vrijednosti i principi
        style = self._derive_style(identity_reasoning)

        # 2) Finalna kompozicija odgovora
        final_text = self._compose_text(style, context, raw)

        return {
            "final_answer": final_text,
            "context": context,
            "style": style,
            "raw": raw,
        }

    # --------------------------------------------------------------
    # PRIVAte metode
    # --------------------------------------------------------------

    def _derive_style(self, reasoning: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pretvara identity_reasoning u stil komunikacije:
        - fokus
        - preciznost
        - direktnost
        - sistemski ton
        """

        traits = reasoning.get("active_identity_traits", {})
        values = reasoning.get("active_values", [])
        mode = reasoning.get("current_mode")
        state = reasoning.get("current_state")

        return {
            "direct": True,
            "precise": True,
            "focused": True,
            "traits": traits,
            "values": values,
            "mode": mode,
            "state": state,
        }

    def _compose_text(self, style: Dict[str, Any], context: str, raw: Any) -> str:
        """
        Kreira finalni tekstualni format odgovora.
        Svi odgovori su:
            - kratki
            - jasni
            - fokusirani
            - bez šuma
        """

        if raw is None:
            return "Razumijem. Nastavljamo fokusirano."

        # Ako je već string → formatiramo ga
        if isinstance(raw, str):
            return self._apply_style(style, raw)

        # Ako je dict → izvući najvažnije
        if isinstance(raw, dict):
            summary = raw.get("message") or raw.get("summary") or raw.get("content")

            if not summary:
                summary = str(raw)

            return self._apply_style(style, summary)

        # Fallback
        return self._apply_style(style, str(raw))

    def _apply_style(self, style: Dict[str, Any], text: str) -> str:
        """
        Na tekst primjenjuje Adnan-style pravila komunikacije.
        """

        # Fokusirane rečenice
        text = text.strip()

        # Direktnost
        if style.get("direct", True):
            if not text.endswith("."):
                text = text + "."

        # Preciznost i sistemski ton
        text = text.replace("  ", " ")

        return text
