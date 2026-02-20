from __future__ import annotations


def test_session_snapshot_cache_respects_min_last_sync():
    from services.session_snapshot_cache import SessionSnapshotCache

    cache = SessionSnapshotCache()

    cache.set(
        session_id="s1",
        db_keys_csv="tasks,projects",
        value={"last_sync": "2026-01-01T00:00:00Z", "payload": {"tasks": [1]}},
        ttl_seconds=60,
    )

    assert cache.get(session_id="s1", db_keys_csv="tasks,projects") is not None

    # Newer min_last_sync should suppress older cached entry.
    assert (
        cache.get(
            session_id="s1",
            db_keys_csv="tasks,projects",
            min_last_sync="2026-01-02T00:00:00Z",
        )
        is None
    )
