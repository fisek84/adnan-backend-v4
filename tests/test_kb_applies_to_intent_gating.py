def test_kb_retrieval_filters_by_intent_applies_to():
    from services.grounding_pack_service import GroundingPackService

    kb = {
        "version": "test",
        "entries": [
            {
                "id": "A",
                "title": "A",
                "tags": [],
                "applies_to": ["advisory"],
                "priority": 0.5,
                "content": "hello world",
                "updated_at": None,
            },
            {
                "id": "B",
                "title": "B",
                "tags": [],
                "applies_to": ["state_query"],
                "priority": 0.5,
                "content": "hello world",
                "updated_at": None,
            },
        ],
    }

    out_adv = GroundingPackService._retrieve_kb(
        prompt="hello world", kb=kb, intent="advisory"
    )
    assert out_adv.used_entry_ids == ["A"]

    out_state = GroundingPackService._retrieve_kb(
        prompt="hello world", kb=kb, intent="state_query"
    )
    assert out_state.used_entry_ids == ["B"]


def test_kb_retrieval_missing_applies_to_defaults_to_all():
    from services.grounding_pack_service import GroundingPackService

    kb = {
        "version": "test",
        "entries": [
            {
                "id": "C",
                "title": "C",
                "tags": [],
                # applies_to missing on purpose
                "priority": 0.5,
                "content": "hello world",
                "updated_at": None,
            }
        ],
    }

    out = GroundingPackService._retrieve_kb(
        prompt="hello world", kb=kb, intent="advisory"
    )
    assert out.used_entry_ids == ["C"]
