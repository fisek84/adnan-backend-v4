def create_task(self, data: TaskCreate, forced_id: Optional[str] = None, notion_id: Optional[str] = None) -> TaskModel:
    now = self._now()
    task_id = forced_id or uuid4().hex

    new_task = TaskModel(
        id=task_id,
        title=data.title,
        description=data.description,
        deadline=data.deadline,
        goal_id=data.goal_id,
        priority=data.priority,
        status="pending",
        order=0,
        created_at=now,
        updated_at=now,

        # ⭐ OVO JE KLJUČNO ZA BRISANJE IZ NOTIONA
        notion_id=notion_id  
    )

    self.tasks[task_id] = new_task
    self._trigger_sync()
    return new_task
