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
# CEO CONSOLE ROUTER MOUNT (READ‑ONLY DASHBOARD)
# ============================================================

# CEO dashboard je čist READ layer: prikazuje stanje (snapshot), ne izvršava ništa.
# Da ne bismo duplo registrovali rute, prvo provjeravamo da li već postoje /ceo-console putevi.

from routers import ceo_console_router  # noqa: E402


def ensure_ceo_console_router_mounted() -> None:
    existing_paths = set()

    for route in app.routes:
        if isinstance(route, APIRoute):
            existing_paths.add(route.path)

    # Ako već postoji bilo koja ruta pod /ceo-console, ne mountamo ponovo.
    if any(path.startswith("/ceo-console") for path in existing_paths):
        logger.info("ℹ️ CEO console router already mounted; skipping include_router.")
        return

    app.include_router(ceo_console_router.router)
    logger.info("✅ CEO console router mounted at /ceo-console")


ensure_ceo_console_router_mounted()

# ============================================================
# FRONTEND STATIC MOUNT
# ============================================================

# UX je čisto čitanje kroz static files; sve operativno stanje dolazi iz backend API-ja.
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
