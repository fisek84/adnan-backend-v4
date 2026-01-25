from __future__ import annotations


def test_lookup_identity_id_calls_resolve_with_allow_create_false(monkeypatch) -> None:
    import services.identity_resolver as ir  # noqa: PLC0415

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")

    called = {"allow_create": None}

    def _fake_resolve(_owner: str, *, allow_create: bool = True) -> str:
        called["allow_create"] = allow_create
        return "system"

    monkeypatch.setattr(ir, "resolve_identity_id", _fake_resolve)

    assert ir.lookup_identity_id("CEO") is None
    assert called["allow_create"] is False
