"""
Notion Ops Bilingual Support - Practical Examples

This file demonstrates practical usage of the Notion Ops Agent
with bilingual support (Bosnian and English).
"""

from services.notion_keyword_mapper import (
    NotionKeywordMapper,
    translate_to_english,
    translate_payload,
    is_batch_request,
)
from services.branch_request_handler import (
    BranchRequestHandler,
    process_branch_request,
)


def example_1_property_translation():
    """Example 1: Translating property names from Bosnian to English."""
    print("=== Example 1: Property Translation ===\n")

    bosnian_properties = [
        "cilj",
        "zadatak",
        "prioritet",
        "rok",
        "opis",
        "status zadatka",
        "početni datum",
    ]

    print("Bosnian → English:")
    for prop in bosnian_properties:
        english = translate_to_english(prop)
        notion_name = NotionKeywordMapper.get_notion_property_name(english)
        print(f"  {prop:20} → {english:20} → {notion_name}")
    print()


def example_2_payload_translation():
    """Example 2: Translating a complete task payload."""
    print("=== Example 2: Complete Payload Translation ===\n")

    bosnian_payload = {
        "zadatak": "Implementacija API-ja",
        "prioritet": "visok",
        "rok": "2025-12-31",
        "opis": "Potrebno implementirati REST API za korisničke podatke",
        "status": "u tijeku",
        "veza s projektom": "project-123",
    }

    print("Original (Bosnian):")
    for key, value in bosnian_payload.items():
        print(f"  {key}: {value}")

    english_payload = translate_payload(bosnian_payload)

    print("\nTranslated (English):")
    for key, value in english_payload.items():
        print(f"  {key}: {value}")
    print()


def example_3_status_priority_translation():
    """Example 3: Translating status and priority values."""
    print("=== Example 3: Status & Priority Translation ===\n")

    mapper = NotionKeywordMapper()

    statuses = ["nije započet", "u tijeku", "završen", "blokiran"]
    priorities = ["nizak", "srednji", "visok"]

    print("Status values:")
    for status in statuses:
        translated = mapper.translate_status_value(status)
        print(f"  {status:15} → {translated}")

    print("\nPriority values:")
    for priority in priorities:
        translated = mapper.translate_priority_value(priority)
        print(f"  {priority:15} → {translated}")
    print()


def example_4_intent_detection():
    """Example 4: Detecting intent from prompts."""
    print("=== Example 4: Intent Detection ===\n")

    prompts = [
        "kreiraj cilj: Povećanje prihoda",
        "napravi zadatak: Implementacija",
        "create goal: Revenue Growth",
        "Grupni zadatak: Kreiraj cilj + taskove",
        "batch request: create multiple items",
    ]

    print("Intent detection:")
    for prompt in prompts:
        intent = NotionKeywordMapper.detect_intent(prompt)
        print(f"  '{prompt[:40]}...' → {intent}")
    print()


def example_5_branch_request_parsing():
    """Example 5: Parsing branch requests."""
    print("=== Example 5: Branch Request Parsing ===\n")

    requests = [
        "Grupni zadatak: Kreiraj 1 cilj + 5 taskova: Povećanje prihoda",
        "Branch request: Create 1 goal with 3 child goals and 10 tasks: Product Launch",
        "Kreiraj projekt sa 1 ciljem i 5 zadataka visok prioritet: Digital Transformation",
    ]

    for req in requests:
        print(f"Request: {req}\n")

        result = BranchRequestHandler.parse_branch_request(req)

        if result:
            print(f"  Type: {result['type']}")
            print(f"  Title: {result['main_title']}")
            print(f"  Counts: {result['counts']}")
            print(f"  Properties: {result['properties']}")
        else:
            print("  Not a branch request")
        print()


def example_6_building_operations():
    """Example 6: Building operations from branch request."""
    print("=== Example 6: Building Operations ===\n")

    branch_request = {
        "main_title": "Revenue Growth Q1 2025",
        "counts": {"goals": 1, "tasks": 3},
        "properties": {"priority": "High", "deadline": "2025-03-31"},
    }

    operations = BranchRequestHandler.build_branch_operations(branch_request)

    print(f"Created {len(operations)} operations:\n")

    for i, op in enumerate(operations, 1):
        print(f"Operation {i}:")
        print(f"  ID: {op['op_id']}")
        print(f"  Intent: {op['intent']}")
        print(f"  Type: {op['entity_type']}")
        print(f"  Payload: {op['payload']}")
        print()


def example_7_end_to_end_branch_request():
    """Example 7: End-to-end branch request processing."""
    print("=== Example 7: End-to-End Branch Request ===\n")

    prompt = "Grupni zadatak: Kreiraj 1 cilj + 5 taskova visok prioritet: Digitalna Transformacija"

    print(f"Prompt: {prompt}\n")

    result = process_branch_request(prompt)

    if result:
        print(f"Type: {result['type']}")
        print(f"Total Operations: {result['total_operations']}")
        print("\nParsed Request:")
        print(f"  Title: {result['parsed']['main_title']}")
        print(f"  Counts: {result['parsed']['counts']}")
        print(f"  Properties: {result['parsed']['properties']}")
        print("\nOperations created:")

        for i, op in enumerate(result["operations"][:3], 1):  # Show first 3
            print(f"  {i}. {op['intent']} - {op['payload'].get('title', 'N/A')}")

        if len(result["operations"]) > 3:
            print(f"  ... and {len(result['operations']) - 3} more")
    else:
        print("Could not process as branch request")
    print()


def example_8_mixed_language():
    """Example 8: Handling mixed language input."""
    print("=== Example 8: Mixed Language Handling ===\n")

    # Payload with mixed Bosnian and English
    mixed_payload = {
        "cilj": "Revenue Growth",  # Bosnian key, English value
        "priority": "visok",  # English key, Bosnian value
        "opis": "Strategic initiative",  # Bosnian key, English value
        "deadline": "2025-12-31",  # English key and value
    }

    print("Original (mixed):")
    for key, value in mixed_payload.items():
        print(f"  {key}: {value}")

    translated = translate_payload(mixed_payload)

    print("\nTranslated (normalized):")
    for key, value in translated.items():
        print(f"  {key}: {value}")
    print()


def example_9_notion_field_names():
    """Example 9: Getting Notion database field names."""
    print("=== Example 9: Notion Field Names ===\n")

    inputs = [
        ("cilj", "Bosnian"),
        ("goal", "English"),
        ("zadatak status", "Bosnian"),
        ("task_status", "English internal"),
        ("početni datum", "Bosnian"),
        ("start_date", "English internal"),
    ]

    print("Input → Notion Property Name:")
    for field, lang in inputs:
        notion_name = NotionKeywordMapper.normalize_field_name(field)
        print(f"  {field:20} ({lang:20}) → {notion_name}")
    print()


def example_10_practical_workflow():
    """Example 10: Practical workflow example."""
    print("=== Example 10: Practical Workflow ===\n")

    # User submits a Bosnian request
    user_request = """
    Grupni zadatak: Kreiraj projekt 'Digital Transformation Q1 2025'
    
    Sa sledećim stavkama:
    - 1 glavni cilj
    - 3 podciljeva
    - 10 taskova
    
    Prioritet: visok
    Rok: 2025-03-31
    Status: u tijeku
    """

    print("User Request (Bosnian):")
    print(user_request)
    print()

    # Detect if it's a branch request
    is_branch = is_batch_request(user_request)
    print(f"Is branch request: {is_branch}")

    # Parse the request
    parsed = BranchRequestHandler.parse_branch_request(user_request)

    if parsed:
        print("\nParsed successfully:")
        print(f"  Main Title: {parsed['main_title']}")
        print(f"  Entity Counts: {parsed['counts']}")
        print(f"  Properties: {parsed['properties']}")

        # Build operations
        operations = BranchRequestHandler.build_branch_operations(parsed)
        print(f"\nGenerated {len(operations)} operations")
        print("Ready for approval and execution!")
    print()


def run_all_examples():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("NOTION OPS BILINGUAL SUPPORT - PRACTICAL EXAMPLES")
    print("=" * 70 + "\n")

    example_1_property_translation()
    example_2_payload_translation()
    example_3_status_priority_translation()
    example_4_intent_detection()
    example_5_branch_request_parsing()
    example_6_building_operations()
    example_7_end_to_end_branch_request()
    example_8_mixed_language()
    example_9_notion_field_names()
    example_10_practical_workflow()

    print("=" * 70)
    print("All examples completed!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_all_examples()
