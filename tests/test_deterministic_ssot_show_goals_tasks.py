"""Tests for deterministic SSOT show/list goals+tasks and CEO_VIEW fallback.

Phase 1: test_show_goals_tasks_deterministic_when_snapshot_ready
  - POST /api/chat "Pokazi mi ciljeve i taskove" with ready snapshot →
    must return deterministic summary headings, never "Nemam SSOT snapshot".

Phase 2: test_budget_exceeded_still_lists_from_ceo_view
  - When notion_snapshot in grounding_pack is budget_exceeded/redacted but
    snapshot is ready with real titles, build_ceo_instructions must still
    emit real titles via CEO_VIEW.

Phase 2: test_ceo_view_present_in_instructions
  - build_ceo_instructions with grounding_pack containing ceo_view must
    include CEO_VIEW section even when notion_snapshot is missing/redacted.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _ready_snapshot():
    return {
        "ready": True,
        "status": "fresh",
        "schema_version": "v1",
        "payload": {
            "goals": [
                {
                    "id": "g1",
                    "title": "Rast prihoda Q1",
                    "status": "In Progress",
                    "due": "2026-03-31",
                },
                {
                    "id": "g2",
                    "title": "Lansiranje novog proizvoda",
                    "status": "Not Started",
                    "due": "2026-06-30",
                },
            ],
            "tasks": [
                {
                    "id": "t1",
                    "title": "Istraživanje tržišta",
                    "status": "In Progress",
                    "due": "2026-02-28",
                },
                {
                    "id": "t2",
                    "title": "Priprema prezentacije",
                    "status": "Not Started",
                    "due": "2026-03-05",
                },
            ],
            "projects": [],
        },
    }


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------


def test_show_goals_tasks_deterministic_when_snapshot_ready(monkeypatch):
    """Router must return deterministic summary for show/list intent when snapshot is ready."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")

    app = _get_app()
    client = TestClient(app)

    snap = _ready_snapshot()

    r = client.post(
        "/api/chat",
        json={
            "message": "Pokazi mi ciljeve i taskove",
            "snapshot": snap,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    txt = body.get("text") or ""

    # Must contain deterministic summary headings (from _render_snapshot_summary).
    assert "GOALS (top 3)" in txt or "goals" in txt.lower()
    assert "TASKS (top 5)" in txt or "tasks" in txt.lower()

    # Must include real goal/task titles.
    assert "Rast prihoda" in txt or "rast prihoda" in txt.lower()
    assert "Istraživanje" in txt or "istrazivanje" in txt.lower() or "Istra" in txt

    # Critical: must NEVER say "Nemam SSOT snapshot" when snapshot is ready.
    assert "Nemam SSOT snapshot" not in txt
    assert "nemam ssot snapshot" not in txt.lower()

    # Must be read-only.
    assert body.get("read_only") is True


def test_show_goals_tasks_bosnian_variants_deterministic(monkeypatch):
    """Multiple Bosnian show-intent phrases must all trigger deterministic path."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_GOALS_DB_ID", "test-goals-db")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "test-tasks-db")
    monkeypatch.setenv("NOTION_PROJECTS_DB_ID", "test-projects-db")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")

    app = _get_app()
    client = TestClient(app)

    snap = _ready_snapshot()

    for phrase in [
        "Pokazi mi ciljeve i taskove",
        "Pokaži ciljeve",
        "Izlistaj taskove",
        "Navedi ciljeve",
        "lista taskova",
    ]:
        r = client.post(
            "/api/chat",
            json={"message": phrase, "snapshot": snap},
        )
        assert r.status_code == 200, f"phrase={phrase!r}: {r.text}"
        txt = r.json().get("text") or ""
        assert "Nemam SSOT snapshot" not in txt, (
            f"phrase={phrase!r} leaked 'Nemam SSOT snapshot'"
        )


# ---------------------------------------------------------------------------
# Phase 2: test_ceo_view_present_in_instructions
# ---------------------------------------------------------------------------


def test_ceo_view_present_in_instructions():
    """build_ceo_instructions must emit CEO_VIEW section when ceo_view is in grounding_pack."""
    from services.ceo_advisor_agent import build_ceo_instructions

    ceo_view = {
        "goals_count": 2,
        "tasks_count": 3,
        "goals_top3": [
            {"title": "Rast prihoda Q1", "status": "In Progress", "due": "2026-03-31"},
        ],
        "tasks_top10": [
            {
                "title": "Istraživanje tržišta",
                "status": "In Progress",
                "due": "2026-02-28",
                "priority": "High",
                "goal_ids": [],
            },
        ],
    }

    # With notion_snapshot missing (redacted/absent) but ceo_view present.
    gp_no_notion = {
        "enabled": True,
        "identity_pack": {"payload": {"system": "test"}},
        "kb_retrieved": {"entries": [], "used_entry_ids": []},
        "ceo_view": ceo_view,
        # notion_snapshot intentionally absent.
        "memory_snapshot": {"payload": {}},
    }

    instructions = build_ceo_instructions(gp_no_notion)

    assert "CEO_VIEW:" in instructions
    assert "Rast prihoda Q1" in instructions
    assert "Istraživanje" in instructions or "goals_count" in instructions


def test_ceo_view_present_when_notion_snapshot_redacted():
    """CEO_VIEW must appear in instructions when notion_snapshot is budget_exceeded/redacted."""
    from services.ceo_advisor_agent import build_ceo_instructions

    ceo_view = {
        "goals_count": 1,
        "tasks_count": 2,
        "goals_top3": [
            {"title": "My Goal Title", "status": "Active", "due": "2026-04-01"}
        ],
        "tasks_top10": [
            {
                "title": "My Task Title",
                "status": "Todo",
                "due": "-",
                "priority": "Medium",
                "goal_ids": [],
            },
        ],
    }

    gp_redacted = {
        "enabled": True,
        "identity_pack": {"payload": {}},
        "kb_retrieved": {"entries": [], "used_entry_ids": []},
        "ceo_view": ceo_view,
        "notion_snapshot": {"status": "budget_exceeded", "ready": False, "payload": {}},
        "memory_snapshot": {"payload": {}},
    }

    instructions = build_ceo_instructions(gp_redacted)

    assert "CEO_VIEW:" in instructions
    assert "My Goal Title" in instructions
    # CEO_VIEW must appear BEFORE NOTION_SNAPSHOT in the instructions.
    ceo_view_pos = instructions.index("CEO_VIEW:")
    notion_pos = instructions.index("NOTION_SNAPSHOT:")
    assert ceo_view_pos < notion_pos


def test_ceo_view_absent_when_not_in_grounding_pack():
    """CEO_VIEW section must NOT appear when grounding_pack has no ceo_view."""
    from services.ceo_advisor_agent import build_ceo_instructions

    gp_no_ceo_view = {
        "enabled": True,
        "identity_pack": {"payload": {}},
        "kb_retrieved": {"entries": [], "used_entry_ids": []},
        "notion_snapshot": {"ready": False, "payload": {}},
        "memory_snapshot": {"payload": {}},
    }

    instructions = build_ceo_instructions(gp_no_ceo_view)
    assert "CEO_VIEW:" not in instructions


# ---------------------------------------------------------------------------
# Phase 2: test_budget_exceeded_still_lists_from_ceo_view
# ---------------------------------------------------------------------------


def test_budget_exceeded_still_lists_from_ceo_view(monkeypatch):
    """When notion_snapshot is budget_exceeded, real titles must appear via CEO_VIEW."""

    from services.ceo_advisor_agent import build_ceo_instructions

    # Simulate what the router injects into grounding_pack.
    ceo_view = {
        "goals_count": 1,
        "tasks_count": 1,
        "goals_top3": [{"title": "Prihod Q2", "status": "Active", "due": "2026-06-30"}],
        "tasks_top10": [
            {
                "title": "Kampanja lansiranja",
                "status": "In Progress",
                "due": "2026-03-01",
                "priority": "High",
                "goal_ids": ["g1"],
            },
        ],
    }

    gp = {
        "enabled": True,
        "identity_pack": {"payload": {}},
        "kb_retrieved": {"entries": [], "used_entry_ids": []},
        # Simulated budget_exceeded / redacted notion_snapshot.
        "notion_snapshot": {"status": "budget_exceeded", "ready": False, "payload": {}},
        "ceo_view": ceo_view,
        "memory_snapshot": {"payload": {}},
    }

    instructions = build_ceo_instructions(gp)

    # CEO_VIEW must carry real titles even though notion_snapshot is redacted.
    assert "Prihod Q2" in instructions
    assert "Kampanja lansiranja" in instructions
    assert "CEO_VIEW:" in instructions


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_is_show_goals_tasks_intent_matches():
    from routers.chat_router import _is_show_goals_tasks_intent

    positives = [
        "Pokazi mi ciljeve i taskove",
        "Pokaži ciljeve",
        "Prikazi taskove",
        "Izlistaj ciljeve",
        "Navedi taskove",
        "lista goals",
        "pokazi goals",
        "pokazi taskovi",
        "lista ciljevi",
        "navedi zadaci",
    ]
    for t in positives:
        assert _is_show_goals_tasks_intent(t), f"Expected True for {t!r}"


def test_is_show_goals_tasks_intent_no_match():
    from routers.chat_router import _is_show_goals_tasks_intent

    negatives = [
        "Kako kreirati cilj?",
        "Napravi novi task",
        "Koji je plan za Q2?",
        "refresh snapshot",
        "",
        "Planiram sljedeću sedmicu",
    ]
    for t in negatives:
        assert not _is_show_goals_tasks_intent(t), f"Expected False for {t!r}"


def test_compute_ceo_view_basic():
    from routers.chat_router import _compute_ceo_view

    snap = {
        "ready": True,
        "payload": {
            "goals": [
                {"title": "Goal A", "status": "Active", "due": "2026-03-31"},
                {"title": "Goal B", "fields": {"status": "Done", "due": "2026-01-01"}},
            ],
            "tasks": [
                {"title": "Task 1", "status": "Todo"},
                {"title": "Task 2", "fields": {"priority": "High"}},
            ],
        },
    }

    view = _compute_ceo_view(snap)

    assert view["goals_count"] == 2
    assert view["tasks_count"] == 2
    assert len(view["goals_top3"]) == 2
    assert len(view["tasks_top10"]) == 2
    assert view["goals_top3"][0]["title"] == "Goal A"
    assert view["tasks_top10"][0]["title"] == "Task 1"
    assert "priority" in view["tasks_top10"][0]
    assert "goal_ids" in view["tasks_top10"][0]


def test_compute_ceo_view_empty_snapshot():
    from routers.chat_router import _compute_ceo_view

    view = _compute_ceo_view({})
    assert view["goals_count"] == 0
    assert view["tasks_count"] == 0
    assert view["goals_top3"] == []
    assert view["tasks_top10"] == []


def test_compute_ceo_view_top3_top10_limits():
    from routers.chat_router import _compute_ceo_view

    snap = {
        "payload": {
            "goals": [{"title": f"G{i}"} for i in range(10)],
            "tasks": [{"title": f"T{i}"} for i in range(15)],
        }
    }
    view = _compute_ceo_view(snap)
    assert len(view["goals_top3"]) == 3
    assert len(view["tasks_top10"]) == 10
