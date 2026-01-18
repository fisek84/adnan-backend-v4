# Notion Operations - Complete Guide

## Overview

The `services/notion_service.py` file is the central hub for all Notion write operations in the Adnan.AI system. This file manages interactions with Notion databases for goals, tasks, projects, and pages.

## Supported Operations

### 1. Create Page (`create_page`)

Generic page creation in any Notion database.

**Intent**: `create_page`

**Required Parameters**:
- `db_key`: Database identifier (e.g., "goals", "tasks", "projects")
- `properties` or `property_specs`: Page properties

**Example**:
```python
{
    "intent": "create_page",
    "params": {
        "db_key": "tasks",
        "property_specs": {
            "Name": {"type": "title", "text": "My Task"},
            "Description": {"type": "rich_text", "text": "Task description"}
        }
    }
}
```

### 2. Create Goal (`create_goal`)

Creates a goal in the Notion goals database.

**Intent**: `create_goal`

**Required Parameters**:
- `title`: Goal title (string)

**Optional Parameters**:
- `description`: Detailed description (string)
- `deadline`: Deadline in ISO8601 format (YYYY-MM-DD)
- `priority`: Priority level ("low", "medium", "high")
- `status`: Goal status (e.g., "pending", "in_progress", "completed")

**Example**:
```python
{
    "intent": "create_goal",
    "params": {
        "title": "Increase Revenue",
        "description": "Increase monthly recurring revenue by 20%",
        "deadline": "2025-12-31",
        "priority": "high",
        "status": "in_progress"
    }
}
```

### 3. Create Task (`create_task`)

Creates a task in the Notion tasks database.

**Intent**: `create_task`

**Required Parameters**:
- `title`: Task title (string)

**Optional Parameters**:
- `description`: Task description (string)
- `deadline`: Deadline in ISO8601 format (YYYY-MM-DD)
- `priority`: Priority level ("low", "medium", "high")
- `status`: Task status (e.g., "pending", "in_progress", "completed")
- `goal_id`: ID of the related goal (establishes relation)
- `project_id`: ID of the related project (establishes relation)

**Example**:
```python
{
    "intent": "create_task",
    "params": {
        "title": "Review Q4 metrics",
        "description": "Analyze performance data for Q4",
        "deadline": "2025-01-31",
        "priority": "medium",
        "status": "pending",
        "goal_id": "abc123-notion-goal-id",
        "project_id": "xyz789-notion-project-id"
    }
}
```

### 4. Create Project (`create_project`)

Creates a project in the Notion projects database.

**Intent**: `create_project`

**Required Parameters**:
- `title`: Project title (string)

**Optional Parameters**:
- `description`: Project description (string)
- `deadline`: Deadline in ISO8601 format (YYYY-MM-DD)
- `priority`: Priority level ("low", "medium", "high")
- `status`: Project status (e.g., "Active", "Completed", "On Hold")
- `primary_goal_id`: ID of the primary goal (establishes relation)

**Example**:
```python
{
    "intent": "create_project",
    "params": {
        "title": "Website Redesign",
        "description": "Complete overhaul of company website",
        "deadline": "2025-06-30",
        "priority": "high",
        "status": "Active",
        "primary_goal_id": "abc123-notion-goal-id"
    }
}
```

### 5. Update Page (`update_page`)

Updates an existing page in Notion.

**Intent**: `update_page`

**Required Parameters**:
- `page_id`: Notion page ID to update

**Optional Parameters**:
- `title`: Updated title
- `description`: Updated description
- `deadline`: Updated deadline (ISO8601 format)
- `priority`: Updated priority ("low", "medium", "high")
- `status`: Updated status
- `goal_id`: Update goal relation
- `project_id`: Update project relation
- `db_key`: Database key (helps with property type resolution)

**Example**:
```python
{
    "intent": "update_page",
    "params": {
        "page_id": "notion-page-id-123",
        "status": "completed",
        "priority": "low",
        "goal_id": "new-goal-id"
    }
}
```

## Property Types Supported

The system supports the following Notion property types:

1. **title**: Page title (required for most databases)
2. **rich_text**: Multi-line text content
3. **select**: Single selection from predefined options
4. **status**: Status property (automatically maps to select if needed)
5. **date**: Date or date range
6. **relation**: Link to pages in other databases

## Relation Linking

The system automatically handles relation linking between:
- **Tasks ↔ Goals**: Use `goal_id` parameter
- **Tasks ↔ Projects**: Use `project_id` parameter  
- **Projects ↔ Goals**: Use `primary_goal_id` parameter

Relations are established in two ways:
1. **During creation**: Include the relation ID in creation parameters
2. **After creation**: Use `update_page` with relation parameters

## Database Configuration

The system expects the following environment variables:

```bash
NOTION_API_KEY=your-notion-api-key
NOTION_GOALS_DB_ID=your-goals-database-id
NOTION_TASKS_DB_ID=your-tasks-database-id
NOTION_PROJECTS_DB_ID=your-projects-database-id
```

## Execution Flow

All Notion write operations follow the canonical execution flow:

1. **Proposal Phase** (READ-only)
   - User request → CEO Advisor → Proposed commands
   - Returns proposals without side effects

2. **Approval Phase** (Governance)
   - Proposed command → Approval system
   - Returns `approval_id` for tracking

3. **Execution Phase** (WRITE)
   - Approved command → NotionOpsAgent → NotionService.execute()
   - Actual Notion API write operation
   - Returns execution results with `execution_id`

## Security & Governance

- All write operations require `approval_id`
- Operations are blocked without proper governance approval
- Security checks enforce separation of concerns:
  - CEO Advisor is READ-only (advisory)
  - Notion Ops Agent requires armed state
  - NotionService requires approval_id for execution

## Error Handling

The service includes robust error handling:

- Missing required parameters → `RuntimeError` with clear message
- Invalid database keys → `RuntimeError` with resolution guidance
- Notion API errors → Wrapped with context and propagated
- Schema mismatches → Automatic mapping (e.g., status → select)

## Extension Points

To add new Notion operations:

1. Add new intent handler in `NotionService.execute()`
2. Implement `_execute_<operation_name>()` method
3. Follow the canonical response format
4. Update this documentation

## Related Files

- `services/notion_ops_agent.py` - Notion operations agent wrapper
- `routers/notion_ops_router.py` - Bulk operations router
- `ext/notion/writer.py` - Lower-level Notion writer utilities
- `models/goal_create.py`, `task_create.py`, `project_create.py` - Data models
- `models/goal_update.py`, `task_update.py`, `project_update.py` - Update models

## Testing

Test files demonstrating Notion operations:
- `single_task_test.ps1` - Task creation test
- `test_create_goal.ps1` - Goal creation test
- `test_notion_goal_persists.ps1` - Goal persistence test

## Conclusion

The `services/notion_service.py` file provides a complete, secure, and extensible foundation for all Notion operations. It supports creating and updating goals, tasks, projects, and pages while maintaining strict governance and security controls.
