diff --git a/main.py b/main.py
index 87d7fc1769cc70c88410eea16636015ec7fc3c89..d4f0a1d1bf7f2e1ed6a3493a0d5679d098bab862 100644
--- a/main.py
+++ b/main.py
@@ -1,170 +1,243 @@
-from fastapi import FastAPI
-from pydantic import BaseModel
-from typing import Optional
-from notion_client import Client
 import os
+from typing import Optional
+
 from dotenv import load_dotenv
 
-# ----------------------------
-# LOAD ENV VARS
-# ----------------------------
+# Load env vars before importing Notion client so it picks up tokens
 load_dotenv()
 
-NOTION_TOKEN = os.getenv("NOTION_TOKEN")
-GOALS_DB_ID = os.getenv("GOALS_DB_ID")
-TASKS_DB_ID = os.getenv("TASKS_DB_ID")
+from fastapi import Depends, FastAPI, Header, HTTPException
+from pydantic import BaseModel
+
+from notion_service import GOALS_DB_ID, TASKS_DB_ID, notion
+
+API_KEY = os.getenv("API_KEY")
 
-notion = Client(auth=NOTION_TOKEN)
 app = FastAPI()
 
+
 # ----------------------------
-# PYDANTIC MODELS
+# SECURITY
 # ----------------------------
 
-class GoalCreate(BaseModel):
-    name: Optional[str] = None
-    outcome_state: Optional[str] = None
-    outcome_result: Optional[str] = None
-    activity_state: Optional[str] = None
-    context_state: Optional[str] = None
+def verify_api_key(x_api_key: Optional[str] = Header(None)):
+    if API_KEY and x_api_key != API_KEY:
+        raise HTTPException(status_code=401, detail="Invalid API Key")
 
-class TaskCreate(BaseModel):
-    name: str
-    goal_id: Optional[str] = None  # optional relation to a goal
 
 # ----------------------------
-# HELPER: NAME GENERATOR
+# PYDANTIC MODELS
 # ----------------------------
 
-def generate_goal_name(data: GoalCreate):
-    # A) Ako name postoji → koristi ga
-    if data.name:
-        return data.name
+class GoalCreate(BaseModel):
+    title: str
+    description: Optional[str] = None
+    deadline: Optional[str] = None
+    parent_id: Optional[str] = None
+    priority: Optional[str] = None
+    status: Optional[str] = None
+    progress: Optional[int] = None
+
 
-    # B) Ako nema name → koristi drugo polje redom
-    if data.outcome_state:
-        return f"Goal: {data.outcome_state}"
-    if data.outcome_result:
-        return f"Goal: {data.outcome_result}"
-    if data.activity_state:
-        return f"Goal: {data.activity_state}"
-    if data.context_state:
-        return f"Goal: {data.context_state}"
+class GoalUpdate(BaseModel):
+    title: Optional[str] = None
+    description: Optional[str] = None
+    deadline: Optional[str] = None
+    parent_id: Optional[str] = None
+    priority: Optional[str] = None
+    status: Optional[str] = None
+    progress: Optional[int] = None
 
-    # C) Ako ništa ne postoji → error
-    return None
 
-# ----------------------------
-# ROOT
-# ----------------------------
+class TaskCreate(BaseModel):
+    title: str
+    description: Optional[str] = None
+    goal_id: Optional[str] = None
+    deadline: Optional[str] = None
+    priority: Optional[str] = None
+    status: Optional[str] = None
+    order: Optional[int] = None
+
+
+class TaskUpdate(BaseModel):
+    title: Optional[str] = None
+    description: Optional[str] = None
+    goal_id: Optional[str] = None
+    deadline: Optional[str] = None
+    priority: Optional[str] = None
+    status: Optional[str] = None
+    order: Optional[int] = None
+
+
+# ----------------------------
+# HELPERS: PROPERTY BUILDERS
+# ----------------------------
+
+def build_goal_properties(data: BaseModel):
+    properties = {}
+
+    if getattr(data, "title", None):
+        properties["Name"] = {"title": [{"text": {"content": data.title}}]}
+    if getattr(data, "description", None):
+        properties["Description"] = {"rich_text": [{"text": {"content": data.description}}]}
+    if getattr(data, "deadline", None):
+        properties["Deadline"] = {"date": {"start": data.deadline}}
+    if getattr(data, "priority", None):
+        properties["Priority"] = {"select": {"name": data.priority}}
+    if getattr(data, "status", None):
+        properties["Goal State"] = {"select": {"name": data.status}}
+    if getattr(data, "progress", None) is not None:
+        properties["Progress"] = {"number": data.progress}
+    if getattr(data, "parent_id", None):
+        properties["Parent Goal"] = {"relation": [{"id": data.parent_id}]}
+
+    return properties
+
+
+def build_task_properties(data: BaseModel):
+    properties = {}
+
+    if getattr(data, "title", None):
+        properties["Name"] = {"title": [{"text": {"content": data.title}}]}
+    if getattr(data, "description", None):
+        properties["Description"] = {"rich_text": [{"text": {"content": data.description}}]}
+    if getattr(data, "deadline", None):
+        properties["Deadline"] = {"date": {"start": data.deadline}}
+    if getattr(data, "priority", None):
+        properties["Priority"] = {"select": {"name": data.priority}}
+    if getattr(data, "status", None):
+        properties["Task Status"] = {"select": {"name": data.status}}
+    if getattr(data, "order", None) is not None:
+        properties["Order"] = {"number": data.order}
+    if getattr(data, "goal_id", None):
+        properties["Goal"] = {"relation": [{"id": data.goal_id}]}
+
+    return properties
 
 @app.get("/")
 def root():
     return {"status": "OK", "message": "AdnanAI backend radi."}
 
-# ----------------------------
-# GET GOALS
-# ----------------------------
-
-@app.get("/goals")
-def get_goals():
-    try:
-        result = notion.databases.query(database_id=GOALS_DB_ID)
-        return result
-    except Exception as e:
-        return {"error": str(e)}
 
 # ----------------------------
-# GET TASKS
+# GOALS
 # ----------------------------
 
-@app.get("/tasks")
-def get_tasks():
+@app.get("/goals/all", dependencies=[Depends(verify_api_key)])
+def get_goals():
     try:
-        result = notion.databases.query(database_id=TASKS_DB_ID)
-        return result
+        return notion.databases.query(database_id=GOALS_DB_ID)
     except Exception as e:
-        return {"error": str(e)}
+        raise HTTPException(status_code=500, detail=str(e))
 
-# ----------------------------
-# POST GOALS (NEW)
-# ----------------------------
 
-@app.post("/goals")
+@app.post("/goals/create", dependencies=[Depends(verify_api_key)])
 def create_goal(data: GoalCreate):
+    properties = build_goal_properties(data)
 
-    # 1. GENERIŠI IME
-    generated_name = generate_goal_name(data)
-    if not generated_name:
-        return {"error": "Name is missing"}
+    try:
+        result = notion.pages.create(
+            parent={"database_id": GOALS_DB_ID},
+            properties=properties,
+        )
 
-    # 2. MAPIRAJ PROPERTIES
-    properties = {
-        "Name": {
-            "title": [{"text": {"content": generated_name}}]
+        return {
+            "status": "created",
+            "goal": {
+                "id": result["id"],
+                "title": data.title,
+                "description": data.description,
+                "deadline": data.deadline,
+                "parent_id": data.parent_id,
+                "priority": data.priority,
+                "status": data.status,
+                "progress": data.progress,
+            },
         }
-    }
-
-    if data.outcome_state:
-        properties["Outcome State"] = {"select": {"name": data.outcome_state}}
+    except Exception as e:
+        raise HTTPException(status_code=500, detail=str(e))
 
-    if data.outcome_result:
-        properties["Outcome Result"] = {"rich_text": [{"text": {"content": data.outcome_result}}]}
 
-    if data.activity_state:
-        properties["Activity State"] = {"select": {"name": data.activity_state}}
+@app.patch("/goals/{goal_id}", dependencies=[Depends(verify_api_key)])
+def update_goal(goal_id: str, data: GoalUpdate):
+    properties = build_goal_properties(data)
 
-    if data.context_state:
-        properties["Context State"] = {"select": {"name": data.context_state}}
+    if not properties:
+        raise HTTPException(status_code=400, detail="No fields to update")
 
-    # 3. CREATE PAGE U NOTION DATABASE
     try:
-        result = notion.pages.create(
-            parent={"database_id": GOALS_DB_ID},
-            properties=properties
-        )
+        notion.pages.update(page_id=goal_id, properties=properties)
+        return {"status": "updated", "goal_id": goal_id}
+    except Exception as e:
+        raise HTTPException(status_code=500, detail=str(e))
 
-        return {
-            "status": "success",
-            "goal_id": result["id"],
-            "name": generated_name
-        }
 
+@app.delete("/goals/{goal_id}", dependencies=[Depends(verify_api_key)])
+def delete_goal(goal_id: str):
+    try:
+        notion.pages.update(page_id=goal_id, archived=True)
+        return {"status": "deleted", "goal_id": goal_id}
     except Exception as e:
-        return {"error": str(e)}
+        raise HTTPException(status_code=500, detail=str(e))
+
 
 # ----------------------------
-# POST TASKS (NEW)
+# TASKS
 # ----------------------------
 
-@app.post("/tasks")
-def create_task(data: TaskCreate):
-    if not data.name:
-        return {"error": "Task name is required"}
+@app.get("/tasks/all", dependencies=[Depends(verify_api_key)])
+def get_tasks():
+    try:
+        return notion.databases.query(database_id=TASKS_DB_ID)
+    except Exception as e:
+        raise HTTPException(status_code=500, detail=str(e))
 
-    properties = {
-        "Name": {
-            "title": [{"text": {"content": data.name}}]
-        }
-    }
 
-    if data.goal_id:
-        properties["Goal"] = {
-            "relation": [{"id": data.goal_id}]
-        }
+@app.post("/tasks/create", dependencies=[Depends(verify_api_key)])
+def create_task(data: TaskCreate):
+    properties = build_task_properties(data)
 
     try:
         result = notion.pages.create(
             parent={"database_id": TASKS_DB_ID},
-            properties=properties
+            properties=properties,
         )
 
         return {
-            "status": "success",
-            "task_id": result["id"],
-            "name": data.name,
-            "goal_id": data.goal_id
+            "status": "created",
+            "task": {
+                "id": result["id"],
+                "title": data.title,
+                "description": data.description,
+                "goal_id": data.goal_id,
+                "deadline": data.deadline,
+                "priority": data.priority,
+                "status": data.status,
+                "order": data.order,
+            },
         }
+    except Exception as e:
+        raise HTTPException(status_code=500, detail=str(e))
+
 
+@app.patch("/tasks/{task_id}", dependencies=[Depends(verify_api_key)])
+def update_task(task_id: str, data: TaskUpdate):
+    properties = build_task_properties(data)
+
+    if not properties:
+        raise HTTPException(status_code=400, detail="No fields to update")
+
+    try:
+        notion.pages.update(page_id=task_id, properties=properties)
+        return {"status": "updated", "task_id": task_id}
+    except Exception as e:
+        raise HTTPException(status_code=500, detail=str(e))
+
+
+@app.delete("/tasks/{task_id}", dependencies=[Depends(verify_api_key)])
+def delete_task(task_id: str):
+    try:
+        notion.pages.update(page_id=task_id, archived=True)
+        return {"status": "deleted", "task_id": task_id}
     except Exception as e:
-        return {"error": str(e)}
+        raise HTTPException(status_code=500, detail=str(e))