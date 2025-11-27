from ext.notion.client import notion

def link_to_relation(page_id: str, relation_name: str, target_id: str):
    """
    Dodaje relation link na Notion stranicu.
    relation_name = ime relation property-ja u bazi (npr. "Project", "Goal")
    target_id = ID stranice/entiteta na koji se linkuje
    """

    notion.pages.update(
        page_id=page_id,
        properties={
            relation_name: {
                "relation": [{"id": target_id}]
            }
        }
    )
