from services.notion_task_to_agent_builder import build_agent_task_from_snapshot


def test_snapshot_task_builds_stable_task_text_and_source_task():
    task_item = {
        "notion_id": "abc123",
        "title": "Prepare weekly KPI report",
        "url": "https://notion.so/example",
        "fields": {
            "status": "in_progress",
            "due": "2026-03-10",
            "assigned_to": ["Adnan"],
            "secret": "MUST_NOT_LEAK",
        },
    }

    out = build_agent_task_from_snapshot(task_item)

    assert out.get("source_task") == {
        "notion_id": "abc123",
        "url": "https://notion.so/example",
    }

    expected = (
        "Task: Prepare weekly KPI report\n\n"
        "Source: https://notion.so/example\n\n"
        "Details:\n"
        "- status: in_progress\n"
        "- due: 2026-03-10\n"
        "- owner: Adnan"
    )

    assert out.get("task_text") == expected
    assert len(out.get("task_text") or "") <= 1500
    assert "MUST_NOT_LEAK" not in (out.get("task_text") or "")


def test_missing_fields_do_not_crash_and_fallback_to_unknown():
    task_item = {
        "notion_id": "n1",
        "title": "T",
        "url": "U",
        # fields missing
    }

    out = build_agent_task_from_snapshot(task_item)
    txt = out.get("task_text") or ""

    assert "- status: unknown" in txt
    assert "- due: unknown" in txt
    assert "- owner: unknown" in txt
    assert len(txt) <= 1500


def test_output_is_capped_to_1500_chars():
    long_title = "A" * 5000
    task_item = {
        "notion_id": "abc",
        "title": long_title,
        "url": "https://notion.so/long",
        "fields": {"status": "ok", "due": "2026-03-10", "assigned_to": "X"},
    }

    out = build_agent_task_from_snapshot(task_item)
    txt = out.get("task_text") or ""

    assert txt.startswith("Task: A")
    assert len(txt) <= 1500
