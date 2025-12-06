from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
from dependencies import get_goals_service, get_tasks_service

# Import TaskCreate (required!)
from models.task_create import TaskCreate

router = APIRouter(prefix="/notion-ops", tags=["Notion Ops Bulk"])


@router.post("/bulk")
async def notion_ops_bulk(payload: Dict[str, Any],
                          goals_service=Depends(get_goals_service),
                          tasks_service=Depends(get_tasks_service)):

    if "goals" not in payload:
        raise HTTPException(400, "Payload must include 'goals' array")

    if "tasks" not in payload:
        payload["tasks"] = []

    if "links" not in payload:
        payload["links"] = []

    temp_map = {}
    temp_ids = set()

    # VALIDACIJA GOALS
    for item in payload["goals"]:
        if "temp_id" not in item:
            raise HTTPException(400, f"Goal missing temp_id: {item}")

        if item["temp_id"] in temp_ids:
            raise HTTPException(400, f"Duplicate temp_id: {item['temp_id']}")

        temp_ids.add(item["temp_id"])

        if "title" not in item or not item["title"]:
            raise HTTPException(400, f"Goal '{item['temp_id']}' missing title")

    # VALIDACIJA TASKS
    for t in payload["tasks"]:
        if "temp_id" not in t:
            raise HTTPException(400, f"Task missing temp_id: {t}")

        if "title" not in t or not t["title"]:
            raise HTTPException(400, f"Task '{t['temp_id']}' missing title")

        if t.get("goal_temp") not in temp_ids:
            raise HTTPException(400, f"Task goal_temp '{t.get('goal_temp')}' invalid")

    # VALIDACIJA LINKS
    for link in payload["links"]:
        c = link.get("child_temp")
        p = link.get("parent_temp")
        if c not in temp_ids or p not in temp_ids:
            raise HTTPException(400, f"Invalid link: {link}")

    results = {
        "status": "completed",
        "goals_created": 0,
        "tasks_created": 0,
        "links_applied": 0
    }

    try:
        # --------------------------------------------
        # CREATE GOALS
        # --------------------------------------------
        for item in payload["goals"]:
            goal_data = {
                "title": item["title"],
                "description": item.get("description"),
                "deadline": item.get("deadline"),
                "priority": item.get("priority"),
                "parent_id": None
            }

            new_goal = goals_service.create_goal(goal_data)
            temp_map[item["temp_id"]] = new_goal.id
            results["goals_created"] += 1

        # --------------------------------------------
        # CREATE TASKS  (ASYNC FIX)
        # --------------------------------------------
        from models.task_create import TaskCreate

        for t in payload["tasks"]:
            task_data = {
                "title": t["title"],
                "description": t.get("description"),
                "deadline": t.get("deadline"),
                "priority": t.get("priority"),
                "goal_id": temp_map[t["goal_temp"]]
            }

            task_model = TaskCreate(**task_data)

            new_task = await tasks_service.create_task(task_model)  # FIXED

            temp_map[t["temp_id"]] = new_task.id
            results["tasks_created"] += 1

        # --------------------------------------------
        # APPLY LINKS (send dict to update_goal)
        # --------------------------------------------
        for link in payload["links"]:
            child_real = temp_map[link["child_temp"]]
            parent_real = temp_map[link["parent_temp"]]

            update_data = {"parent_id": parent_real}

            await goals_service.update_goal(child_real, update_data)

            results["links_applied"] += 1

    except Exception as e:
        raise HTTPException(500, f"Bulk execution failed: {e}")

    return results
