from fastapi import APIRouter
from ext.tasks.queue import enqueue_task
from ext.tasks.db import get_task

router = APIRouter()

@router.post("/queue")
async def queue(payload: dict):
    task_id = enqueue_task(payload)
    return {"task_id": task_id}

@router.get("/queue/{task_id}")
async def get_status(task_id: str):
    return get_task(task_id)
