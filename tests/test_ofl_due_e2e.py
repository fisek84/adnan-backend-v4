import os
import sqlalchemy as sa
from sqlalchemy import text, bindparam
from jobs.outcome_feedback_loop_job import run_once


def test_ofl_due_e2e():
    e = sa.create_engine(os.getenv("DATABASE_URL"))
    ids = ["test-decision-001", "test-decision-002"]

    upd = text("""
        update outcome_feedback_loop
        set review_at = now() - interval '2 minutes',
            delta = null,
            execution_result = null
        where decision_id in :ids
    """).bindparams(bindparam("ids", expanding=True))

    cnt = text("""
        select count(*)
        from outcome_feedback_loop
        where decision_id in :ids
          and review_at <= now()
          and delta is null
    """).bindparams(bindparam("ids", expanding=True))

    with e.begin() as c:
        c.execute(upd, {"ids": ids})

    with e.connect() as c:
        due_before = int(c.execute(cnt, {"ids": ids}).scalar() or 0)

    code = int(run_once() or 0)

    with e.connect() as c:
        due_after = int(c.execute(cnt, {"ids": ids}).scalar() or 0)

    assert due_before == 6
    assert code == 0
    assert due_after == 0
