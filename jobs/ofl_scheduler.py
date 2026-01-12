# jobs/ofl_scheduler.py
from __future__ import annotations

import logging
import os

import sqlalchemy as sa
from sqlalchemy import text

from jobs.outcome_feedback_loop_job import run_once

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("ofl.scheduler")


def _db_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required")

    # Force psycopg3 driver, because bare postgres/postgresql URLs may resolve to psycopg2 dialect.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    return url


def _acquire_lock(conn) -> bool:
    lock_key = 0x0F1A0F1A
    got = conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar()
    return bool(got)


def _release_lock(conn) -> None:
    lock_key = 0x0F1A0F1A
    try:
        conn.execute(text("select pg_advisory_unlock(:k)"), {"k": lock_key})
    except Exception:
        pass


def _db_driver_probe_stdout() -> None:
    # Hard proof visible even if INFO logs are suppressed.
    print("db_driver_probe: start", flush=True)
    try:
        import psycopg  # psycopg3

        print(
            f"db_driver_probe: psycopg_present version={psycopg.__version__}", flush=True
        )
    except Exception as e:
        print(f"db_driver_probe: psycopg_missing err={repr(e)}", flush=True)

    try:
        import psycopg2  # psycopg2

        print(
            f"db_driver_probe: psycopg2_present version={psycopg2.__version__}", flush=True
        )
    except Exception as e:
        print(f"db_driver_probe: psycopg2_missing err={repr(e)}", flush=True)


def main() -> int:
    _db_driver_probe_stdout()

    e = sa.create_engine(_db_url(), pool_pre_ping=True)
    try:
        with e.connect() as c:
            if not _acquire_lock(c):
                logger.info("ofl_scheduler: lock_not_acquired (another instance running)")
                return 0

            try:
                rc = int(run_once() or 0)
                logger.info("ofl_scheduler: run_once_exit=%s", rc)
                return rc
            except Exception as exc:
                logger.exception("ofl_scheduler: failed: %s", exc)
                return 2
            finally:
                _release_lock(c)
    finally:
        e.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
