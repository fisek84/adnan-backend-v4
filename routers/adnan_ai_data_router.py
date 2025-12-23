import json
import os
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI Data"])

BASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "adnan_ai")


def read_json(filename: str):
    path = os.path.join(BASE_PATH, filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"{filename} not found")

    try:
        # FIX: UTF-8 SIG removes BOM
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/identity")
def get_identity():
    return read_json("identity.json")


@router.get("/kernel")
def get_kernel():
    return read_json("kernel.json")


@router.get("/mode")
def get_mode():
    return read_json("mode.json")


@router.get("/state")
def get_state():
    return read_json("state.json")


@router.get("/decision-engine")
def get_decision_engine():
    return read_json("decision_engine.json")
