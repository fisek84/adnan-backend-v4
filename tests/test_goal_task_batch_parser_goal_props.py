from services.goal_task_batch_parser import (
    build_batch_operations_from_parsed,
    parse_goal_with_explicit_tasks,
)


def test_batch_parser_goal_extracts_status_and_priority_from_goal_line():
    prompt = (
        "Kreiraj cilj: Adnan X, Status Active, Priority low\n"
        "i zatim kreiraj Task: Majmun ganja majmuna, Status Active, Priority low"
    )

    parsed = parse_goal_with_explicit_tasks(prompt)
    assert parsed is not None, "Parser should recognize goal+task batch prompt"

    ops = build_batch_operations_from_parsed(parsed)
    assert isinstance(ops, list) and ops, "Should produce operations"
    assert ops[0].get("intent") == "create_goal"

    goal_payload = ops[0].get("payload") or {}
    assert goal_payload.get("title"), "Goal title must be present"
    assert goal_payload.get("status") == "Active"
    assert goal_payload.get("priority") == "low"


def test_batch_parser_goal_extracts_status_and_priority_from_multiline_goal_block():
    prompt = (
        "Kreiraj cilj: Adnan X\n"
        "Status Active\n"
        "Priority High\n"
        "Deadline 22.01.2026\n"
        "i zatim kreiraj Task: Majmun ganja majmuna, Status Active, Priority low"
    )

    parsed = parse_goal_with_explicit_tasks(prompt)
    assert parsed is not None, "Parser should recognize goal+task batch prompt"

    ops = build_batch_operations_from_parsed(parsed)
    assert isinstance(ops, list) and ops
    assert ops[0].get("intent") == "create_goal"

    goal_payload = ops[0].get("payload") or {}
    assert goal_payload.get("title")
    assert goal_payload.get("deadline") == "2026-01-22"
    assert goal_payload.get("status") == "Active"
    assert goal_payload.get("priority") == "High"
