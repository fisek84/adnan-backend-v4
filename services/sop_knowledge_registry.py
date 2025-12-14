from pathlib import Path
from typing import Dict, Any, List, Optional
import json

# TAČAN PATH:
# services/adnan_ai/sops/*.json
BASE_PATH = Path(__file__).resolve().parent / "adnan_ai" / "sops"


class SOPKnowledgeRegistry:
    """
    SOP KNOWLEDGE REGISTRY — CEO SOURCE OF TRUTH

    Pravila:
    - READ-ONLY
    - svi SOP-ovi su fajlovi
    - filename = canonical SOP ID
    - nema logike izvršenja
    - nema memorije
    """

    def __init__(self):
        pass

    # ============================================================
    # LIST
    # ============================================================
    def list_sops(self) -> List[Dict[str, Any]]:
        """
        Vraća listu svih SOP-ova (metadata).
        """
        sops: List[Dict[str, Any]] = []

        if not BASE_PATH.exists():
            return sops

        for path in BASE_PATH.glob("*.json"):
            sop_id = path.stem  # CANONICAL ID

            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                sops.append({
                    "id": sop_id,
                    "name": data.get("name", sop_id),
                    "version": data.get("version", "1.0"),
                    "description": data.get("description", ""),
                })
            except Exception:
                continue

        return sorted(sops, key=lambda x: x["name"].lower())

    # ============================================================
    # GET
    # ============================================================
    def get_sop(
        self,
        sop_id: str,
        mode: str = "summary",  # summary | full
    ) -> Optional[Dict[str, Any]]:
        """
        Dohvata SOP po ID-u (filename = ID).
        """
        if mode not in {"summary", "full"}:
            return None

        path = BASE_PATH / f"{sop_id}.json"
        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if mode == "summary":
            return {
                "id": sop_id,
                "name": data.get("name", sop_id),
                "version": data.get("version"),
                "description": data.get("description"),
                "steps": [
                    {
                        "step": s.get("step"),
                        "title": s.get("title"),
                    }
                    for s in data.get("steps", [])
                ],
            }

        # FULL
        return {
            "id": sop_id,
            "name": data.get("name", sop_id),
            "version": data.get("version"),
            "description": data.get("description"),
            "content": data,
        }

    # ============================================================
    # SOP → TASK MAPPING (FAZA 5.4 — KORAK 2)
    # ============================================================
    def map_sop_to_tasks(self, sop_id: str) -> List[Dict[str, Any]]:
        """
        Deterministički mapira SOP u niz TASK payload-a.

        Pravila:
        - bez AI
        - bez heuristike
        - 1 SOP step = 1 TASK
        - redoslijed je strogo definisan SOP-om
        """

        path = BASE_PATH / f"{sop_id}.json"
        if not path.exists():
            return []

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        steps = data.get("steps", [])
        tasks: List[Dict[str, Any]] = []

        for idx, step in enumerate(steps, start=1):
            tasks.append({
                "task_id": f"{sop_id}_step_{idx}",
                "sop_id": sop_id,
                "step": step.get("step", idx),
                "title": step.get("title"),
                "description": step.get("description"),
                "action": step.get("action"),
                "parameters": step.get("parameters", {}),
                "order": idx,
            })

        return tasks
