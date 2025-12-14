# C:\adnan-backend-v4\main.py

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
# RUNTIME GUARDS — FAIL FAST
# ============================================================

REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "NOTION_OPS_ASSISTANT_ID",
]

missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
if missing:
    logger.critical(
        "❌ Missing required environment variables: %s",
        ", ".join(missing),
    )
    sys.exit(1)

logger.info("✅ Environment variables validated.")

# ============================================================
# SINGLE ENTRYPOINT — GATEWAY
# ============================================================

try:
    from gateway.gateway_server import app  # noqa: E402
except Exception as e:
    logger.critical("❌ Failed to load gateway application: %s", e)
    sys.exit(1)

# ============================================================
# BOOT CONFIRMATION
# ============================================================

logger.info("🟢 Adnan.AI / Evolia OS backend loaded successfully.")
logger.info("🔒 Runtime guards active. Fail-fast enabled.")
