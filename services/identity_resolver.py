import os
import sqlalchemy as sa


def _db_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def resolve_identity_id(owner: str) -> str:
    db_url = _db_url()
    if not db_url:
        return "system"  # fallback, no DB configured

    engine = sa.create_engine(db_url, pool_pre_ping=True, future=True)
    itype = (owner or "system").strip().lower()
    if itype == "ceo":
        itype_db = "CEO"
    elif itype == "agent":
        itype_db = "agent"
    else:
        itype_db = "system"

    with engine.begin() as conn:
        row = conn.execute(
            sa.text(
                "SELECT identity_id FROM identity_root WHERE identity_type = :t LIMIT 1"
            ),
            {"t": itype_db},
        ).fetchone()
        if row and row[0]:
            return str(row[0])

        conn.execute(
            sa.text("INSERT INTO identity_root (identity_type) VALUES (:t)"),
            {"t": itype_db},
        )
        row2 = conn.execute(
            sa.text(
                "SELECT identity_id FROM identity_root WHERE identity_type = :t ORDER BY created_at DESC LIMIT 1"
            ),
            {"t": itype_db},
        ).fetchone()
        if row2 and row2[0]:
            return str(row2[0])

    return "system"
