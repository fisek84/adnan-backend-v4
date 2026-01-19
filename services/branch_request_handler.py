"""
Branch Request Handler for Notion Ops Agent

Handles creation of grouped/batch requests where multiple related entities
(goals, tasks, KPIs) are created together with proper relationship linking.

Supports both Bosnian and English input.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

from services.notion_keyword_mapper import NotionKeywordMapper

logger = logging.getLogger(__name__)


# Internationalization labels
I18N_LABELS = {
    "child_goal_prefix": {
        "en": "Child Goal",
        "bs": "Podcilj",
    },
    "goal_prefix": {
        "en": "Goal",
        "bs": "Cilj",
    },
    "task_prefix": {
        "en": "Task",
        "bs": "Zadatak",
    },
    "project_prefix": {
        "en": "Project",
        "bs": "Projekt",
    },
}

# Regex patterns for title extraction
# Pattern to remove count information that appears before the actual title
# E.g., "1 cilj + 5 taskova Povećanje prihoda" -> "Povećanje prihoda"
TITLE_COUNT_PATTERN = (
    r'^\d+\s*'                           # Number at start (e.g., "1 ")
    r'(cilj|ciljeva|goal|goals)\s*'      # Goal keyword
    r'[\+\-]*\s*'                        # Optional + or - separator
    r'\d*\s*'                            # Optional second number
    r'(task|taskova|tasks|zadatak|zadataka)?\s*'  # Optional task keyword
)


class BranchRequestHandler:
    """
    Handles branch requests - grouped creation of related Notion entities.
    
    A branch request creates multiple related items in a single operation:
    - Goals with child goals
    - Tasks linked to goals
    - KPIs linked to goals/tasks
    - Projects with related goals and tasks
    """

    @staticmethod
    def parse_branch_request(prompt: str) -> Optional[Dict[str, Any]]:
        """
        Parse a branch request prompt into structured operations.
        
        Supports formats like:
        - "Grupni zadatak: Kreiraj cilj X sa 5 taskova"
        - "Branch request: Create goal Y with 3 child goals and 10 tasks"
        - "Napravi projekt Z sa ciljem i 5 zadataka"
        
        Args:
            prompt: User input prompt in Bosnian or English
            
        Returns:
            Structured branch request or None if not a branch request
        """
        if not prompt or not isinstance(prompt, str):
            return None
        
        text = prompt.strip()
        text_lower = text.lower()
        
        # Check if this is a branch request
        if not NotionKeywordMapper.is_batch_request(text):
            # Also check for alternative patterns
            alternative_patterns = [
                r"kreiraj.*\s+sa\s+\d+",  # "kreiraj cilj sa 5 taskova"
                r"napravi.*\s+sa\s+\d+",  # "napravi projekt sa 3 cilja"
                r"create.*with\s+\d+",    # "create goal with 5 tasks"
                r"\d+\s+(cilj|task|zadatak)",  # "1 cilj + 5 taskova"
            ]
            
            is_branch = any(re.search(pattern, text_lower) for pattern in alternative_patterns)
            if not is_branch:
                return None
        
        logger.info(f"Parsing branch request: {text[:100]}...")
        
        # Extract the main goal/project title
        main_title = BranchRequestHandler._extract_main_title(text)
        
        # Extract counts for different entity types
        counts = BranchRequestHandler._extract_entity_counts(text)
        
        # Extract additional properties
        properties = BranchRequestHandler._extract_properties(text)
        
        if not main_title and not counts:
            logger.warning("Could not parse branch request structure")
            return None
        
        return {
            "type": "branch_request",
            "main_title": main_title or "Untitled",
            "counts": counts,
            "properties": properties,
        }
    
    @staticmethod
    def _extract_main_title(text: str) -> Optional[str]:
        """Extract the main title/topic from the request."""
        # Try to find quoted text first
        quoted = re.search(r"['\"]([^'\"]+)['\"]", text)
        if quoted:
            return quoted.group(1).strip()
        
        # Try to find text after last colon (since there might be multiple)
        if ":" in text:
            # Split by colon and take the last part
            parts = text.split(":")
            title = parts[-1].strip()
            
            # Remove common prefixes
            for prefix in ["kreiraj", "napravi", "create", "make"]:
                if title.lower().startswith(prefix):
                    title = title[len(prefix):].strip()
            
            # Remove count patterns at the beginning (before title)
            # E.g., "1 cilj + 5 taskova Povećanje prihoda" -> "Povećanje prihoda"
            title = re.sub(TITLE_COUNT_PATTERN, '', title, flags=re.IGNORECASE)
            
            # Remove trailing count patterns
            title = re.sub(r'\s+sa\s+\d+.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+with\s+\d+.*$', '', title, flags=re.IGNORECASE)
            
            # Remove leading "sa" or "with"
            title = re.sub(r'^(sa|with)\s+', '', title, flags=re.IGNORECASE)
            
            if title and title.strip():
                return title.strip()
        
        return None
    
    @staticmethod
    def _extract_entity_counts(text: str) -> Dict[str, int]:
        """Extract counts for different entity types."""
        counts = {}
        text_lower = text.lower()
        
        # Goal patterns
        goal_patterns = [
            r"(\d+)\s*(cilj|ciljeva|goal|goals)",
            r"(jedan|one|1)\s*cilj",
        ]
        
        for pattern in goal_patterns:
            match = re.search(pattern, text_lower)
            if match:
                count_str = match.group(1)
                count = 1 if count_str in ("jedan", "one") else int(count_str)
                counts["goals"] = count
                break
        
        # Task patterns
        task_patterns = [
            r"(\d+)\s*(task|taskova|tasks|zadatak|zadatka)",
            r"(pet|five|5)\s*(task|zadatak)",
        ]
        
        for pattern in task_patterns:
            match = re.search(pattern, text_lower)
            if match:
                count_str = match.group(1)
                if count_str in ("pet", "five"):
                    count = 5
                else:
                    count = int(count_str)
                counts["tasks"] = count
                break
        
        # Child goal patterns
        child_goal_patterns = [
            r"(\d+)\s*(podcilj|podciljeva|child goal|sub goal)",
        ]
        
        for pattern in child_goal_patterns:
            match = re.search(pattern, text_lower)
            if match:
                counts["child_goals"] = int(match.group(1))
                break
        
        # Project patterns
        project_patterns = [
            r"(\d+)\s*(projekt|projekat|project)",
        ]
        
        for pattern in project_patterns:
            match = re.search(pattern, text_lower)
            if match:
                counts["projects"] = int(match.group(1))
                break
        
        # KPI patterns
        kpi_patterns = [
            r"(\d+)\s*kpi",
        ]
        
        for pattern in kpi_patterns:
            match = re.search(pattern, text_lower)
            if match:
                counts["kpis"] = int(match.group(1))
                break
        
        return counts
    
    @staticmethod
    def _extract_properties(text: str) -> Dict[str, Any]:
        """Extract additional properties from the request."""
        properties = {}
        text_lower = text.lower()
        
        # Priority patterns
        priority_patterns = [
            (r"visok\w*\s+prioritet", "High"),
            (r"high\s+priority", "High"),
            (r"srednji\s+prioritet", "Medium"),
            (r"medium\s+priority", "Medium"),
            (r"nizak\s+prioritet", "Low"),
            (r"low\s+priority", "Low"),
        ]
        
        for pattern, value in priority_patterns:
            if re.search(pattern, text_lower):
                properties["priority"] = value
                break
        
        # Status patterns
        status_patterns = [
            (r"u\s+tijeku|u\s+toku", "In Progress"),
            (r"in\s+progress", "In Progress"),
            (r"započet|zapocet", "In Progress"),
            (r"završen|zavrsen", "Completed"),
            (r"completed", "Completed"),
        ]
        
        for pattern, value in status_patterns:
            if re.search(pattern, text_lower):
                properties["status"] = value
                break
        
        # Deadline patterns (ISO format)
        deadline_pattern = r"(\d{4}-\d{2}-\d{2})"
        deadline_match = re.search(deadline_pattern, text)
        if deadline_match:
            properties["deadline"] = deadline_match.group(1)
        
        return properties
    
    @staticmethod
    def _detect_language(text: str) -> str:
        """
        Detect if the request is in Bosnian or English.
        
        Args:
            text: Request text
            
        Returns:
            'bs' for Bosnian, 'en' for English
        """
        text_lower = text.lower()
        
        # Bosnian indicators
        bosnian_keywords = ["cilj", "zadatak", "projekt", "prioritet", "kreiraj", "napravi"]
        english_keywords = ["goal", "task", "project", "priority", "create", "make"]
        
        bosnian_count = sum(1 for keyword in bosnian_keywords if keyword in text_lower)
        english_count = sum(1 for keyword in english_keywords if keyword in text_lower)
        
        return "bs" if bosnian_count > english_count else "en"
    
    @staticmethod
    def _get_label(label_key: str, lang: str = "en") -> str:
        """
        Get a localized label.
        
        Args:
            label_key: Key in I18N_LABELS
            lang: Language code ('en' or 'bs')
            
        Returns:
            Localized label
        """
        return I18N_LABELS.get(label_key, {}).get(lang, I18N_LABELS.get(label_key, {}).get("en", ""))
    
    @staticmethod
    def build_branch_operations(
        branch_request: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Build a list of operations from a parsed branch request.
        
        Args:
            branch_request: Parsed branch request structure
            
        Returns:
            List of operation dictionaries ready for execution
        """
        operations = []
        main_title = branch_request.get("main_title", "Untitled")
        counts = branch_request.get("counts", {})
        properties = branch_request.get("properties", {})
        
        # Detect language for proper labels
        lang = BranchRequestHandler._detect_language(main_title)
        
        # Track IDs for linking
        goal_ids = []
        project_ids = []
        
        # Create main goal(s)
        num_goals = counts.get("goals", 0)
        if num_goals > 0:
            for i in range(num_goals):
                op_id = f"goal_{uuid4().hex[:8]}"
                goal_ids.append(op_id)
                
                goal_payload = {
                    "title": main_title if num_goals == 1 else f"{main_title} - {BranchRequestHandler._get_label('goal_prefix', lang)} {i+1}",
                    **properties,
                }
                
                operations.append({
                    "op_id": op_id,
                    "intent": "create_goal",
                    "entity_type": "goal",
                    "payload": goal_payload,
                })
        
        # Create child goals
        num_child_goals = counts.get("child_goals", 0)
        if num_child_goals > 0 and goal_ids:
            parent_goal_id = goal_ids[0]  # Link to first main goal
            
            for i in range(num_child_goals):
                op_id = f"child_goal_{uuid4().hex[:8]}"
                
                child_payload = {
                    "title": f"{main_title} - {BranchRequestHandler._get_label('child_goal_prefix', lang)} {i+1}",
                    "parent_goal_id": f"${parent_goal_id}",  # Reference to parent
                    **properties,
                }
                
                operations.append({
                    "op_id": op_id,
                    "intent": "create_goal",
                    "entity_type": "child_goal",
                    "payload": child_payload,
                })
        
        # Create projects
        num_projects = counts.get("projects", 0)
        if num_projects > 0:
            for i in range(num_projects):
                op_id = f"project_{uuid4().hex[:8]}"
                project_ids.append(op_id)
                
                project_payload = {
                    "title": main_title if num_projects == 1 else f"{main_title} - {BranchRequestHandler._get_label('project_prefix', lang)} {i+1}",
                    **properties,
                }
                
                # Link to goal if available
                if goal_ids:
                    project_payload["primary_goal_id"] = f"${goal_ids[0]}"
                
                operations.append({
                    "op_id": op_id,
                    "intent": "create_project",
                    "entity_type": "project",
                    "payload": project_payload,
                })
        
        # Create tasks
        num_tasks = counts.get("tasks", 0)
        if num_tasks > 0:
            for i in range(num_tasks):
                op_id = f"task_{uuid4().hex[:8]}"
                
                task_payload = {
                    "title": f"{BranchRequestHandler._get_label('task_prefix', lang)} {i+1}: {main_title}",
                    **properties,
                }
                
                # Link to goal if available
                if goal_ids:
                    task_payload["goal_id"] = f"${goal_ids[0]}"
                
                # Link to project if available
                if project_ids:
                    task_payload["project_id"] = f"${project_ids[0]}"
                
                operations.append({
                    "op_id": op_id,
                    "intent": "create_task",
                    "entity_type": "task",
                    "payload": task_payload,
                })
        
        logger.info(f"Built {len(operations)} operations from branch request")
        
        return operations
    
    @staticmethod
    def process_branch_request(prompt: str) -> Optional[Dict[str, Any]]:
        """
        End-to-end processing of a branch request.
        
        Args:
            prompt: User prompt
            
        Returns:
            Dict with operations list and metadata, or None if not a branch request
        """
        # Parse the request
        parsed = BranchRequestHandler.parse_branch_request(prompt)
        if not parsed:
            return None
        
        # Build operations
        operations = BranchRequestHandler.build_branch_operations(parsed)
        
        return {
            "type": "branch_request",
            "parsed": parsed,
            "operations": operations,
            "total_operations": len(operations),
        }


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def is_branch_request(prompt: str) -> bool:
    """Check if a prompt is a branch request."""
    parsed = BranchRequestHandler.parse_branch_request(prompt)
    return parsed is not None


def process_branch_request(prompt: str) -> Optional[Dict[str, Any]]:
    """Process a branch request and return operations."""
    return BranchRequestHandler.process_branch_request(prompt)
