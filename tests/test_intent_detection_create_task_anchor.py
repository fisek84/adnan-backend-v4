from services.notion_keyword_mapper import NotionKeywordMapper


def test_detect_intent_anchor_create_task_at_start():
    text = "Kreiraj task: ADNAN X, Status: Active, Priority: Low"
    assert NotionKeywordMapper.detect_intent(text) == "create_task"


def test_detect_intent_create_goal_at_start():
    text = "Kreiraj cilj: ADNAN X, Status: Active, Priority: Low"
    assert NotionKeywordMapper.detect_intent(text) == "create_goal"


def test_detect_intent_batch_request_goal_plus_tasks_list():
    text = "Kreiraj cilj: X\nZadaci:\n1) Kreiraj task: A\n2) Kreiraj task: B"
    assert NotionKeywordMapper.detect_intent(text) == "batch_request"


def test_detect_intent_task_with_goal_field_is_not_goal_or_batch():
    text = "Kreiraj task: A, Goal: X, Status: Active"
    assert NotionKeywordMapper.detect_intent(text) == "create_task"
