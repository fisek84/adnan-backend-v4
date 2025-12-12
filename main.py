# main.py
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

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ============================================================
# SINGLE ENTRYPOINT — GATEWAY
# ============================================================
from gateway.gateway_server import app  # noqa: E402

logger.info("🟢 Adnan.AI / Evolia OS backend loaded (gateway entrypoint).")
