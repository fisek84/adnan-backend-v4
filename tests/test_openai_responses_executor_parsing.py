from services.agent_router.openai_responses_executor import OpenAIResponsesExecutor


def test_responses_executor_wraps_plain_text_as_text_dict():
    ex = OpenAIResponsesExecutor(client=object())
    out = ex._parse_json("Pariz", force_text_contract=True)
    assert out == {"text": "Pariz"}


def test_responses_executor_maps_single_string_dict_to_text():
    ex = OpenAIResponsesExecutor(client=object())
    out = ex._parse_json('{"answer":"Pariz"}', force_text_contract=True)
    assert out == {"text": "Pariz"}
