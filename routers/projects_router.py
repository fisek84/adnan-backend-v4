from fastapi import APIRouter, Depends, HTTPException
from typing import List
import logging  # Dodajemo logovanje

from models.project_create import ProjectCreate
from models.project_update import ProjectUpdate
from models.project_model import ProjectModel   # ✅ FIXED

from services.projects_service import ProjectsService
from dependencies import get_projects_service

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/projects", tags=["Projects"])

# ============================================================
# GET ALL PROJECTS
# ============================================================
@router.get("/", response_model=List[ProjectModel])
def get_all_projects(projects_service: ProjectsService = Depends(get_projects_service)):
    logger.info("Fetching all projects.")
    projects = projects_service.get_all()
    logger.info(f"Fetched {len(projects)} projects.")
    return projects


# ============================================================
# GET SINGLE PROJECT
# ============================================================
@router.get("/{project_id}", response_model=ProjectModel)
def get_project(project_id: str, projects_service: ProjectsService = Depends(get_projects_service)):
    logger.info(f"Fetching project with ID: {project_id}")
    projects = projects_service.get_all()
    for p in projects:
        if p.id == project_id or p.notion_id == project_id:
            logger.info(f"Project {project_id} found.")
            return p

    logger.error(f"Project {project_id} not found.")
    raise HTTPException(status_code=404, detail="Project not found")


# ============================================================
# CREATE PROJECT
# ============================================================
@router.post("/", response_model=ProjectModel)
def create_project(
    payload: ProjectCreate,
    projects_service: ProjectsService = Depends(get_projects_service)
):
    logger.info(f"Creating project with title: {payload.title}")
    project = projects_service.create_project(payload)
    logger.info(f"Project {project.id} created successfully.")
    return project


# ============================================================
# UPDATE PROJECT
# ============================================================
@router.patch("/{project_id}", response_model=ProjectModel)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    projects_service: ProjectsService = Depends(get_projects_service)
):
    logger.info(f"Updating project with ID: {project_id}")
    try:
        updated_project = projects_service.update_project(project_id, payload)
        logger.info(f"Project {project_id} updated successfully.")
        return updated_project
    except ValueError:
        logger.error(f"Project {project_id} not found for update.")
        raise HTTPException(status_code=404, detail="Project not found")


# ============================================================
# DELETE PROJECT
# ============================================================
@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    projects_service: ProjectsService = Depends(get_projects_service)
):
    logger.info(f"Deleting project with ID: {project_id}")
    try:
        deleted = projects_service.delete_project(project_id)
        logger.info(f"Project {project_id} deleted successfully.")
        return {"deleted": True, "project_id": project_id}
    except ValueError:
        logger.error(f"Project {project_id} not found for deletion.")
        raise HTTPException(status_code=404, detail="Project not found")
