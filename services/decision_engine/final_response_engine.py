from typing import Dict, Any, List


class FinalResponseEngine:
    """
    Final Response Engine — FAZA 2 + FAZA 10

    Pravila:
    - chat mora zvučati prirodno
    - CEO / direktnost samo kad treba
    - final_answer uvijek string (fallback)
    - ui_payload je STRUKTURA za frontend
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
        raw = result.get("response") if isinstance(result, dict) else result

        style = self._derive_style(identity_reasoning, context_type)

        # --------------------------------
        # KNOWLEDGE RESPONSE (STRUCTURED)
        # --------------------------------
        if result.get("type") == "knowledge":
            text, ui_payload = self._format_knowledge(result)
            return {
                "final_answer": text,
                "ui_payload": ui_payload,
            }

        # --------------------------------
        # DEFAULT
        # --------------------------------
        final_text = self._compose_final_text(
            context_type=context_type,
            raw=raw,
            style=style,
            result=result,
        )

        return {
            "final_answer": final_text,
            "ui_payload": None,
        }

    # ============================================================
    # STYLE
    # ============================================================
    def _derive_style(
        self,
        reasoning: Dict[str, Any],
        context_type: str,
    ) -> Dict[str, Any]:

        style = {"direct": False}

        if context_type in {"business", "notion", "sop", "agent", "identity"}:
            style["direct"] = True

        return style

    # ============================================================
    # KNOWLEDGE FORMATTER (STRUCTURED)
    # ============================================================
    def _format_knowledge(self, result: Dict[str, Any]) -> (str, Dict[str, Any]):
        response = result.get("response", {})
        topic = response.get("topic")
        items: List[str] = response.get("items", [])
        count = response.get("count", len(items))

        if not items:
            return "Nemam dostupne podatke.", None

        if topic == "goals":
            header = f"Trenutno imaš {count} aktivnih ciljeva."
            label = "Ciljevi"
        elif topic == "tasks":
            header = f"Trenutno imaš {count} zadataka."
            label = "Zadaci"
        elif topic == "projects":
            header = f"Trenutno imaš {count} projekata."
            label = "Projekti"
        else:
            header = f"Pregled ({count} stavki)."
            label = "Stavke"

        ui_payload = {
            "type": "list",
            "label": label,
            "items": items,
            "ordered": False,
        }

        return header, ui_payload

    # ============================================================
    # TEXT COMPOSITION (FALLBACK)
    # ============================================================
    def _compose_final_text(
        self,
        context_type: str,
        raw: Any,
        style: Dict[str, Any],
        result: Dict[str, Any],
    ) -> str:

        if context_type == "identity":
            return "Ja sam Adnan.AI."

        if context_type == "chat":
            return raw.strip() if isinstance(raw, str) else "Razumijem."

        if context_type == "memory":
            return "Zabilježeno."

        if context_type == "meta":
            return "Status je provjeren."

        if result.get("type") == "delegation":
            return "Akcija je delegirana."

        return "U redu."

