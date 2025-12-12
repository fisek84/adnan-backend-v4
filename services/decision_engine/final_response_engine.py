from typing import Dict, Any


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

        if context_type in {"business", "notion", "sop", "agent"}:
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
    # TEXT COMPOSITION
    # ============================================================
    def _compose_final_text(
        self,
        context_type: str,
        raw: Any,
        style: Dict[str, Any],
        result: Dict[str, Any],
    ) -> str:

        # -------------------------
        # IDENTITY
        # -------------------------
        if context_type == "identity":
            return self._apply_style(
                style,
                raw or "Ja sam Adnan.AI.",
            )

        # -------------------------
        # CHAT
        # -------------------------
        if context_type == "chat":
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
            return "Razumijem. Reci mi slobodno."

        # -------------------------
        # MEMORY
        # -------------------------
        if context_type == "memory":
            return "Zabilježeno."

        # -------------------------
        # META
        # -------------------------
        if context_type == "meta":
            return "Status je provjeren."

        # -------------------------
        # SOP / DELEGATION (FAZA 10)
        # -------------------------
        if result.get("type") == "delegation":
            return self._explain_delegation(result)

        # -------------------------
        # GENERIC
        # -------------------------
        return self._format_generic(raw, style)

    # ============================================================
    # FAZA 10 — EXPLAINABILITY (READ-ONLY)
    # ============================================================
    def _explain_delegation(self, result: Dict[str, Any]) -> str:
        """
        CEO-level explainability.
        Nikad ne utiče na izvršenje.
        """

        delegation = result.get("delegation", {})
        sop = delegation.get("sop")
        plan = delegation.get("plan")

        # fallback — staro ponašanje
        if not isinstance(plan, list) or not plan:
            return "Zadatak je delegiran agentu. Pratim izvršenje."

        lines = []
        if sop:
            lines.append(f"SOP '{sop}' je izvršen sljedećim redoslijedom:")

        for step in plan:
            step_id = step.get("step")
            agent = step.get("preferred_agent") or step.get("agent")
            score = step.get("delegation_score")

            if score is not None:
                lines.append(
                    f"- Korak '{step_id}' dodijeljen agentu '{agent}' (pouzdanost {score})."
                )
            else:
                lines.append(
                    f"- Korak '{step_id}' dodijeljen agentu '{agent}'."
                )

        return " ".join(lines)

    # ============================================================
    # FORMATTERS
    # ============================================================
    def _format_generic(self, raw: Any, style: Dict[str, Any]) -> str:
        if raw is None:
            return "U redu."

        if isinstance(raw, str):
            return self._apply_style(style, raw)

        if isinstance(raw, dict):
            summary = raw.get("summary") or raw.get("message")
            if summary:
                return self._apply_style(style, str(summary))
            return "Operacija je završena."

        return str(raw)

    # ============================================================
    # STYLE APPLICATION
    # ============================================================
    def _apply_style(self, style: Dict[str, Any], text: str) -> str:
        text = (text or "").strip()

        if not text:
            return "U redu."

        if style.get("direct") and not text.endswith("."):
            text += "."

        return text
