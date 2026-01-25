import os

import pytest
import sqlalchemy as sa
from sqlalchemy import text

import jobs.ofl_scheduler as sched


if not os.getenv("DATABASE_URL"):
    pytest.skip(
        "DATABASE_URL not set in CI; skipping DB-backed scheduler lock test",
        allow_module_level=True,
    )


def test_scheduler_advisory_lock_blocks_second_runner(monkeypatch):
    url = os.environ["DATABASE_URL"]

    try:
        with sa.create_engine(url, pool_pre_ping=True).connect():
            pass
    except Exception:
        pytest.skip("PostgreSQL not reachable")

    e = sa.create_engine(url, pool_pre_ping=True)

    # Ensure scheduler reads DATABASE_URL
    monkeypatch.setenv("DATABASE_URL", url)

    # Hold the lock in this test session
    with e.connect() as c:
        got = c.execute(
            text("select pg_try_advisory_lock(:k)"),
            {"k": 0x0F1A0F1A},
        ).scalar()
        assert bool(got) is True

        # Now scheduler should see lock and exit 0 (no work)
        rc = sched.main()
        assert rc == 0

        # Cleanup
        c.execute(text("select pg_advisory_unlock(:k)"), {"k": 0x0F1A0F1A})
