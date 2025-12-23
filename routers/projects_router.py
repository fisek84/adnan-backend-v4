from fastapi import APIRouter, Depends, HTTPException
from typing import List
import logging

from models.project_create import ProjectCreate
from models.project_update import ProjectUpdate
from models.project_model import ProjectModel

from services.projects_service import ProjectsService
from dependencies import get_projects_service

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
def get_project(
    project_id: str, projects_service: ProjectsService = Depends(get_projects_service)
):
    logger.info(f"Fetching project with ID: {project_id}")
    projects = projects_service.get_all()
    for p in projects:
        if p.id == project_id or p.notion_id == project_id:
            logger.info(f"Project {project_id} found.")
            return p

    logger.error(f"Project {project_id} not found.")
    raise HTTPException(status_code=404, detail="Project not found")


# ============================================================
# CREATE PROJECT (WRITE via WriteGateway)
# ============================================================
@router.post("/", response_model=ProjectModel)
async def create_project(
    payload: ProjectCreate,
    projects_service: ProjectsService = Depends(get_projects_service),
):
    logger.info(f"Creating project with title: {payload.title}")

    res = await projects_service.create_project(payload)

    if res.get("success") is True and res.get("status") in ("applied", "replayed"):
        project_id = (res.get("data") or {}).get("project_id")
        proj = projects_service.get(project_id) if project_id else None
        if not proj:
            raise HTTPException(
                status_code=500, detail="Project created but not found locally"
            )
        logger.info(f"Project {proj.id} created successfully.")
        return proj

    if res.get("status") == "requires_approval":
        raise HTTPException(
            status_code=409,
            detail={
                "reason": res.get("reason"),
                "approval_id": res.get("approval_id"),
                "write_id": res.get("write_id"),
            },
        )

    raise HTTPException(status_code=403, detail=res.get("reason") or "write_rejected")


# ============================================================
# UPDATE PROJECT (WRITE via WriteGateway)
# ============================================================
@router.patch("/{project_id}", response_model=ProjectModel)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    projects_service: ProjectsService = Depends(get_projects_service),
):
    logger.info(f"Updating project with ID: {project_id}")

    res = await projects_service.update_project(project_id, payload)

    if res.get("success") is True and res.get("status") in ("applied", "replayed"):
        proj = projects_service.get(project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        logger.info(f"Project {project_id} updated successfully.")
        return proj

    if res.get("status") == "requires_approval":
        raise HTTPException(
            status_code=409,
            detail={
                "reason": res.get("reason"),
                "approval_id": res.get("approval_id"),
                "write_id": res.get("write_id"),
            },
        )

    raise HTTPException(
        status_code=404, detail=res.get("reason") or "Project not found"
    )


# ============================================================
# DELETE PROJECT (WRITE via WriteGateway)
# ============================================================
@router.delete("/{project_id}")
async def delete_project(
    project_id: str, projects_service: ProjectsService = Depends(get_projects_service)
):
    logger.info(f"Deleting project with ID: {project_id}")

    res = await projects_service.delete_project(project_id)

    if res.get("success") is True and res.get("status") in ("applied", "replayed"):
        logger.info(f"Project {project_id} deleted successfully.")
        return {"deleted": True, "project_id": project_id}

    if res.get("status") == "requires_approval":
        raise HTTPException(
            status_code=409,
            detail={
                "reason": res.get("reason"),
                "approval_id": res.get("approval_id"),
                "write_id": res.get("write_id"),
            },
        )

    raise HTTPException(
        status_code=404, detail=res.get("reason") or "Project not found"
    )
