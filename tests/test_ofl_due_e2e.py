# tests/test_ofl_due_e2e.py
import os
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from jobs.outcome_feedback_loop_job import run_once


def _pk_col(tbl: sa.Table) -> sa.Column:
    pk_cols = list(tbl.primary_key.columns)
    if pk_cols:
        return pk_cols[0]
    return list(tbl.c)[0]


def _get_identity_id_if_exists(conn) -> str | None:
    md = sa.MetaData()
    identity = sa.Table("identity_root", md, autoload_with=conn)
    pk = _pk_col(identity)

    row = conn.execute(sa.select(pk).limit(1)).fetchone()
    if row and row[0] is not None:
        return str(row[0])
    return None


def _seed_ofl_rows(conn, ids):
    """
    Ubaci 3 prozora (7/14/30) po decision_id ako ne postoje.
    """
    md = sa.MetaData()
    ofl = sa.Table("outcome_feedback_loop", md, autoload_with=conn)

    cols = set(ofl.c.keys())

    # detektuj naziv kolone za "window days"
    if "evaluation_window_days" in cols:
        window_col = "evaluation_window_days"
    elif "window_days" in cols:
        window_col = "window_days"
    else:
        raise AssertionError(
            "NIJE POZNATO: u outcome_feedback_loop ne nalazim evaluation_window_days niti window_days."
        )

    # identity_id (ako postoji u OFL; ne pokušavaj insert u identity_root)
    identity_id = None
    if "identity_id" in cols:
        identity_id = _get_identity_id_if_exists(conn)

    now = datetime.utcnow()
    windows = [7, 14, 30]

    for decision_id in ids:
        for w in windows:
            row = {}

            # obavezni/business kolone
            if "decision_id" in cols:
                row["decision_id"] = decision_id
            row[window_col] = w

            if "review_at" in cols:
                row["review_at"] = now + timedelta(days=w)

            # REQUIRED u tvom DB: recommendation_summary je NOT NULL
            if "recommendation_summary" in cols:
                row["recommendation_summary"] = f"[test seed] {decision_id} window={w}"

            # često postoji, ali ne pretpostavljamo NOT NULL; setujemo samo ako kolona postoji
            if "recommendation_type" in cols:
                row["recommendation_type"] = "test"

            # marker evaluacije
            if "delta" in cols:
                row["delta"] = None

            # execution outcome marker (ako postoji)
            if "execution_result" in cols:
                row["execution_result"] = None

            if identity_id is not None:
                row["identity_id"] = identity_id

            # timestamps (ako postoje, setuj da izbjegnemo NOT NULL probleme)
            if "created_at" in cols:
                row["created_at"] = now
            if "updated_at" in cols:
                row["updated_at"] = now

            stmt = pg_insert(ofl).values(**row)

            try:
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["decision_id", window_col]
                )
            except Exception:
                stmt = stmt.on_conflict_do_nothing()

            conn.execute(stmt)


def test_ofl_due_e2e():
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("DATABASE_URL not set in CI; skipping OFL DB-backed E2E test")

    e = sa.create_engine(db_url, pool_pre_ping=True, future=True)

    ids = ["test-decision-001", "test-decision-002"]

    upd = text(
        """
            update outcome_feedback_loop
            set review_at = now() - interval '2 minutes',
                delta = null,
                execution_result = null
            where decision_id in :ids
            """
    ).bindparams(bindparam("ids", expanding=True))

    cnt = text(
        """
            select count(*)
            from outcome_feedback_loop
            where decision_id in :ids
              and review_at <= now()
              and delta is null
            """
    ).bindparams(bindparam("ids", expanding=True))

    # 0) SEED: eksplicitno seed-uj 7/14/30 (2 * 3 = 6)
    with e.begin() as c:
        _seed_ofl_rows(c, ids)

    # 1) Forsiraj redove u "due" stanje
    with e.begin() as c:
        c.execute(upd, {"ids": ids})

    with e.connect() as c:
        due_before = int(c.execute(cnt, {"ids": ids}).scalar() or 0)

    assert due_before == 6

    # 2) run_once treba evaluirati due redove
    code = int(run_once() or 0)
    assert code == 0

    with e.connect() as c:
        due_after = int(c.execute(cnt, {"ids": ids}).scalar() or 0)

    assert due_after == 0
