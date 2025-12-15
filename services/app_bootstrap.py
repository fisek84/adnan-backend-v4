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
from services.ai_command_service import AICommandService
from routers.adnan_ai_router import set_adnan_ai_services


def bootstrap_application() -> None:
    """
    Wire core AI services into routers.
    Must be called ONCE during application startup.
    """

    # Instantiate canonical services
    coo_service = COOTranslationService()
    ai_command_service = AICommandService()

    # Inject into router
    set_adnan_ai_services(
        command_service=ai_command_service,
        coo=coo_service,
    )
