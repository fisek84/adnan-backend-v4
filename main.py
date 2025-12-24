import os
import sys
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from uvicorn import run

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


def validate_runtime_env_or_raise() -> None:
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        logger.critical("❌ Missing ENV vars: %s", ", ".join(missing))
        raise RuntimeError(f"Missing ENV vars: {', '.join(missing)}")
    logger.info("✅ Environment variables validated.")


# NOTE:
# - Do NOT sys.exit() on import. Tests import `app` via `main`.
# - Enforce strict env validation only when starting the server ( __main__ ).

# ============================================================
# LOAD FASTAPI APP (GATEWAY)
# ============================================================

from gateway.gateway_server import app  # noqa: E402

logger.info("✅ FastAPI gateway app loaded.")

# ============================================================
# SERVICE INITIALIZATION
# ============================================================

from services.ai_command_service import AICommandService  # noqa: E402
from services.coo_conversation_service import COOConversationService  # noqa: E402
from services.coo_translation_service import COOTranslationService  # noqa: E402

ai_command_service = AICommandService()
coo_translation_service = COOTranslationService()
coo_conversation_service = COOConversationService()

logger.info("🧠 Core AI services initialized.")

# ============================================================
# ROUTER DEPENDENCY INJECTION
# ============================================================

from routers.adnan_ai_router import set_adnan_ai_services  # noqa: E402
from routers.ai_router import set_ai_services  # noqa: E402

# --- PRIMARY /ai ROUTER (UX ENTRYPOINT) ---
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

_orchestrator_available = False

try:
    from dependencies import get_orchestrator_service, init_services  # noqa: E402

    init_services()
    _orchestrator_available = True
except Exception as e:
    logger.warning("ℹ️ dependencies init/orchestrator not available: %s", e)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if _orchestrator_available:
        try:
            orch = get_orchestrator_service()
            if orch:
                await orch.start()
                logger.info("✅ Orchestrator worker started.")
        except Exception as e:
            logger.error("❌ Orchestrator startup failed: %s", e)

    yield

    if _orchestrator_available:
        try:
            orch = get_orchestrator_service()
            if orch:
                await orch.stop()
                logger.info("✅ Orchestrator worker stopped.")
        except Exception as e:
            logger.error("❌ Orchestrator shutdown failed: %s", e)


# Attach lifespan to existing app instance (avoid deprecated on_event)
app.router.lifespan_context = _lifespan  # type: ignore[attr-defined]

# ============================================================
# CEO CONSOLE + NOTION OPS ROUTERS
# ============================================================

from routers import ceo_console_router  # noqa: E402
from routers import notion_ops_router  # noqa: E402


def ensure_ceo_console_router_mounted() -> None:
    """
    Mount CEO console router only once.

    Note: Some deployments mount API routers under /api, so we detect any existing
    path that contains "ceo-console" (e.g. /ceo-console/* or /api/ceo-console/*).
    """
    existing_paths = set()

    for route in app.routes:
        if isinstance(route, APIRoute):
            existing_paths.add(route.path)

    if any("ceo-console" in path for path in existing_paths):
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
    validate_runtime_env_or_raise()
    port = int(os.environ.get("PORT", 8000))
    logger.info("🚀 Starting Uvicorn on port %s", port)
    run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
