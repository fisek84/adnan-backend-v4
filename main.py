import os
import sys
import logging

from dotenv import load_dotenv
from uvicorn import run
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRoute

# ============================================================
# ENV + PATH
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

load_dotenv()

# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger("adnan_ai_bootstrap")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ============================================================
# RUNTIME GUARDS (CORE)
# ============================================================

REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "NOTION_OPS_ASSISTANT_ID",
]

missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
if missing:
    logger.critical("❌ Missing ENV vars: %s", ", ".join(missing))
    sys.exit(1)

logger.info("✅ Environment variables validated.")

# ============================================================
# LOAD FASTAPI APP (GATEWAY)
# ============================================================

from gateway.gateway_server import app  # noqa: E402

logger.info("✅ FastAPI gateway app loaded.")

# ============================================================
# SERVICE INITIALIZATION
# ============================================================

from services.ai_command_service import AICommandService  # noqa: E402
from services.coo_translation_service import COOTranslationService  # noqa: E402
from services.coo_conversation_service import COOConversationService  # noqa: E402

ai_command_service = AICommandService()
coo_translation_service = COOTranslationService()
coo_conversation_service = COOConversationService()

logger.info("🧠 Core AI services initialized.")

# ============================================================
# ROUTER DEPENDENCY INJECTION
# ============================================================

from routers.ai_router import set_ai_services  # noqa: E402
from routers.adnan_ai_router import set_adnan_ai_services  # noqa: E402

# --- PRIMARY /ai ROUTER (UX → SYSTEM → EXECUTION) ---
set_ai_services(
    command_service=ai_command_service,
    conversation_service=coo_conversation_service,
    translation_service=coo_translation_service,
)

# --- SECONDARY /adnan-ai ROUTER (LEGACY / INTERNAL) ---
set_adnan_ai_services(
    command_service=ai_command_service,
    coo_translation=coo_translation_service,
    coo_conversation=coo_conversation_service,
)

logger.info("🔌 AI services injected.")

# ============================================================
# PHASE 5/6/7 SERVICES INIT (DEPENDENCIES SINGLETONS)
# ============================================================

try:
    from dependencies import init_services, get_orchestrator_service  # noqa: E402

    init_services()

    @app.on_event("startup")
    async def _startup_orchestrator_worker() -> None:
        try:
            orch = get_orchestrator_service()
            if orch:
                await orch.start()
                logger.info("✅ Orchestrator worker started.")
        except Exception as e:
            logger.error("❌ Orchestrator startup failed: %s", e)

    @app.on_event("shutdown")
    async def _shutdown_orchestrator_worker() -> None:
        try:
            orch = get_orchestrator_service()
            if orch:
                await orch.stop()
                logger.info("✅ Orchestrator worker stopped.")
        except Exception as e:
            logger.error("❌ Orchestrator shutdown failed: %s", e)

except Exception as e:
    logger.warning("ℹ️ dependencies init/orchestrator not available: %s", e)

# ============================================================
# CEO CONSOLE + NOTION OPS ROUTERS
# ============================================================

from routers import ceo_console_router  # noqa: E402
from routers import notion_ops_router  # noqa: E402


def ensure_ceo_console_router_mounted() -> None:
    existing_paths = set()

    for route in app.routes:
        if isinstance(route, APIRoute):
            existing_paths.add(route.path)

    if any(path.startswith("/ceo-console") for path in existing_paths):
        logger.info("ℹ️ CEO console router already mounted; skipping include_router.")
        return

    app.include_router(ceo_console_router.router)
    logger.info("✅ CEO console router mounted at /ceo-console")


ensure_ceo_console_router_mounted()

# Notion bulk ops router (bulk create/update/query za goals/tasks)
app.include_router(notion_ops_router.router)
logger.info("✅ Notion bulk ops router mounted at /notion-ops")

# ============================================================
# FRONTEND STATIC MOUNT
# ============================================================

app.mount(
    "/",
    StaticFiles(directory="gateway/frontend", html=True),
    name="frontend",
)

logger.info("🖥️ Frontend mounted at /")

# ============================================================
# START UVICORN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info("🚀 Starting Uvicorn on port %s", port)
    run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
