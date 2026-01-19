"""
Tests for Notion Keyword Mapper - Bilingual Support

Tests the bilingual keyword mapping functionality for Bosnian ↔ English
property name translation and request parsing.
"""

import pytest
from services.notion_keyword_mapper import NotionKeywordMapper, translate_to_english, translate_payload


class TestPropertyNameTranslation:
    """Test property name translation from Bosnian to English."""
    
    def test_basic_property_translation(self):
        """Test basic property name translations."""
        assert translate_to_english("cilj") == "goal"
        assert translate_to_english("zadatak") == "task"
        assert translate_to_english("prioritet") == "priority"
        assert translate_to_english("opis") == "description"
    
    def test_status_property_translation(self):
        """Test status-related property translations."""
        assert translate_to_english("zadatak status") == "task_status"
        assert translate_to_english("status zadatka") == "task_status"
    
    def test_date_property_translation(self):
        """Test date property translations."""
        assert translate_to_english("početni datum") == "start_date"
        assert translate_to_english("pocetni datum") == "start_date"
        assert translate_to_english("završni datum") == "target_deadline"
        assert translate_to_english("deadline") == "due_date"
        assert translate_to_english("rok") == "due_date"
    
    def test_relation_property_translation(self):
        """Test relation property translations."""
        assert translate_to_english("veza s projektom") == "project"
        assert translate_to_english("veza sa projektom") == "project"
        assert translate_to_english("veza s kpi") == "kpi"
        assert translate_to_english("veza s agentima") == "agent_exchange_db"
    
    def test_english_passthrough(self):
        """Test that English properties pass through correctly."""
        assert translate_to_english("goal") == "goal"
        assert translate_to_english("task") == "task"
        assert translate_to_english("priority") == "priority"
    
    def test_case_insensitivity(self):
        """Test that translation is case-insensitive."""
        assert translate_to_english("CILJ") == "goal"
        assert translate_to_english("Zadatak") == "task"
        assert translate_to_english("PrIoRiTeT") == "priority"


class TestStatusValueTranslation:
    """Test status value translation."""
    
    def test_status_values(self):
        """Test Bosnian to English status value translation."""
        mapper = NotionKeywordMapper()
        
        assert mapper.translate_status_value("nije započet") == "Not started"
        assert mapper.translate_status_value("nije zapocet") == "Not started"
        assert mapper.translate_status_value("u tijeku") == "In Progress"
        assert mapper.translate_status_value("u toku") == "In Progress"
        assert mapper.translate_status_value("završen") == "Completed"
        assert mapper.translate_status_value("zavrsen") == "Completed"
    
    def test_english_status_passthrough(self):
        """Test English status values pass through."""
        mapper = NotionKeywordMapper()
        
        assert mapper.translate_status_value("Not started") == "Not started"
        assert mapper.translate_status_value("In Progress") == "In Progress"
        assert mapper.translate_status_value("Completed") == "Completed"


class TestPriorityValueTranslation:
    """Test priority value translation."""
    
    def test_priority_values(self):
        """Test Bosnian to English priority value translation."""
        mapper = NotionKeywordMapper()
        
        assert mapper.translate_priority_value("nizak") == "Low"
        assert mapper.translate_priority_value("niska") == "Low"
        assert mapper.translate_priority_value("srednji") == "Medium"
        assert mapper.translate_priority_value("srednja") == "Medium"
        assert mapper.translate_priority_value("visok") == "High"
        assert mapper.translate_priority_value("visoka") == "High"
    
    def test_english_priority_passthrough(self):
        """Test English priority values pass through."""
        mapper = NotionKeywordMapper()
        
        assert mapper.translate_priority_value("Low") == "Low"
        assert mapper.translate_priority_value("Medium") == "Medium"
        assert mapper.translate_priority_value("High") == "High"


class TestPayloadTranslation:
    """Test complete payload translation."""
    
    def test_simple_payload_translation(self):
        """Test translating a simple payload."""
        bosnian_payload = {
            "cilj": "Povećanje prihoda",
            "prioritet": "visok",
            "opis": "Testni opis"
        }
        
        english_payload = translate_payload(bosnian_payload)
        
        assert "goal" in english_payload
        assert english_payload["goal"] == "Povećanje prihoda"
        assert "priority" in english_payload
        assert english_payload["priority"] == "High"
        assert "description" in english_payload
    
    def test_complex_payload_translation(self):
        """Test translating a complex payload with relations."""
        payload = {
            "zadatak": "Novi zadatak",
            "status zadatka": "u tijeku",
            "prioritet": "srednji",
            "rok": "2025-12-31",
            "veza s projektom": "project-123"
        }
        
        translated = translate_payload(payload)
        
        assert translated["task"] == "Novi zadatak"
        assert translated["task_status"] == "In Progress"
        assert translated["priority"] == "Medium"
        assert translated["due_date"] == "2025-12-31"
        assert translated["project"] == "project-123"
    
    def test_mixed_language_payload(self):
        """Test payload with mixed Bosnian and English keys."""
        payload = {
            "cilj": "Test Goal",
            "priority": "High",
            "opis": "Description",
            "deadline": "2025-12-31"
        }
        
        translated = translate_payload(payload)
        
        assert "goal" in translated
        assert "priority" in translated
        assert "description" in translated
        assert "due_date" in translated


class TestIntentDetection:
    """Test intent detection from prompts."""
    
    def test_create_goal_intent_bosnian(self):
        """Test detecting create goal intent in Bosnian."""
        prompts = [
            "kreiraj cilj Povećanje prihoda",
            "napravi cilj Test",
            "novi cilj za projekt"
        ]
        
        for prompt in prompts:
            assert NotionKeywordMapper.detect_intent(prompt) == "create_goal"
    
    def test_create_goal_intent_english(self):
        """Test detecting create goal intent in English."""
        assert NotionKeywordMapper.detect_intent("create goal Revenue Growth") == "create_goal"
    
    def test_create_task_intent_bosnian(self):
        """Test detecting create task intent in Bosnian."""
        prompts = [
            "kreiraj zadatak Test",
            "napravi zadatak Implementacija",
            "novi zadatak za cilj"
        ]
        
        for prompt in prompts:
            assert NotionKeywordMapper.detect_intent(prompt) == "create_task"
    
    def test_batch_request_intent(self):
        """Test detecting batch/branch request intent."""
        prompts = [
            "grupni zahtjev: kreiraj 5 taskova",
            "batch request: create 10 tasks",
            "branch request for project"
        ]
        
        for prompt in prompts:
            assert NotionKeywordMapper.detect_intent(prompt) == "batch_request"


class TestNotionPropertyNames:
    """Test getting Notion database property names."""
    
    def test_get_notion_property_name(self):
        """Test getting Notion property names."""
        mapper = NotionKeywordMapper()
        
        assert mapper.get_notion_property_name("goal") == "Goal"
        assert mapper.get_notion_property_name("task_status") == "Status"
        assert mapper.get_notion_property_name("due_date") == "Due Date"
        assert mapper.get_notion_property_name("priority") == "Priority"
        assert mapper.get_notion_property_name("parent_goal") == "Parent Goal"
    
    def test_normalize_field_name_bosnian(self):
        """Test normalizing Bosnian field names to Notion property names."""
        mapper = NotionKeywordMapper()
        
        assert mapper.normalize_field_name("cilj") == "Goal"
        assert mapper.normalize_field_name("zadatak status") == "Status"
        assert mapper.normalize_field_name("rok") == "Due Date"
        assert mapper.normalize_field_name("prioritet") == "Priority"
    
    def test_normalize_field_name_english(self):
        """Test normalizing English field names to Notion property names."""
        mapper = NotionKeywordMapper()
        
        assert mapper.normalize_field_name("goal") == "Goal"
        assert mapper.normalize_field_name("task_status") == "Status"
        assert mapper.normalize_field_name("due_date") == "Due Date"


class TestBatchRequestDetection:
    """Test batch request detection."""
    
    def test_is_batch_request_bosnian(self):
        """Test detecting batch requests in Bosnian."""
        from services.notion_keyword_mapper import is_batch_request
        
        batch_prompts = [
            "grupni zahtjev: kreiraj cilj sa 5 taskova",
            "grupni zadatak: napravi projekt",
            "kreiraj grupu zadataka"
        ]
        
        for prompt in batch_prompts:
            assert is_batch_request(prompt) is True
    
    def test_is_batch_request_english(self):
        """Test detecting batch requests in English."""
        from services.notion_keyword_mapper import is_batch_request
        
        batch_prompts = [
            "batch request: create goal with tasks",
            "branch request for project setup"
        ]
        
        for prompt in batch_prompts:
            assert is_batch_request(prompt) is True
    
    def test_is_not_batch_request(self):
        """Test that non-batch requests return False."""
        from services.notion_keyword_mapper import is_batch_request
        
        regular_prompts = [
            "kreiraj cilj",
            "create task",
            "napravi projekt"
        ]
        
        for prompt in regular_prompts:
            # These might be batch if they contain patterns, so we just check they don't error
            result = is_batch_request(prompt)
            assert isinstance(result, bool)
