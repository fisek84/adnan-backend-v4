import os
import sys
import logging

from dotenv import load_dotenv
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
    missing = [v for v in REQUIRED_ENV_VARS if not (os.getenv(v) or "").strip()]
    if missing:
        logger.critical("❌ Missing ENV vars: %s", ", ".join(missing))
        raise RuntimeError(f"Missing ENV vars: {', '.join(missing)}")
    logger.info("✅ Environment variables validated.")


# ============================================================
# LOAD FASTAPI APP (SSOT: gateway/gateway_server.py)
# ============================================================

# IMPORTANT:
# - Do NOT mount routers/static here.
# - Do NOT override lifespan here.
# - gateway/gateway_server.py owns boot sequence (including agents.json load).
from gateway.gateway_server import app  # noqa: E402

logger.info("✅ FastAPI gateway app loaded (SSOT: gateway/gateway_server.py).")

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
