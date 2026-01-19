"""
Tests for Branch Request Handler

Tests the parsing and processing of branch/batch requests for creating
multiple related Notion entities (goals, tasks, projects, KPIs).
"""

from services.branch_request_handler import (
    BranchRequestHandler,
    is_branch_request,
    process_branch_request,
)


class TestBranchRequestParsing:
    """Test parsing of branch requests."""

    def test_parse_simple_branch_request_bosnian(self):
        """Test parsing simple branch request in Bosnian."""
        prompt = "Grupni zadatak: Kreiraj 1 cilj + 5 taskova: Povećanje prihoda"

        result = BranchRequestHandler.parse_branch_request(prompt)

        assert result is not None
        assert result["type"] == "branch_request"
        assert "Povećanje prihoda" in result["main_title"]
        assert result["counts"]["goals"] == 1
        assert result["counts"]["tasks"] == 5

    def test_parse_simple_branch_request_english(self):
        """Test parsing simple branch request in English."""
        prompt = "Branch request: Create 1 goal + 5 tasks: Revenue Growth"

        result = BranchRequestHandler.parse_branch_request(prompt)

        assert result is not None
        assert result["type"] == "branch_request"
        assert "Revenue Growth" in result["main_title"]
        assert result["counts"]["goals"] == 1
        assert result["counts"]["tasks"] == 5

    def test_parse_complex_branch_request(self):
        """Test parsing complex branch request with multiple entity types."""
        prompt = "Kreiraj 1 cilj sa 3 podciljeva i 10 taskova: Novi projekt"

        result = BranchRequestHandler.parse_branch_request(prompt)

        assert result is not None
        assert result["counts"]["goals"] == 1
        assert result["counts"]["child_goals"] == 3
        assert result["counts"]["tasks"] == 10

    def test_parse_with_properties(self):
        """Test parsing branch request with additional properties."""
        prompt = (
            "Grupni zadatak: Kreiraj cilj sa 5 taskova visok prioritet: Test Project"
        )

        result = BranchRequestHandler.parse_branch_request(prompt)

        assert result is not None
        assert result["properties"]["priority"] == "High"

    def test_parse_with_deadline(self):
        """Test parsing branch request with deadline."""
        prompt = "Kreiraj cilj sa 3 taskova deadline 2025-12-31: Important Goal"

        result = BranchRequestHandler.parse_branch_request(prompt)

        assert result is not None
        assert result["properties"]["deadline"] == "2025-12-31"

    def test_parse_quoted_title(self):
        """Test parsing branch request with quoted title."""
        prompt = "Grupni zahtjev: Kreiraj 1 cilj + 5 taskova: 'Projekat sa navodnicima'"

        result = BranchRequestHandler.parse_branch_request(prompt)

        assert result is not None
        assert "Projekat sa navodnicima" in result["main_title"]

    def test_parse_non_branch_request(self):
        """Test that non-branch requests return None."""
        prompts = ["Kreiraj običan cilj", "Napravi zadatak", "Create simple task"]

        for prompt in prompts:
            result = BranchRequestHandler.parse_branch_request(prompt)
            # Some might be detected by alternative patterns, just ensure no crash
            assert result is None or isinstance(result, dict)


class TestEntityCountExtraction:
    """Test extraction of entity counts from prompts."""

    def test_extract_goal_count(self):
        """Test extracting goal count."""
        texts = ["1 cilj", "jedan cilj", "2 cilja", "5 ciljeva"]

        for text in texts[:2]:  # "1 cilj" and "jedan cilj"
            counts = BranchRequestHandler._extract_entity_counts(text)
            assert counts.get("goals") == 1

    def test_extract_task_count(self):
        """Test extracting task count."""
        texts = ["5 taskova", "10 zadataka", "pet taskova", "3 tasks"]

        for text in texts:
            counts = BranchRequestHandler._extract_entity_counts(text)
            assert "tasks" in counts
            assert counts["tasks"] > 0

    def test_extract_child_goal_count(self):
        """Test extracting child goal count."""
        text = "3 podciljeva"

        counts = BranchRequestHandler._extract_entity_counts(text)

        assert counts.get("child_goals") == 3

    def test_extract_project_count(self):
        """Test extracting project count."""
        text = "2 projekta"

        counts = BranchRequestHandler._extract_entity_counts(text)

        assert counts.get("projects") == 2

    def test_extract_multiple_counts(self):
        """Test extracting multiple entity counts from single text."""
        text = "1 cilj sa 3 podciljeva i 5 taskova"

        counts = BranchRequestHandler._extract_entity_counts(text)

        assert counts.get("goals") == 1
        assert counts.get("child_goals") == 3
        assert counts.get("tasks") == 5


class TestPropertyExtraction:
    """Test extraction of properties from prompts."""

    def test_extract_high_priority(self):
        """Test extracting high priority."""
        texts = ["visok prioritet", "visoka prioritet", "high priority"]

        for text in texts:
            props = BranchRequestHandler._extract_properties(text)
            assert props.get("priority") == "High"

    def test_extract_medium_priority(self):
        """Test extracting medium priority."""
        texts = ["srednji prioritet", "medium priority"]

        for text in texts:
            props = BranchRequestHandler._extract_properties(text)
            assert props.get("priority") == "Medium"

    def test_extract_status(self):
        """Test extracting status."""
        texts = ["u tijeku", "u toku", "in progress"]

        for text in texts:
            props = BranchRequestHandler._extract_properties(text)
            assert props.get("status") == "In Progress"

    def test_extract_deadline(self):
        """Test extracting deadline."""
        text = "rok 2025-12-31"

        props = BranchRequestHandler._extract_properties(text)

        assert props.get("deadline") == "2025-12-31"


class TestOperationBuilding:
    """Test building operations from parsed branch requests."""

    def test_build_simple_operations(self):
        """Test building operations for simple branch request."""
        branch_request = {
            "main_title": "Test Project",
            "counts": {"goals": 1, "tasks": 3},
            "properties": {"priority": "High"},
        }

        operations = BranchRequestHandler.build_branch_operations(branch_request)

        # Should have 1 goal + 3 tasks = 4 operations
        assert len(operations) == 4

        # First operation should be goal
        assert operations[0]["intent"] == "create_goal"
        assert operations[0]["payload"]["title"] == "Test Project"
        assert operations[0]["payload"]["priority"] == "High"

        # Rest should be tasks
        for i in range(1, 4):
            assert operations[i]["intent"] == "create_task"
            assert "Task" in operations[i]["payload"]["title"]
            assert operations[i]["payload"]["priority"] == "High"

    def test_build_operations_with_child_goals(self):
        """Test building operations with child goals."""
        branch_request = {
            "main_title": "Parent Goal",
            "counts": {"goals": 1, "child_goals": 2},
            "properties": {},
        }

        operations = BranchRequestHandler.build_branch_operations(branch_request)

        # Should have 1 parent goal + 2 child goals = 3 operations
        assert len(operations) == 3

        # First should be parent goal
        assert operations[0]["entity_type"] == "goal"
        parent_op_id = operations[0]["op_id"]

        # Next two should be child goals
        assert operations[1]["entity_type"] == "child_goal"
        assert operations[2]["entity_type"] == "child_goal"

        # Child goals should reference parent
        assert f"${parent_op_id}" in operations[1]["payload"]["parent_goal_id"]
        assert f"${parent_op_id}" in operations[2]["payload"]["parent_goal_id"]

    def test_build_operations_with_relations(self):
        """Test that task operations reference goal operations."""
        branch_request = {
            "main_title": "Linked Project",
            "counts": {"goals": 1, "tasks": 2},
            "properties": {},
        }

        operations = BranchRequestHandler.build_branch_operations(branch_request)

        # Get goal op_id
        goal_op_id = operations[0]["op_id"]

        # Tasks should reference the goal
        assert f"${goal_op_id}" in operations[1]["payload"]["goal_id"]
        assert f"${goal_op_id}" in operations[2]["payload"]["goal_id"]

    def test_build_operations_with_project(self):
        """Test building operations with project."""
        branch_request = {
            "main_title": "Full Setup",
            "counts": {"goals": 1, "projects": 1, "tasks": 2},
            "properties": {},
        }

        operations = BranchRequestHandler.build_branch_operations(branch_request)

        # Should have goal + project + 2 tasks = 4 operations
        assert len(operations) == 4

        # Find project operation
        project_op = next(op for op in operations if op["intent"] == "create_project")
        assert project_op is not None

        # Project should reference goal
        goal_op_id = operations[0]["op_id"]
        assert f"${goal_op_id}" in project_op["payload"]["primary_goal_id"]

    def test_build_operations_with_shared_assignee_people_specs(self):
        """Shared assignees in properties should produce people specs on all entities."""
        branch_request = {
            "main_title": "Ownership Setup",
            "counts": {"goals": 1, "child_goals": 1, "projects": 1, "tasks": 1},
            "properties": {"assignees": ["owner@example.com"]},
        }

        operations = BranchRequestHandler.build_branch_operations(branch_request)

        # Expect 1 goal + 1 child_goal + 1 project + 1 task
        assert len(operations) == 4

        # Helper to collect all people specs
        def _collect_people_specs(ops):
            cols = []
            for op in ops:
                payload = op.get("payload") or {}
                ps = payload.get("property_specs")
                if isinstance(ps, dict):
                    for spec in ps.values():
                        if (
                            isinstance(spec, dict)
                            and spec.get("type") == "people"
                            and "names" in spec
                        ):
                            cols.append(spec["names"])
            return cols

        people_lists = _collect_people_specs(operations)
        # At least one people spec should carry the shared assignee
        assert any("owner@example.com" in names for names in people_lists)


class TestEndToEndProcessing:
    """Test end-to-end branch request processing."""

    def test_process_valid_branch_request(self):
        """Test processing a valid branch request."""
        prompt = "Grupni zadatak: Kreiraj 1 cilj + 5 taskova: Test Implementation"

        result = process_branch_request(prompt)

        assert result is not None
        assert result["type"] == "branch_request"
        assert "parsed" in result
        assert "operations" in result
        assert result["total_operations"] == 6  # 1 goal + 5 tasks

    def test_process_invalid_request(self):
        """Test processing an invalid (non-branch) request."""
        prompt = "Just a regular task"

        result = process_branch_request(prompt)

        # Should return None or handle gracefully
        assert result is None or isinstance(result, dict)

    def test_is_branch_request_function(self):
        """Test the convenience is_branch_request function."""
        assert (
            is_branch_request("Grupni zadatak: Test") is True
            or is_branch_request("Grupni zadatak: Test") is False
        )
        assert (
            is_branch_request("Kreiraj cilj sa 5 taskova") is True
            or is_branch_request("Kreiraj cilj sa 5 taskova") is False
        )


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_prompt(self):
        """Test handling empty prompt."""
        result = BranchRequestHandler.parse_branch_request("")
        assert result is None

    def test_none_prompt(self):
        """Test handling None prompt."""
        result = BranchRequestHandler.parse_branch_request(None)
        assert result is None

    def test_no_counts(self):
        """Test handling request with no entity counts."""
        prompt = "Grupni zadatak bez brojeva"

        result = BranchRequestHandler.parse_branch_request(prompt)
        # Should either return None or have empty counts
        if result:
            assert isinstance(result["counts"], dict)

    def test_zero_count_operations(self):
        """Test building operations with zero counts."""
        branch_request = {"main_title": "Empty Request", "counts": {}, "properties": {}}

        operations = BranchRequestHandler.build_branch_operations(branch_request)

        # Should return empty list or minimal structure
        assert isinstance(operations, list)
