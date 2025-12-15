"""
APPLICATION BOOTSTRAP (CANONICAL)

Uloga:
- Centralno mjesto za runtime wiring servisa
- NE sadrži biznis logiku
- NE sadrži UX logiku
- NE izvršava komande

Odgovornost:
- instancira servise
- povezuje router ↔ servisi
"""

from services.coo_translation_service import COOTranslationService
from services.coo_conversation_service import COOConversationService
from services.ai_command_service import AICommandService
from services.cron_service import CronService
from services.knowledge_snapshot_service import KnowledgeSnapshotService

from routers.adnan_ai_router import set_adnan_ai_services
from routers.ai_ops_router import set_cron_service


def bootstrap_application() -> None:
    """
    Wire core AI services into routers.
    Must be called ONCE during application startup.
    """

    # ---------------------------------------------------------
    # Instantiate canonical services
    # ---------------------------------------------------------
    coo_translation_service = COOTranslationService()
    coo_conversation_service = COOConversationService()
    ai_command_service = AICommandService()

    # ---------------------------------------------------------
    # READ-ONLY Scheduler (CAPABILITY ONLY — NO JOBS)
    # ---------------------------------------------------------
    cron_service = CronService()
    knowledge_snapshot_service = KnowledgeSnapshotService()

    # ❌ NAMJERNO NEMA cron job registracije
    # READ-ONLY snapshot se poziva EKSKLUZIVNO na zahtjev

    # Inject cron into OPS router (NO EXECUTION HERE)
    set_cron_service(cron_service)

    # ---------------------------------------------------------
    # Inject into router (CANONICAL)
    # ---------------------------------------------------------
    set_adnan_ai_services(
        command_service=ai_command_service,
        coo_translation=coo_translation_service,
        coo_conversation=coo_conversation_service,
    )
