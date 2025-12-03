from fastapi import APIRouter, Depends, HTTPException
from typing import List

from models.project_create import ProjectCreate
from models.project_update import ProjectUpdate
from models.project_model import ProjectModel   # ✅ FIXED

from services.projects_service import ProjectsService
from dependencies import get_projects_service

router = APIRouter(prefix="/projects", tags=["Projects"])


# ============================================================
# GET ALL PROJECTS
# ============================================================
@router.get("/", response_model=List[ProjectModel])
def get_all_projects(projects_service: ProjectsService = Depends(get_projects_service)):
    return projects_service.get_all()


# ============================================================
# GET SINGLE PROJECT
# ============================================================
@router.get("/{project_id}", response_model=ProjectModel)
def get_project(project_id: str, projects_service: ProjectsService = Depends(get_projects_service)):
    projects = projects_service.get_all()
    for p in projects:
        if p.id == project_id or p.notion_id == project_id:
            return p

    raise HTTPException(status_code=404, detail="Project not found")


# ============================================================
# CREATE PROJECT
# ============================================================
@router.post("/", response_model=ProjectModel)
def create_project(
    payload: ProjectCreate,
    projects_service: ProjectsService = Depends(get_projects_service)
):
    return projects_service.create_project(payload)


# ============================================================
# UPDATE PROJECT
# ============================================================
@router.patch("/{project_id}", response_model=ProjectModel)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    projects_service: ProjectsService = Depends(get_projects_service)
):
    try:
        return projects_service.update_project(project_id, payload)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")


# ============================================================
# DELETE PROJECT
# ============================================================
@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    projects_service: ProjectsService = Depends(get_projects_service)
):
    try:
        deleted = projects_service.delete_project(project_id)
        return {"deleted": True, "project_id": project_id}
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
