# services/app_bootstrap.py
"""
APPLICATION BOOTSTRAP — CANONICAL

Uloga:
- Centralno mjesto za runtime wiring servisa
- JEDINI entrypoint za inicijalizaciju sistema
- NE sadrži biznis logiku
- NE izvršava cron automatski (samo capability)

Garantuje:
- jednokratnu inicijalizaciju
- ARCH_LOCK enforcement
"""

from services.coo_translation_service import COOTranslationService
from services.coo_conversation_service import COOConversationService
from services.ai_command_service import AICommandService
from services.cron_service import CronService
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.alignment_drift_monitor import AlignmentDriftMonitor
from services.data_freshness_monitor import DataFreshnessMonitor

from routers.adnan_ai_router import set_adnan_ai_services
from routers.ai_ops_router import set_cron_service

from system_version import ARCH_LOCK

# ---------------------------------------------------------
# INTERNAL BOOTSTRAP GUARD
# ---------------------------------------------------------
_BOOTSTRAPPED = False


# ---------------------------------------------------------
# CRON JOB WRAPPERS (FAIL-SAFE)
# ---------------------------------------------------------
def _cron_job_alignment_drift_monitor() -> dict:
    try:
        return AlignmentDriftMonitor().run()
    except Exception as e:
        return {
            "ok": False,
            "skipped": True,
            "reason": "alignment_drift_monitor_failed",
            "error": str(e),
        }


def _cron_job_data_freshness_monitor() -> dict:
    try:
        return DataFreshnessMonitor().run()
    except Exception as e:
        return {
            "ok": False,
            "skipped": True,
            "reason": "data_freshness_monitor_failed",
            "error": str(e),
        }


# ---------------------------------------------------------
# BOOTSTRAP
# ---------------------------------------------------------
def bootstrap_application() -> None:
    global _BOOTSTRAPPED

    if _BOOTSTRAPPED:
        raise RuntimeError("Application already bootstrapped")

    # ARCH LOCK
    if ARCH_LOCK is not True:
        raise RuntimeError("ARCH_LOCK must be True in production bootstrap")

    # Core services
    coo_translation_service = COOTranslationService()
    coo_conversation_service = COOConversationService()
    ai_command_service = AICommandService()

    # Cron capability (NO AUTOMATIC EXECUTION)
    cron_service = CronService()

    # Snapshot capability (on-demand)
    KnowledgeSnapshotService()

    # Register cron jobs (manual trigger only)
    cron_service.register(
        "alignment_drift_monitor",
        _cron_job_alignment_drift_monitor,
    )
    cron_service.register(
        "data_freshness_monitor",
        _cron_job_data_freshness_monitor,
    )

    set_cron_service(cron_service)

    # Inject legacy AdnanAI router (READ / PROPOSE ONLY)
    set_adnan_ai_services(
        ai_command_service,
        coo_translation_service,
        coo_conversation_service,
    )

    _BOOTSTRAPPED = True
