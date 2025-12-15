"""
COO CONVERSATION SERVICE (CANONICAL)

Uloga:
- JEZIK ZA LJUDE (Conversation / UX Language)
- vodi razgovor ka ODLUCI
- odlučuje da li je input spreman za TRANSLATION (COOTranslationService)

Ovdje se:
- NE izvršava
- NE kreira AICommand
- NE zove ExecutionOrchestrator
- NE piše trajnu memoriju (za sada)

Izlaz:
- UX odgovor tipa: message / question / ready_for_translation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from services.intent_classifier import IntentClassifier
from services.intent_contract import Intent, IntentType


@dataclass(frozen=True)
class COOConversationResult:
    """
    Canonical response contract between Conversation layer and Router/Frontend.
    """
    type: str  # "message" | "question" | "ready_for_translation"
    text: str
    next_actions: Optional[List[Dict[str, Any]]] = None
    readiness: Optional[Dict[str, Any]] = None


class COOConversationService:
    """
    COO-style conversation layer.

    Primarni cilj:
    - ne da "chat odgovor"
    - nego da dovede do jasne odluke:
      * šta želiš postići
      * koji scope
      * ko izvršava
      * treba li potvrda
    """

    SYSTEM_LEVEL_INTENTS = {
        IntentType.SYSTEM_QUERY,
    }

    def __init__(self):
        self.intent_classifier = IntentClassifier()

    def handle_user_input(
        self,
        raw_input: str,
        *,
        source: str,
        context: Dict[str, Any],
    ) -> COOConversationResult:
        """
        Entry point za JEZIK ZA LJUDE.

        Pravilo:
        - ako je intent izvršiv i dovoljno pouzdan
          * ali system-level → TRAŽI POTVRDU
          * inače → READY_FOR_TRANSLATION
        """

        user_text = (raw_input or "").strip()
        if not user_text:
            return COOConversationResult(
                type="question",
                text="Nisam dobio poruku. Napiši šta želiš postići (npr. pregled sistema, audit Notiona, dodjela zadatka agentu).",
                next_actions=[
                    {"label": "Pregled sistema", "example": "Pregledaj stanje sistema"},
                    {"label": "Audit Notiona", "example": "Uradi audit Notiona"},
                    {"label": "Aktivni agenti", "example": "Koji agenti su aktivni?"},
                ],
            )

        # 1) Deterministička klasifikacija
        intent: Intent = self.intent_classifier.classify(user_text, source=source)

        # --------------------------------------------------
        # 2) SYSTEM-LEVEL INTENT → TRAŽI ODOBRENJE
        # --------------------------------------------------
        if (
            intent.type in self.SYSTEM_LEVEL_INTENTS
            and intent.confidence >= self.intent_classifier.DEFAULT_CONFIDENCE_THRESHOLD
            and intent.is_executable
        ):
            return COOConversationResult(
                type="question",
                text=(
                    "Ovo je sistemska operacija i ne može se izvršiti direktno.\n"
                    "Za nastavak je potrebna autonomna potvrda.\n\n"
                    "Želiš li da zatražim odobrenje za izvršenje?"
                ),
                next_actions=[
                    {"label": "Da, zatraži odobrenje", "example": "da"},
                    {"label": "Ne, odustani", "example": "ne"},
                ],
                readiness={
                    "intent_type": intent.type.value,
                    "requires_approval": True,
                    "proposed_command": intent.allowed_commands[0] if intent.allowed_commands else None,
                },
            )

        # --------------------------------------------------
        # 3) NORMALNI EXECUTABLE INTENT → READY
        # --------------------------------------------------
        if self._is_ready_for_translation(intent):
            return COOConversationResult(
                type="ready_for_translation",
                text="Razumijem. Spremno za sistemsku naredbu.",
                readiness={
                    "intent_type": intent.type.value,
                    "confidence": float(intent.confidence),
                    "is_executable": bool(intent.is_executable),
                },
            )

        # --------------------------------------------------
        # 4) UX HANDLING / OBJAŠNJENJE
        # --------------------------------------------------
        lowered = user_text.lower()

        if self._looks_like_identity_question(lowered):
            return COOConversationResult(
                type="message",
                text=(
                    "Ja sam Adnan.AI u COO režimu: operativni interfejs između tebe (CEO) i sistemskog jezika.\n"
                    "Ne izvršavam ništa dok nije jasno šta želiš i dok ne postoji valjana sistemska naredba.\n"
                    "Ako je potrebna sistemska akcija, vodim proces odobrenja.\n\n"
                    "Reci šta želiš postići."
                ),
                next_actions=[
                    {"label": "Pregled sistema", "example": "Šta nam trenutno gori?"},
                    {"label": "Notion struktura", "example": "Imamo haos u Notionu, predloži plan sređivanja"},
                    {"label": "Agent zadatak", "example": "Dodijeli agentu audit Notiona"},
                ],
            )

        # --------------------------------------------------
        # 5) GENERALNI FALLBACK
        # --------------------------------------------------
        return COOConversationResult(
            type="question",
            text=(
                "Ovo još nije spremno za izvršenje.\n"
                "Reci mi cilj i opseg:\n"
                "- Šta tačno želiš postići?\n"
                "- Nad čim (Notion, agenti, sistem)?\n"
                "- Koliki scope (malo / srednje / široko)?"
            ),
            next_actions=[
                {"label": "Primjer (Notion)", "example": "Sredi strukturu Notiona za projekte i zadatke, opseg: srednje"},
                {"label": "Primjer (Sistem)", "example": "Analiziraj stanje sistema i daj top 5 rizika"},
                {"label": "Primjer (Agenti)", "example": "Dodijeli agentu notion_ops da uradi audit baze zadataka"},
            ],
        )

    # =========================================================
    # INTERNALS
    # =========================================================

    def _is_ready_for_translation(self, intent: Intent) -> bool:
        if intent.confidence < self.intent_classifier.DEFAULT_CONFIDENCE_THRESHOLD:
            return False
        if not intent.is_executable:
            return False
        allowed = getattr(intent, "allowed_commands", None)
        if not allowed:
            return False
        if len(allowed) != 1:
            return False
        return True

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
            "koja si ti",
            "ko si ti uopste",
        ]
        return any(t in lowered_text for t in triggers)
