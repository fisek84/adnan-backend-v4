from __future__ import annotations


def test_extract_goals_tasks_prefers_payload_when_dashboard_empty():
    from services.ceo_advisor_agent import _extract_goals_tasks

    snapshot_payload = {
        "dashboard": {"goals": [], "tasks": []},
        "goals": [{"id": "g1"}],
        "tasks": [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}],
    }

    goals, tasks = _extract_goals_tasks(snapshot_payload)

    assert isinstance(goals, list)
    assert isinstance(tasks, list)
    assert len(goals) == 1
    assert len(tasks) == 3
