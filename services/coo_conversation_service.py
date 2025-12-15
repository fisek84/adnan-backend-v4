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
from services.intent_contract import Intent


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
        - ako je intent izvršiv i dovoljno pouzdan → READY_FOR_TRANSLATION
        - ako nije → vrati QUESTION/MESSAGE (ne rejected)
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

        # 2) Ako je spremno za izvršenje → pusti dalje (translation)
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

        # 3) Ako nije spremno → COO razgovor: objasni i vodi ka odluci
        #    Specijalni UX za česta pitanja tipa "ko si ti"
        lowered = user_text.lower()

        if self._looks_like_identity_question(lowered):
            return COOConversationResult(
                type="message",
                text=(
                    "Ja sam Adnan.AI u COO režimu: operativni interfejs između tebe (CEO) i sistemskog jezika.\n"
                    "Ne izvršavam ništa dok nije jasno šta želiš i dok ne postoji valjana sistemska naredba.\n"
                    "Reci šta želiš postići (cilj), a ja ću to dovesti do odluke i pripremiti komandni zahtjev."
                ),
                next_actions=[
                    {"label": "Pregled sistema", "example": "Šta nam trenutno gori?"},
                    {"label": "Notion struktura", "example": "Imamo haos u Notionu, predloži plan sređivanja"},
                    {"label": "Agent zadatak", "example": "Dodijeli agentu audit Notiona"},
                ],
            )

        # 4) Generalni fallback: umjesto "rejected", traži jasnoću
        return COOConversationResult(
            type="question",
            text=(
                "Ovo još nije spremno za izvršenje kao sistemska naredba.\n"
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
        # confidence threshold (isti princip kao translator, ali ovdje samo readiness)
        if intent.confidence < self.intent_classifier.DEFAULT_CONFIDENCE_THRESHOLD:
            return False
        if not intent.is_executable:
            return False
        allowed = getattr(intent, "allowed_commands", None)
        if not allowed:
            return False
        # Ako ima više mogućih komandi, conversation layer treba razjasniti (za sada: nije ready)
        if len(allowed) != 1:
            return False
        return True

    def _looks_like_identity_question(self, lowered_text: str) -> bool:
        # Bosanski + kolokvijalno
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
