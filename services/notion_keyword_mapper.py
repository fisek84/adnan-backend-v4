"""
Notion Keyword Mapper - Bilingual Property Mapping (Bosnian ↔ English)

This module provides comprehensive keyword mapping between Bosnian and English
for Notion database properties, enabling the Notion Ops agent to process
requests in both languages seamlessly.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


class NotionKeywordMapper:
    """
    Canonical bilingual keyword mapper for Notion properties.

    Maps Bosnian property names to their English Notion equivalents
    as defined in the problem statement.
    """

    # ============================================================
    # BOSNIAN → ENGLISH PROPERTY MAPPINGS
    # ============================================================

    PROPERTY_MAPPINGS = {
        # Core Goal/Task Properties
        "cilj": "goal",
        "ciljevi": "goals",
        "podcilj": "child_goal",
        "podciljevi": "child_goals",
        "zadatak": "task",
        "zadaci": "tasks",
        # Status & Progress
        "zadatak status": "task_status",
        "status zadatka": "task_status",
        "prioritet": "priority",
        "deadline": "due_date",
        "rok": "due_date",
        "krajnji rok": "due_date",
        "napredak": "progress",
        "progres": "progress",
        # Descriptive Fields
        "opis": "description",
        "deskripcija": "description",
        # Relations
        "agent": "ai_agent",
        "ai agent": "ai_agent",
        "veza s projektom": "project",
        "veza sa projektom": "project",
        "projekat": "project",
        "projekt": "project",
        "veza s kpi": "kpi",
        "veza sa kpi": "kpi",
        "veza s agentima": "agent_exchange_db",
        "veza sa agentima": "agent_exchange_db",
        "agent exchange db": "agent_exchange_db",
        # Dates
        "početni datum": "start_date",
        "pocetni datum": "start_date",
        "datum početka": "start_date",
        "datum pocetka": "start_date",
        "završni datum": "target_deadline",
        "zavrsni datum": "target_deadline",
        "datum završetka": "target_deadline",
        "datum zavrsetka": "target_deadline",
        # Related Items
        "povezani zadaci": "related_tasks",
        "povezani zadatak": "related_tasks",
        "kategorija": "category",
        "završeno": "is_completed",
        "zavrseno": "is_completed",
        "je završeno": "is_completed",
        "je zavrseno": "is_completed",
        # Tags & Notes
        "oznake": "tags",
        "tagovi": "tags",
        "komentari": "agent_notes",
        "bilješke": "agent_notes",
        "biljeske": "agent_notes",
        "komentari i bilješke": "agent_notes",
        "komentari i biljeske": "agent_notes",
        # Common Fields (normalized)
        "naziv": "name",
        "ime": "name",
        "naslov": "name",
        "title": "name",
    }

    # ============================================================
    # NOTION PROPERTY NAME MAPPINGS (for Notion API)
    # ============================================================

    # Maps internal names to actual Notion database property names
    NOTION_PROPERTY_NAMES = {
        "goal": "Goal",
        "child_goal": "Child Goal",
        "task": "Task",
        "task_status": "Status",
        "priority": "Priority",
        "due_date": "Due Date",
        "deadline": "Deadline",
        "progress": "Progress",
        "description": "Description",
        "ai_agent": "AI Agent",
        "project": "Project",
        "kpi": "KPI",
        "agent_exchange_db": "Agent Exchange DB",
        "status": "Status",
        "start_date": "Start Date",
        "target_deadline": "Target Deadline",
        "related_tasks": "Related Tasks",
        "category": "Category",
        "is_completed": "Is Completed?",
        "tags": "Tags",
        "agent_notes": "Agent Notes",
        "name": "Name",
        "parent_goal": "Parent Goal",
        "child_goals": "Child Goals",
    }

    # ============================================================
    # REVERSE MAPPINGS (for display purposes)
    # ============================================================

    @classmethod
    def get_english_mappings(cls) -> Dict[str, str]:
        """Get English to Bosnian reverse mapping for display."""
        reverse = {}
        for bosnian, english in cls.PROPERTY_MAPPINGS.items():
            if english not in reverse:  # Keep first mapping
                reverse[english] = bosnian
        return reverse

    # ============================================================
    # KEYWORD RECOGNITION PATTERNS
    # ============================================================

    # Bosnian keywords for identifying request types
    INTENT_KEYWORDS = {
        "create_goal": [
            "kreiraj cilj",
            "napravi cilj",
            "novi cilj",
            "dodaj cilj",
            "create goal",
        ],
        "create_task": [
            "kreiraj zadatak",
            "napravi zadatak",
            "novi zadatak",
            "dodaj zadatak",
            "create task",
        ],
        "create_project": [
            "kreiraj projekt",
            "napravi projekt",
            "novi projekt",
            "dodaj projekt",
            "create project",
        ],
        "batch_request": [
            "grupni zahtjev",
            "grupni zahtjevi",
            "grupni zadatak",
            "batch request",
            "branch request",
            "kreiraj grupu",
            "napravi grupu",
            # Also detect patterns with counts
            r"\d+\s*(cilj|ciljeva|goal|goals).*\d+\s*(task|taskova|zadatak|zadataka)",
            r"cilj\s+sa\s+\d+",
            r"goal\s+with\s+\d+",
            r"\btask\s*\d+\s*[:\.)-]",
            r"\bzadatak\s*\d+\s*[:\.)-]",
        ],
    }

    # Status value mappings (Bosnian → English)
    STATUS_VALUES = {
        "nije započet": "Not started",
        "nije zapocet": "Not started",
        "u tijeku": "In Progress",
        "u toku": "In Progress",
        "završen": "Completed",
        "zavrsen": "Completed",
        "blokiran": "Blocked",
        "pauzirano": "Paused",
        "otkazano": "Cancelled",
        "otkazan": "Cancelled",
    }

    # Priority value mappings (Bosnian → English)
    PRIORITY_VALUES = {
        "nizak": "Low",
        "niska": "Low",
        "srednji": "Medium",
        "srednja": "Medium",
        "visok": "High",
        "visoka": "High",
        "kritičan": "Critical",
        "kriticna": "Critical",
    }

    # ============================================================
    # TRANSLATION METHODS
    # ============================================================

    @classmethod
    def translate_property_name(cls, property_name: str) -> str:
        """
        Translate a property name from Bosnian to English internal name.

        Args:
            property_name: Property name in Bosnian or English

        Returns:
            Normalized English internal property name
        """
        normalized = property_name.lower().strip()

        # Check direct mapping
        if normalized in cls.PROPERTY_MAPPINGS:
            return cls.PROPERTY_MAPPINGS[normalized]

        # Already in English format
        return normalized.replace(" ", "_")

    @classmethod
    def get_notion_property_name(cls, internal_name: str) -> str:
        """
        Get the actual Notion database property name for an internal name.

        Args:
            internal_name: Internal property name (e.g., 'due_date')

        Returns:
            Notion property name (e.g., 'Due Date')
        """
        # Try direct lookup
        if internal_name in cls.NOTION_PROPERTY_NAMES:
            return cls.NOTION_PROPERTY_NAMES[internal_name]

        # Try translating first
        translated = cls.translate_property_name(internal_name)
        if translated in cls.NOTION_PROPERTY_NAMES:
            return cls.NOTION_PROPERTY_NAMES[translated]

        # Fallback: capitalize words
        return " ".join(word.capitalize() for word in internal_name.split("_"))

    @classmethod
    def translate_status_value(cls, status: str) -> str:
        """
        Translate status value from Bosnian to English.

        Args:
            status: Status value in Bosnian or English

        Returns:
            English status value
        """
        normalized = status.lower().strip()
        return cls.STATUS_VALUES.get(normalized, status)

    @classmethod
    def translate_priority_value(cls, priority: str) -> str:
        """
        Translate priority value from Bosnian to English.

        Args:
            priority: Priority value in Bosnian or English

        Returns:
            English priority value
        """
        normalized = priority.lower().strip()
        return cls.PRIORITY_VALUES.get(normalized, priority)

    @classmethod
    def translate_payload(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Translate an entire payload from Bosnian to English.

        Args:
            payload: Dictionary with potentially Bosnian keys and values

        Returns:
            Dictionary with English keys and translated values
        """
        translated = {}

        for key, value in payload.items():
            # Translate the key
            english_key = cls.translate_property_name(key)

            # Translate value if it's a status or priority
            if isinstance(value, str):
                if english_key in ("status", "task_status"):
                    value = cls.translate_status_value(value)
                elif english_key == "priority":
                    value = cls.translate_priority_value(value)

            translated[english_key] = value

        return translated

    @classmethod
    def detect_intent(cls, text: str) -> Optional[str]:
        """
        Detect the intent from a text prompt (supports both languages).

        Args:
            text: User prompt in Bosnian or English

        Returns:
            Intent identifier or None if not detected
        """
        text_lower = text.lower()

        # Check batch_request first as it's more specific
        intent_order = ["batch_request", "create_goal", "create_task", "create_project"]

        for intent in intent_order:
            keywords = cls.INTENT_KEYWORDS.get(intent, [])
            for keyword in keywords:
                # Check if keyword is a regex pattern
                if keyword.startswith(r"\d") or "\\" in keyword:
                    # It's a regex pattern
                    if re.search(keyword, text_lower):
                        return intent
                else:
                    # It's a simple string
                    if keyword in text_lower:
                        return intent

        return None

    @classmethod
    def is_batch_request(cls, text: str) -> bool:
        """
        Check if the text represents a batch/branch request.

        Args:
            text: User prompt

        Returns:
            True if this is a batch request
        """
        t = (text or "").lower()

        # Heuristika: ako u istom inputu ima i (goal/cilj) i (task/zadatak), to je GROUP/BATCH.
        if (("task" in t) or ("zad" in t)) and (("goal" in t) or ("cilj" in t)):
            return True

        return cls.detect_intent(text) == "batch_request"

    @classmethod
    def normalize_field_name(cls, field_name: str) -> str:
        """
        Normalize a field name to its canonical Notion property name.

        This handles both Bosnian and English inputs and returns
        the exact property name as it appears in Notion.

        Args:
            field_name: Field name in any supported format

        Returns:
            Canonical Notion property name
        """
        # First translate to internal name
        internal = cls.translate_property_name(field_name)

        # Then get the Notion property name
        return cls.get_notion_property_name(internal)


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================


def translate_to_english(bosnian_text: str) -> str:
    """Translate Bosnian property name to English."""
    return NotionKeywordMapper.translate_property_name(bosnian_text)


def translate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Translate payload from Bosnian to English."""
    return NotionKeywordMapper.translate_payload(payload)


def get_notion_field_name(field: str) -> str:
    """Get the Notion database field name for a given field."""
    return NotionKeywordMapper.normalize_field_name(field)


def is_batch_request(text: str) -> bool:
    """Check if text represents a batch/branch request."""
    return NotionKeywordMapper.is_batch_request(text)
