from __future__ import annotations

from services.ceo_advisor_agent import build_ceo_instructions


def _mock_grounding_pack(*, kb_entries: int = 2) -> dict:
    return {
        "enabled": True,
        "identity_pack": {
            "hash": "h",
            "payload": {
                "schema_version": "identity_pack.v1",
                "identity": {"name": "Adnan", "role": "CEO"},
                "kernel": {"system_safety": {"rules": ["no silent writes"]}},
            },
        },
        "kb_retrieved": {
            "used_entry_ids": ["sys_overview_001"],
            "entries": [
                {
                    "id": f"kb_{i}",
                    "title": f"T{i}",
                    "tags": ["system"],
                    "priority": 1.0,
                    "content": "X" * 5000,
                }
                for i in range(kb_entries)
            ],
        },
        "notion_snapshot": {"status": "ok", "dashboard": {"goals": [], "tasks": []}},
        "memory_snapshot": {"hash": "m", "payload": {"notes": ["a"], "facts": []}},
    }


def test_build_ceo_instructions_contains_all_sections_and_governance():
    gp = _mock_grounding_pack(kb_entries=2)
    instructions = build_ceo_instructions(gp)

    assert isinstance(instructions, str)
    assert instructions.strip()

    assert "IDENTITY:" in instructions
    assert "KB_CONTEXT:" in instructions
    assert "NOTION_SNAPSHOT:" in instructions
    assert "MEMORY_CONTEXT:" in instructions

    # Governance: explicit no-general-knowledge rule
    assert "DO NOT use general world knowledge" in instructions
    assert "Nemam u KB/Memory/Snapshot" in instructions


def test_build_ceo_instructions_truncates_to_budgets():
    gp = _mock_grounding_pack(kb_entries=10)
    instructions = build_ceo_instructions(
        gp,
        kb_max_entries=3,
        total_max_chars=800,
        section_max_chars=250,
        kb_entry_max_chars=120,
    )

    assert len(instructions) <= 800
    # With aggressive budgets and long KB content, we should see truncation markers.
    assert "[TRUNCATED]" in instructions


def test_build_ceo_instructions_handles_empty_grounding_pack():
    instructions = build_ceo_instructions({}, total_max_chars=4000)
    assert isinstance(instructions, str)
    # Builder is deterministic; even empty input yields a minimal scaffold.
    assert "IDENTITY:" in instructions
    assert "KB_CONTEXT:" in instructions
    assert "NOTION_SNAPSHOT:" in instructions
    assert "MEMORY_CONTEXT:" in instructions
