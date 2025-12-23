# services/coo_conversation_service.py
"""
COO CONVERSATION SERVICE (CANONICAL)

Uloga:
- JEZIK ZA LJUDE (UX / Conversation)
- vodi razgovor ka JASNOJ NAMJERI
- odlučuje DA LI JE SPREMNO za TRANSLATION
- NIKAD ne izvršava
- NIKAD ne gradi AICommand

FAZA 2: READ-ONLY
FAZA 3: priprema za approval / translation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from services.intent_classifier import IntentClassifier
from services.intent_contract import Intent, IntentType


@dataclass(frozen=True)
class COOConversationResult:
    """
    Canonical UX contract between Conversation layer and Router.
    """

    type: str  # "message" | "question" | "ready_for_translation"
    text: str
    next_actions: Optional[List[Dict[str, Any]]] = None
    readiness: Optional[Dict[str, Any]] = None


class COOConversationService:
    """
    COO Conversation Layer.
    """

    READ_ONLY_INTENTS = {
        IntentType.SYSTEM_QUERY,
    }

    def __init__(self):
        self.intent_classifier = IntentClassifier()

    # =========================================================
    # MAIN ENTRYPOINT
    # =========================================================
    def handle_user_input(
        self,
        raw_input: str,
        *,
        source: str,
        context: Dict[str, Any],
    ) -> COOConversationResult:
        user_text = (raw_input or "").strip()
        if not user_text:
            return COOConversationResult(
                type="question",
                text=(
                    "Nisam dobio poruku. Reci šta želiš provjeriti "
                    "(npr. stanje sistema, status agenata)."
                ),
                next_actions=[
                    {"label": "Pregled sistema", "example": "Pregledaj stanje sistema"},
                    {"label": "Status agenata", "example": "Koji agenti su aktivni?"},
                ],
            )

        intent: Intent = self.intent_classifier.classify(
            user_text,
            source=source,
        )

        # ======================================================
        # READ-ONLY INTENT — SPREMNO ZA TRANSLATION
        # ======================================================
        if (
            intent.type in self.READ_ONLY_INTENTS
            and intent.confidence >= self.intent_classifier.DEFAULT_CONFIDENCE_THRESHOLD
            and intent.is_executable
        ):
            return COOConversationResult(
                type="ready_for_translation",
                text="Spreman sam da izvršim read-only sistemski upit.",
                readiness={
                    "intent_type": intent.type.value,
                    "confidence": float(intent.confidence),
                    "requires_approval": False,
                },
            )

        # ======================================================
        # WRITE / EXECUTABLE — SPREMNO ZA TRANSLATION (UZ APPROVAL)
        # ======================================================
        if intent.is_executable:
            return COOConversationResult(
                type="ready_for_translation",
                text="Akcija je prepoznata i spremna za approval i dalju obradu.",
                readiness={
                    "intent_type": intent.type.value,
                    "confidence": float(intent.confidence),
                    "requires_approval": True,
                },
            )

        # ======================================================
        # IDENTITY / META QUESTIONS
        # ======================================================
        lowered = user_text.lower()
        if self._looks_like_identity_question(lowered):
            return COOConversationResult(
                type="message",
                text=(
                    "Ja sam Adnan.AI u COO režimu.\n"
                    "Moj zadatak je da razumijem tvoju namjeru "
                    "i pripremim je za sigurno izvršenje."
                ),
                next_actions=[
                    {"label": "Pregled sistema", "example": "Daj sistemski snapshot"},
                    {"label": "Status agenata", "example": "Koji agenti su aktivni?"},
                ],
            )

        # ======================================================
        # DEFAULT — NOT READY
        # ======================================================
        return COOConversationResult(
            type="question",
            text=(
                "Ovo još nije spremno za izvršenje.\n"
                "Pokušaj jasnije opisati šta želiš provjeriti ili uraditi."
            ),
            next_actions=[
                {"label": "Primjer", "example": "Pregledaj stanje sistema"},
                {"label": "Primjer", "example": "Koji agenti su aktivni?"},
            ],
        )

    # =========================================================
    # INTERNALS
    # =========================================================
    def _looks_like_identity_question(self, lowered_text: str) -> bool:
        triggers = [
            "ko si",
            "ko si ti",
            "šta si",
            "sta si",
            "šta radiš",
            "sta radis",
            "ko je adnan",
            "ko je adnan.ai",
        ]
        return any(t in lowered_text for t in triggers)
