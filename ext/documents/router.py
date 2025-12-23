from fastapi import APIRouter
from ext.documents.orchestrator import orchestrate_document

router = APIRouter()


@router.post("/documents/orchestrate")
async def orchestrate_endpoint(data: dict):
    result = orchestrate_document(data)
    return result
