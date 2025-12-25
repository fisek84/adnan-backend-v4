# services/app_bootstrap.py
"""
APPLICATION BOOTSTRAP — CANONICAL (FAZA 14)

Uloga:
- Centralno mjesto za runtime wiring servisa
- JEDINI entrypoint za inicijalizaciju sistema
- NE sadrži biznis logiku
- NE sadrži UX logiku
- NE izvršava komande

Garantuje:
- jednokratnu inicijalizaciju
- ARCH_LOCK enforcement

FAZA 4 napomena:
- adnan_ai_router je READ/PROPOSE ONLY wrapper (ne izvršava)
- canonical chat endpoint (/api/chat) se wira u gateway_server.py
"""

from services.coo_translation_service import COOTranslationService
from services.coo_conversation_service import COOConversationService
from services.ai_command_service import AICommandService
from services.cron_service import CronService
from services.knowledge_snapshot_service import KnowledgeSnapshotService

from routers.adnan_ai_router import set_adnan_ai_services
from routers.ai_ops_router import set_cron_service

from system_version import ARCH_LOCK

# ---------------------------------------------------------
# INTERNAL BOOTSTRAP GUARD
# ---------------------------------------------------------
_BOOTSTRAPPED = False


def bootstrap_application() -> None:
    """
    Wire core AI services into routers.
    Must be called ONCE during application startup.
    """
    global _BOOTSTRAPPED

    if _BOOTSTRAPPED:
        raise RuntimeError("Application already bootstrapped")

    # ---------------------------------------------------------
    # ARCHITECTURE LOCK ENFORCEMENT
    # ---------------------------------------------------------
    if ARCH_LOCK is not True:
        raise RuntimeError("ARCH_LOCK must be True in production bootstrap")

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
    KnowledgeSnapshotService()

    # ❌ NAMJERNO NEMA cron job registracije
    # READ-ONLY snapshot se poziva ISKLJUČIVO na zahtjev

    set_cron_service(cron_service)

    # ---------------------------------------------------------
    # Inject into AdnanAI legacy router (READ/PROPOSE ONLY)
    # ---------------------------------------------------------
    # IMPORTANT: signature is positional (command_service, coo_translation, coo_conversation).
    # Using positional args avoids keyword mismatch regressions.
    set_adnan_ai_services(
        ai_command_service,
        coo_translation_service,
        coo_conversation_service,
    )

    _BOOTSTRAPPED = True
