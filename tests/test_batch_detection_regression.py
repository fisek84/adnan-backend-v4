from services.notion_keyword_mapper import NotionKeywordMapper


def test_goal_field_in_task_command_does_not_trigger_batch_request():
    text = "Kreiraj task: Napisati post, Status: Active, Goal: 30 dana – Prodaja, Priority: high"
    assert NotionKeywordMapper.is_batch_request(text) is False
    assert NotionKeywordMapper.detect_intent(text) != "batch_request"


def test_goal_plus_tasks_structure_is_detected_as_batch_request():
    text = "Kreiraj cilj: X\nZadaci:\n1) A\n2) B"
    assert NotionKeywordMapper.detect_intent(text) == "batch_request"
    assert NotionKeywordMapper.is_batch_request(text) is True
