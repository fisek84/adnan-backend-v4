def some_chat_function(...):
    # existing code
    response = {
        "some_key": some_value,
        "knowledge_snapshot": _knowledge_bundle(),  # Including knowledge_snapshot
        "snapshot_meta": _knowledge_bundle(),  # Including snapshot_meta
        # other response keys
    }
    return response