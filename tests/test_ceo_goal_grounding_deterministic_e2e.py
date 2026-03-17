from __future__ import annotations

from fastapi.testclient import TestClient

from services.ceo_conversation_state_store import ConversationStateStore


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _snapshot_with_goal(
    *,
    title: str,
    assigned_to: list[str] | None = None,
    status: str = "Active",
    due: str = "2026-04-03",
):
    fields = {"title": title, "status": status, "due": due}
    if assigned_to is not None:
        fields["assigned_to"] = assigned_to
    return {"id": "g1", "fields": fields}


def test_show_goals_kakve_imamo_ciljeve_persists_titles(monkeypatch):
    # Ensure deterministic path is used (no agent call).
    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("LLM path called")),
    )

    conversation_id = "conv_show_goals_1"
    snap = {
        "ready": True,
        "payload": {
            "goals": [
                _snapshot_with_goal(title="Goal A", assigned_to=["Alice"]),
                _snapshot_with_goal(
                    title="Goal B", assigned_to=["Bob"], due="2026-05-01"
                ),
            ],
            "tasks": [],
        },
    }

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Kakve imamo ciljeve?",
            "identity_pack": {"user_id": "test"},
            "snapshot": snap,
            "session_id": "sess_show_goals_1",
            "conversation_id": conversation_id,
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    text = (body.get("text") or "").strip()
    assert "Goal A" in text
    assert "Goal B" in text

    meta = ConversationStateStore.get_meta(conversation_id=conversation_id)
    assert isinstance(meta, dict)
    shown = meta.get("last_shown_goal_titles")
    assert isinstance(shown, list)
    assert "Goal A" in shown
    assert "Goal B" in shown


def test_top_goal_najbitniji_sets_last_referenced_goal(monkeypatch):
    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("LLM path called")),
    )

    conversation_id = "conv_top_goal_1"

    # Deterministic rank: status bucket then due. Make one blocked so it wins.
    snap = {
        "ready": True,
        "payload": {
            "goals": [
                _snapshot_with_goal(
                    title="Preseli se u EU za 30 dana.",
                    assigned_to=["Adnan"],
                    status="Active",
                    due="2026-04-03",
                ),
                _snapshot_with_goal(
                    title="Some other goal",
                    assigned_to=["X"],
                    status="Blocked",
                    due="2027-01-01",
                ),
            ],
            "tasks": [],
        },
    }

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Najbitniji cilj?",
            "identity_pack": {"user_id": "test"},
            "snapshot": snap,
            "session_id": "sess_top_goal_1",
            "conversation_id": conversation_id,
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    text = (body.get("text") or "").strip()
    assert "Glavni cilj" in text
    assert "Some other goal" in text

    meta = ConversationStateStore.get_meta(conversation_id=conversation_id)
    assert isinstance(meta, dict)
    assert meta.get("last_referenced_goal_title") == "Some other goal"


def test_goal_ownership_prefers_payload_over_dashboard_and_prints_fields(monkeypatch):
    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("LLM path called")),
    )

    conversation_id = "conv_owner_payload_1"

    goal_title = "Preseli se u EU za 30 dana."
    goal_fields = {
        "title": goal_title,
        "status": "Active",
        "due": "2026-04-03",
        "assigned_to": ["Adnan"],
    }

    snap = {
        "ready": True,
        "payload": {
            # Canonical list contains fields (what deterministic ownership must use).
            "goals": [{"id": "g1", "fields": goal_fields}],
            "tasks": [],
            # Dashboard contains a shallow goal item (historical bug source).
            "dashboard": {"goals": [{"id": "g1", "title": goal_title}]},
        },
    }

    # Snapshot payload proof (shown when running pytest with -s).
    print(
        "SNAPSHOT_PROOF payload.goals[0].fields =",
        snap["payload"]["goals"][0]["fields"],
    )  # noqa: T201

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": f"Ko radi na cilju: {goal_title}",
            "identity_pack": {"user_id": "test"},
            "snapshot": snap,
            "session_id": "sess_owner_payload_1",
            "conversation_id": conversation_id,
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    text = (body.get("text") or "").strip()

    assert goal_title in text
    assert "Za cilj" in text
    assert "Adnan" in text


def test_goal_ownership_followup_ovom_cilju_uses_last_referenced(monkeypatch):
    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("LLM path called")),
    )

    conversation_id = "conv_followup_ovom_1"
    goal_title = "Preseli se u EU za 30 dana."

    snap = {
        "ready": True,
        "payload": {
            "goals": [
                {
                    "id": "g1",
                    "fields": {
                        "title": goal_title,
                        "status": "Active",
                        "due": "2026-04-03",
                        "assigned_to": ["Adnan"],
                    },
                },
            ],
            "tasks": [],
        },
    }

    app = _load_app()
    client = TestClient(app)

    # First turn establishes last_referenced_goal_title.
    r1 = client.post(
        "/api/chat",
        json={
            "message": "Najbitniji cilj?",
            "identity_pack": {"user_id": "test"},
            "snapshot": snap,
            "session_id": "sess_followup_ovom_1",
            "conversation_id": conversation_id,
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r1.status_code == 200, r1.text

    # Follow-up must resolve to the last referenced goal.
    r2 = client.post(
        "/api/chat",
        json={
            "message": "Ko radi na ovom cilju?",
            "identity_pack": {"user_id": "test"},
            "snapshot": snap,
            "session_id": "sess_followup_ovom_1",
            "conversation_id": conversation_id,
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    text2 = (body2.get("text") or "").strip()

    assert goal_title in text2
    assert "Za cilj" in text2
    assert "Adnan" in text2


def test_goal_ownership_followup_koji_smo_spomenuli_uses_last_referenced(monkeypatch):
    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("LLM path called")),
    )

    conversation_id = "conv_followup_spomenuli_1"
    goal_title = "Preseli se u EU za 30 dana."

    snap = {
        "ready": True,
        "payload": {
            "goals": [
                {
                    "id": "g1",
                    "fields": {
                        "title": goal_title,
                        "status": "Active",
                        "due": "2026-04-03",
                        "assigned_to": ["Adnan"],
                    },
                },
            ],
            "tasks": [],
        },
    }

    app = _load_app()
    client = TestClient(app)

    r1 = client.post(
        "/api/chat",
        json={
            "message": "Najbitniji cilj?",
            "identity_pack": {"user_id": "test"},
            "snapshot": snap,
            "session_id": "sess_followup_spomenuli_1",
            "conversation_id": conversation_id,
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/api/chat",
        json={
            "message": "Ko radi na cilju koji smo spomenuli?",
            "identity_pack": {"user_id": "test"},
            "snapshot": snap,
            "session_id": "sess_followup_spomenuli_1",
            "conversation_id": conversation_id,
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    text2 = (body2.get("text") or "").strip()

    assert goal_title in text2
    assert "Za cilj" in text2
    assert "Adnan" in text2


def test_main_goal_glavni_intent_and_multisentence_followup_resolves_owner(
    monkeypatch,
):
    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("LLM path called")),
    )

    conversation_id = "conv_main_goal_multisentence_1"
    goal_title = "Preseli se u EU za 30 dana."

    snap = {
        "ready": True,
        "payload": {
            "goals": [
                {
                    "id": "g1",
                    "fields": {
                        "title": goal_title,
                        "status": "Active",
                        "due": "2026-04-03",
                        "assigned_to": ["Adnan"],
                    },
                },
            ],
            "tasks": [],
        },
    }

    app = _load_app()
    client = TestClient(app)

    r1 = client.post(
        "/api/chat",
        json={
            "message": "Koji je glavni cilj u firmi?",
            "identity_pack": {"user_id": "test"},
            "snapshot": snap,
            "session_id": "sess_main_goal_multisentence_1",
            "conversation_id": conversation_id,
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    text1 = (body1.get("text") or "").strip()
    assert goal_title in text1

    r2 = client.post(
        "/api/chat",
        json={
            "message": "Kome je dodjeljen ovaj cilj. Ko radi na ovom cilju",
            "identity_pack": {"user_id": "test"},
            "snapshot": snap,
            "session_id": "sess_main_goal_multisentence_1",
            "conversation_id": conversation_id,
            "metadata": {"include_debug": True, "read_only": True},
        },
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    text2 = (body2.get("text") or "").strip()

    assert goal_title in text2
    assert "Za cilj" in text2
    assert "Adnan" in text2
