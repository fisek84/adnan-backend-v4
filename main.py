# C:\adnan-backend-v4\main.py

import os
import sys
import logging
from dotenv import load_dotenv

from uvicorn import run
from fastapi.staticfiles import StaticFiles  # <<< DODANO

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
# RUNTIME GUARDS
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
# LOAD GATEWAY APP
# ============================================================

from gateway.gateway_server import app  # noqa

# ============================================================
# SERVICE INITIALIZATION
# ============================================================

from services.ai_command_service import AICommandService
from services.coo_translation_service import COOTranslationService

ai_command_service = AICommandService()
coo_translation_service = COOTranslationService()

logger.info("🧠 Core AI services initialized.")

# ============================================================
# ROUTER INJECTION
# ============================================================

from routers.ai_router import set_ai_services
from routers.adnan_ai_router import set_adnan_ai_services

set_ai_services(
    command_service=ai_command_service,
    coo=coo_translation_service,
)

set_adnan_ai_services(
    command_service=ai_command_service,
    coo=coo_translation_service,
)

logger.info("🔌 AI services injected.")

# ============================================================
# FRONTEND STATIC MOUNT  <<< KLJUČNI DIO
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
