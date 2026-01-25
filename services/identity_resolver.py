from __future__ import annotations

import logging
import os
from typing import Optional

import sqlalchemy as sa


logger = logging.getLogger(__name__)

_WARNED_MISSING_IDENTITY_ROOT = False


def _db_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def _normalize_identity_type(owner: str) -> str:
    itype = (owner or "system").strip().lower()
    if itype == "ceo":
        return "CEO"
    if itype == "agent":
        return "agent"
    return "system"


def _is_missing_identity_root_error(exc: BaseException) -> bool:
    s = str(exc).lower()
    return "identity_root" in s and (
        "does not exist" in s
        or "undefinedtable" in s
        or "undefined table" in s
        or "relation" in s
    )


def _warn_missing_identity_root_once() -> None:
    global _WARNED_MISSING_IDENTITY_ROOT  # noqa: PLW0603
    if _WARNED_MISSING_IDENTITY_ROOT:
        return
    _WARNED_MISSING_IDENTITY_ROOT = True
    logger.warning("identity_root_missing_run_alembic")


def _is_on_conflict_missing_constraint_error(exc: BaseException) -> bool:
    # Postgres: "there is no unique or exclusion constraint matching the ON CONFLICT specification"
    s = str(exc).lower()
    return "on conflict" in s and "no unique" in s and "constraint" in s


def resolve_identity_id(owner: str, *, allow_create: bool = True) -> str:
    """Resolve identity_id from Postgres identity_root.

    - Default is allow_create=True (zero-breaking for existing callers).
    - When allow_create=False, this function is strictly read-only (SELECT only).
    - If DATABASE_URL is not configured or identity_root is missing, returns "system".
    """

    db_url = _db_url()
    if not db_url:
        return "system"  # fallback, no DB configured

    engine = sa.create_engine(db_url, pool_pre_ping=True, future=True)
    itype_db = _normalize_identity_type(owner)

    with engine.begin() as conn:
        try:
            row = conn.execute(
                sa.text(
                    "SELECT identity_id FROM identity_root WHERE identity_type = :t LIMIT 1"
                ),
                {"t": itype_db},
            ).fetchone()
        except (sa.exc.ProgrammingError, sa.exc.DBAPIError) as e:  # noqa: PERF203
            if _is_missing_identity_root_error(e):
                _warn_missing_identity_root_once()
                return "system"
            return "system"

        if row and row[0]:
            return str(row[0])

        if not allow_create:
            return "system"

        # Best-effort deterministic insert:
        # - prefer ON CONFLICT when a UNIQUE exists (enterprise hardened)
        # - fall back to plain INSERT on older schemas
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO identity_root (identity_type) VALUES (:t) "
                    "ON CONFLICT (identity_type) DO NOTHING"
                ),
                {"t": itype_db},
            )
        except (sa.exc.ProgrammingError, sa.exc.DBAPIError) as e:  # noqa: PERF203
            if _is_missing_identity_root_error(e):
                _warn_missing_identity_root_once()
                return "system"
            if _is_on_conflict_missing_constraint_error(e):
                try:
                    conn.execute(
                        sa.text(
                            "INSERT INTO identity_root (identity_type) VALUES (:t)"
                        ),
                        {"t": itype_db},
                    )
                except (sa.exc.ProgrammingError, sa.exc.DBAPIError) as e2:  # noqa: PERF203
                    if _is_missing_identity_root_error(e2):
                        _warn_missing_identity_root_once()
                        return "system"
                    return "system"
            else:
                return "system"

        try:
            row2 = conn.execute(
                sa.text(
                    "SELECT identity_id FROM identity_root WHERE identity_type = :t "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": itype_db},
            ).fetchone()
        except (sa.exc.ProgrammingError, sa.exc.DBAPIError) as e:  # noqa: PERF203
            if _is_missing_identity_root_error(e):
                _warn_missing_identity_root_once()
                return "system"
            return "system"

        if row2 and row2[0]:
            return str(row2[0])

    return "system"


def lookup_identity_id(owner: str) -> Optional[str]:
    """Read-only identity lookup (no INSERTs).

    Returns UUID string when resolvable; otherwise returns None.
    """

    if not _db_url():
        return None
    v = resolve_identity_id(owner, allow_create=False)
    return (
        v
        if isinstance(v, str) and v.strip() and v.strip().lower() != "system"
        else None
    )
