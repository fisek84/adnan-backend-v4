# main.py
from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from uvicorn import run

# ============================================================
# ENV + PATH
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# On Render (or any managed runtime), environment variables should come from the platform,
# not from a baked-in .env file. Keep dotenv for local dev only.
if os.getenv("RENDER") != "true":
    load_dotenv(override=False)

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
    # OpenAI
    "OPENAI_API_KEY",
    # Notion
    "NOTION_API_KEY",
    "NOTION_GOALS_DB_ID",
    "NOTION_TASKS_DB_ID",
    "NOTION_PROJECTS_DB_ID",
    # Ops assistant / internal
    "NOTION_OPS_ASSISTANT_ID",
]


def validate_runtime_env_or_raise() -> None:
    missing = [k for k in REQUIRED_ENV_VARS if not (os.getenv(k) or "").strip()]
    if missing:
        logger.critical("Missing ENV vars: %s", ", ".join(missing))
        raise RuntimeError(f"Missing ENV vars: {', '.join(missing)}")
    logger.info("Environment variables validated.")


# ============================================================
# LOAD FASTAPI APP (SSOT: gateway/gateway_server.py)
# ============================================================

# IMPORTANT:
# - Do NOT mount routers/static here.
# - Do NOT override lifespan here.
# - gateway/gateway_server.py owns boot sequence (including agents.json load).
from gateway.gateway_server import app  # noqa: E402

logger.info("FastAPI gateway app loaded (SSOT: gateway/gateway_server.py).")

# ============================================================
# START UVICORN
# ============================================================

if __name__ == "__main__":
    validate_runtime_env_or_raise()

    port = int(os.getenv("PORT", "8000"))
    logger.info("Starting Uvicorn on port %s", port)

    run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
