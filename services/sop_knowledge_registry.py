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
    - nema logike izvršenja
    - nema memorije
    - ovo je znanje, ne akcija
    """

    def __init__(self):
        # READ-ONLY: ne diramo filesystem
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
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                sops.append({
                    "id": data.get("id") or path.stem,
                    "name": data.get("name", path.stem),
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
        Dohvata SOP po ID-u.
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
                "id": data.get("id"),
                "name": data.get("name"),
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
            "id": data.get("id"),
            "name": data.get("name"),
            "version": data.get("version"),
            "description": data.get("description"),
            "content": data,
        }
