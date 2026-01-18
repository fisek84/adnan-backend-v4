# Notion Operations - Quick Reference

## 🎯 Problem Solved

**Question**: Koji fajl je odgovoran za sve Notion operacije (kreiranje ciljeva, zadataka, projekata, stranica, povezivanje relacija, ažuriranje statusa i due dates)?

**Answer**: **`services/notion_service.py`** ✅

## 📁 The Central File

```
services/notion_service.py
```

This is the **Single Source of Truth (SSOT)** for all Notion write operations.

## ✨ What It Can Do

### Create Operations
```python
# Create a goal
{
    "intent": "create_goal",
    "params": {
        "title": "My Goal",
        "description": "Goal description",
        "deadline": "2025-12-31",
        "priority": "high",
        "status": "in_progress"
    }
}

# Create a task (with relations)
{
    "intent": "create_task",
    "params": {
        "title": "My Task",
        "goal_id": "goal-page-id",
        "project_id": "project-page-id",
        "deadline": "2025-06-30"
    }
}

# Create a project (with relation)
{
    "intent": "create_project",
    "params": {
        "title": "My Project",
        "primary_goal_id": "goal-page-id",
        "status": "Active"
    }
}
```

### Update Operations
```python
# Update status and due date
{
    "intent": "update_page",
    "params": {
        "page_id": "page-id-to-update",
        "status": "completed",
        "deadline": "2025-12-31",
        "priority": "low"
    }
}

# Update relations
{
    "intent": "update_page",
    "params": {
        "page_id": "task-page-id",
        "goal_id": "new-goal-id",
        "project_id": "new-project-id"
    }
}
```

## 🔗 Relation Support

The system automatically handles these relations:
- Task ↔ Goal
- Task ↔ Project
- Project ↔ Goal

Just include the `*_id` parameter and the relation is created/updated automatically.

## 📚 Documentation

- **Complete Guide**: `docs/NOTION_OPERATIONS.md`
- **Solution Summary**: `docs/NOTION_OPS_SOLUTION.md`
- **Usage Examples**: `examples/notion_operations_example.py`
- **Tests**: `tests/test_notion_service_operations.py`

## 🚀 Quick Start

1. **Set environment variables**:
   ```bash
   export NOTION_API_KEY=your-api-key
   export NOTION_GOALS_DB_ID=your-goals-db-id
   export NOTION_TASKS_DB_ID=your-tasks-db-id
   export NOTION_PROJECTS_DB_ID=your-projects-db-id
   ```

2. **Run the example**:
   ```bash
   python examples/notion_operations_example.py --run
   ```

3. **Or use programmatically**:
   ```python
   from services.notion_service import bootstrap_notion_service_from_env
   from models.ai_command import AICommand
   
   service = bootstrap_notion_service_from_env()
   
   command = AICommand(
       intent="create_goal",
       params={"title": "My Goal"},
       approval_id="approval-id",
       read_only=False
   )
   
   result = await service.execute(command)
   ```

## 🔒 Security

All operations:
- ✅ Require `approval_id` (governance enforced)
- ✅ Follow READ/WRITE separation
- ✅ Pass security scanning (0 vulnerabilities)
- ✅ Respect NotionOpsAgent armed state

## 🧪 Testing

Run tests:
```bash
python -m unittest tests.test_notion_service_operations -v
```

## 📊 Supported Property Types

- `title` - Page titles
- `rich_text` - Long text/descriptions
- `select` - Single choice fields
- `status` - Status fields (auto-maps to select if needed)
- `date` - Dates and deadlines
- `relation` - Links to other pages

## 🎓 Examples

See `examples/notion_operations_example.py` for complete working examples of:
- Creating goals
- Creating tasks with relations
- Creating projects with relations
- Updating status and due dates

## 🔧 Implementation Details

### Main Methods

```python
NotionService.execute(command)           # Main entry point
  ├─ _execute_create_goal()             # Create goals
  ├─ _execute_create_task()             # Create tasks
  ├─ _execute_create_project()          # Create projects
  ├─ _execute_update_page()             # Update pages
  └─ _update_page_relations()           # Manage relations
```

### Helper Methods

```python
_date_prop()         # Build date properties
_relation_prop()     # Build relation properties
_title_prop()        # Build title properties
_rich_text_prop()    # Build text properties
_select_prop()       # Build select properties
_status_prop()       # Build status properties
```

## ✅ Conclusion

**`services/notion_service.py`** is the file you need. It handles:

✅ Goal creation  
✅ Task creation  
✅ Project creation  
✅ Page updates  
✅ Status updates  
✅ Due date updates  
✅ Relation linking  
✅ All Notion operations  

Everything works through this single, well-architected file! 🎉
