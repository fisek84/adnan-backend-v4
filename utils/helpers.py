from datetime import datetime, timezone
import uuid


def ping() -> dict:
    """
    Simple health-check helper.
    Returns structured info instead of a plain string.
    """
    return {
        "status": "helpers active",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "module": "helpers"
    }


def utc_now() -> str:
    """
    Returns current UTC timestamp in ISO 8601 format.
    Useful across the backend for logging, debugging, and Notion updates.
    """
    return datetime.now(timezone.utc).isoformat()


def ensure(value, message="Missing required value"):
    """
    Small validation helper.
    Raises ValueError if 'value' is None or empty.
    """
    if value in (None, "", [], {}):
        raise ValueError(message)
    return value


# =========================================
# NEW — UUID GENERATOR (required by backend)
# =========================================
def generate_uuid() -> str:
    """
    Generates a unique UUID4 string.
    Standard identifier for tasks/goals in Evolia Backend.
    """
    return str(uuid.uuid4())
