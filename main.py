import os
import sys
import logging
from dotenv import load_dotenv

# ============================================================
# ENV + PATH
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

load_dotenv()

# ============================================================
# LOGGING (BOOTSTRAP SAFE)
# ============================================================

logger = logging.getLogger("adnan_ai_bootstrap")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ============================================================
# RUNTIME GUARDS — FAIL FAST + HARD VERIFICATION
# ============================================================

REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "NOTION_OPS_ASSISTANT_ID",
]

# 🔎 HARD DEBUG — OVO NAM DAJE ISTINU
logger.info("ENV CHECK → OPENAI_API_KEY present: %s", bool(os.getenv("OPENAI_API_KEY")))
logger.info(
    "ENV CHECK → NOTION_OPS_ASSISTANT_ID present: %s",
    bool(os.getenv("NOTION_OPS_ASSISTANT_ID")),
)

missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
if missing:
    logger.critical(
        "❌ Missing required environment variables: %s",
        ", ".join(missing),
    )
    sys.exit(1)

logger.info("✅ Environment variables validated.")

# ============================================================
# SINGLE ENTRYPOINT — GATEWAY (LOAD FIRST)
# ============================================================

try:
    from gateway.gateway_server import app  # noqa: E402
except Exception as e:
    logger.critical("❌ Failed to load gateway application: %s", e)
    sys.exit(1)

# ============================================================
# SERVICE INITIALIZATION (CANONICAL)
# ============================================================

from services.ai_command_service import AICommandService
from services.coo_translation_service import COOTranslationService

ai_command_service = AICommandService()
coo_translation_service = COOTranslationService()

logger.info("🧠 Core AI services initialized.")

# ============================================================
# ROUTER INJECTION — CANONICAL AI ROUTER (/ai/run)
# ============================================================

from routers.ai_router import set_ai_services

set_ai_services(
    command_service=ai_command_service,
    coo=coo_translation_service,
)

logger.info("🔌 AI services injected into /ai router.")

# ============================================================
# ROUTER INJECTION — ADNAN AI UX ROUTER (/adnan-ai/input)
# ============================================================

from routers.adnan_ai_router import set_adnan_ai_services

set_adnan_ai_services(
    command_service=ai_command_service,
    coo=coo_translation_service,
)

logger.info("🔌 AI services injected into /adnan-ai router.")

# ============================================================
# BOOT CONFIRMATION
# ============================================================

logger.info("🟢 Adnan.AI / Evolia OS backend loaded successfully.")
logger.info("🔒 Runtime guards active. Fail-fast enabled.")
