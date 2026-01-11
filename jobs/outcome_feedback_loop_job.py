from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict

import sqlalchemy as sa

from services.outcome_feedback_loop_service import OutcomeFeedbackLoopService

logger = logging.getLogger("ofl.job")


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if raw.isdigit():
        v = int(raw)
        if v > 0:
            return v
    return default


def _lock_key() -> int:
    # Constant across all instances; can be overridden via env for safety in multi-app DBs.
    return _env_int("OUTCOME_FEEDBACK_LOOP_LOCK_KEY", 91433711)


def _limit() -> int:
    return _env_int("OUTCOME_FEEDBACK_LOOP_EVAL_LIMIT", 50)


def run_once() -> int:
    svc = OutcomeFeedbackLoopService()
    engine = svc._engine()

    lock_key = _lock_key()
    limit = _limit()

    with engine.begin() as conn:
        if conn.dialect.name != "postgresql":
            logger.error("ofl_job_requires_postgres_for_advisory_lock")
            return 2

        got_lock = conn.execute(sa.text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar()
        if not got_lock:
            logger.info("ofl_job_lock_not_acquired", extra={"lock_key": lock_key})
            return 0

        try:
            res: Dict[str, Any] = svc.evaluate_due_reviews(limit=limit)
            logger.info(
                "ofl_job_run_summary",
                extra={
                    "ok": bool(res.get("ok")),
                    "processed": int(res.get("processed") or 0),
                    "updated": int(res.get("updated") or 0),
                    "errors": len(res.get("errors") or []),
                    "marker_column": res.get("marker_column"),
                    "limit": res.get("limit"),
                },
            )
            return 0 if res.get("ok") else 1
        except Exception:
            logger.exception("ofl_job_unhandled_exception")
            return 3
        finally:
            conn.execute(sa.text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})


def _configure_logging() -> None:
    level = (os.getenv("LOG_LEVEL") or "INFO").upper().strip()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


if __name__ == "__main__":
    _configure_logging()
    raise SystemExit(run_once())
