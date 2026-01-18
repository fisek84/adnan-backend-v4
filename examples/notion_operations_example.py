#!/usr/bin/env python3
"""
Example demonstrating how to use the extended Notion operations.

This shows how to create goals, tasks, and projects with relations.
"""
import asyncio
from services.notion_service import NotionService, bootstrap_notion_service_from_env
from models.ai_command import AICommand


async def example_create_goal():
    """Example: Create a goal in Notion."""
    print("\n=== Example: Create Goal ===")

    # Bootstrap the service from environment variables
    service = bootstrap_notion_service_from_env()
    if not service:
        print("ERROR: NotionService not configured. Set env vars:")
        print("  NOTION_API_KEY, NOTION_GOALS_DB_ID, NOTION_TASKS_DB_ID, NOTION_PROJECTS_DB_ID")
        return

    # Create a goal command
    command = AICommand(
        command="notion_write",
        intent="create_goal",
        params={
            "title": "Increase Revenue Q1 2025",
            "description": "Achieve 20% revenue growth in Q1",
            "deadline": "2025-03-31",
            "priority": "high",
            "status": "in_progress",
        },
        approval_id="example-approval-001",
        execution_id="example-exec-001",
        read_only=False,
    )

    try:
        result = await service.execute(command)
        print(f"✅ Goal created successfully!")
        print(f"   Page ID: {result['result']['page_id']}")
        print(f"   URL: {result['result']['url']}")
        return result["result"]["page_id"]
    except Exception as e:
        print(f"❌ Error creating goal: {e}")
        return None
    finally:
        await service.aclose()


async def example_create_task_with_goal(goal_id: str):
    """Example: Create a task linked to a goal."""
    print("\n=== Example: Create Task with Goal Relation ===")

    service = bootstrap_notion_service_from_env()
    if not service:
        return

    command = AICommand(
        command="notion_write",
        intent="create_task",
        params={
            "title": "Prepare Q1 Sales Report",
            "description": "Analyze sales data and prepare presentation",
            "deadline": "2025-02-15",
            "priority": "high",
            "status": "pending",
            "goal_id": goal_id,  # Link to the goal
        },
        approval_id="example-approval-002",
        execution_id="example-exec-002",
        read_only=False,
    )

    try:
        result = await service.execute(command)
        print(f"✅ Task created and linked to goal!")
        print(f"   Page ID: {result['result']['page_id']}")
        print(f"   URL: {result['result']['url']}")
        return result["result"]["page_id"]
    except Exception as e:
        print(f"❌ Error creating task: {e}")
        return None
    finally:
        await service.aclose()


async def example_create_project_with_goal(goal_id: str):
    """Example: Create a project linked to a goal."""
    print("\n=== Example: Create Project with Goal Relation ===")

    service = bootstrap_notion_service_from_env()
    if not service:
        return

    command = AICommand(
        command="notion_write",
        intent="create_project",
        params={
            "title": "Q1 Revenue Growth Initiative",
            "description": "Strategic project to achieve revenue targets",
            "deadline": "2025-03-31",
            "priority": "high",
            "status": "Active",
            "primary_goal_id": goal_id,  # Link to the goal
        },
        approval_id="example-approval-003",
        execution_id="example-exec-003",
        read_only=False,
    )

    try:
        result = await service.execute(command)
        print(f"✅ Project created and linked to goal!")
        print(f"   Page ID: {result['result']['page_id']}")
        print(f"   URL: {result['result']['url']}")
        return result["result"]["page_id"]
    except Exception as e:
        print(f"❌ Error creating project: {e}")
        return None
    finally:
        await service.aclose()


async def example_update_task_status(task_id: str):
    """Example: Update a task's status and priority."""
    print("\n=== Example: Update Task Status ===")

    service = bootstrap_notion_service_from_env()
    if not service:
        return

    command = AICommand(
        command="notion_write",
        intent="update_page",
        params={
            "page_id": task_id,
            "status": "in_progress",
            "priority": "medium",
        },
        approval_id="example-approval-004",
        execution_id="example-exec-004",
        read_only=False,
    )

    try:
        result = await service.execute(command)
        print(f"✅ Task updated successfully!")
        print(f"   Page ID: {result['result']['page_id']}")
        print(f"   URL: {result['result']['url']}")
    except Exception as e:
        print(f"❌ Error updating task: {e}")
    finally:
        await service.aclose()


async def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("Notion Operations Examples")
    print("=" * 60)

    # Example 1: Create a goal
    goal_id = await example_create_goal()

    if goal_id:
        # Example 2: Create a task linked to the goal
        task_id = await example_create_task_with_goal(goal_id)

        # Example 3: Create a project linked to the goal
        project_id = await example_create_project_with_goal(goal_id)

        if task_id:
            # Example 4: Update the task status
            await example_update_task_status(task_id)

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    # NOTE: This example requires proper environment variables:
    # - NOTION_API_KEY (or NOTION_TOKEN)
    # - NOTION_GOALS_DB_ID
    # - NOTION_TASKS_DB_ID
    # - NOTION_PROJECTS_DB_ID

    print("\n⚠️  WARNING: This will create real pages in your Notion workspace!")
    print("    Make sure your environment variables are set correctly.\n")

    # Uncomment to run (commented by default for safety)
    # asyncio.run(main())

    print("Example code is ready. Uncomment asyncio.run(main()) to execute.")
