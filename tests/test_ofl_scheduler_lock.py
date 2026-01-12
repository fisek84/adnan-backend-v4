import os
import sqlalchemy as sa
from sqlalchemy import text

import jobs.ofl_scheduler as sched


def test_scheduler_advisory_lock_blocks_second_runner(monkeypatch):
    url = os.getenv("DATABASE_URL")
    assert url, "DATABASE_URL must be set for this test"
    e = sa.create_engine(url, pool_pre_ping=True)

    # Hold the lock in this test session
    with e.connect() as c:
        got = c.execute(text("select pg_try_advisory_lock(:k)"), {"k": 0x0F1A0F1A}).scalar()
        assert bool(got) is True

        # Now scheduler should see lock and exit 0 (no work)
        rc = sched.main()
        assert rc == 0

        c.execute(text("select pg_advisory_unlock(:k)"), {"k": 0x0F1A0F1A})
