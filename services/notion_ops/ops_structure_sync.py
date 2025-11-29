# services/notion_ops/ops_structure_sync.py

from typing import Dict, Any
from notion_client import Client
import os


class NotionStructureSync:
    """
    Analizira strukturu Notion baze i poredi sa očekivanom strukturom.
    Ne izvršava nikakve destruktivne akcije — samo vraća rezime razlika.
    """

    def __init__(self):
        self.notion = Client(auth=os.getenv("NOTION_API_KEY"))

    # ============================================================
    # GET DB STRUCTURE FROM NOTION
    # ============================================================
    def get_structure(self, db_id: str) -> Dict[str, Any]:
        schema = self.notion.databases.retrieve(database_id=db_id)
        raw_props = schema.get("properties", {})

        formatted = {}
        for name, spec in raw_props.items():
            formatted[name] = spec.get("type")

        return {
            "db_id": db_id,
            "properties": formatted,
            "property_count": len(formatted),
        }

    # ============================================================
    # COMPARE EXPECTED STRUCTURE WITH NOTION STRUCTURE
    # ============================================================
    def compare(self, expected: Dict[str, str], actual: Dict[str, str]) -> Dict[str, Any]:
        missing = []
        mismatched_types = []
        extra = []

        # Check missing + type mismatch
        for prop, expected_type in expected.items():
            if prop not in actual:
                missing.append(prop)
            else:
                if actual[prop] != expected_type:
                    mismatched_types.append(
                        {"property": prop,
                         "expected": expected_type,
                         "actual": actual[prop]}
                    )

        # Check unexpected properties
        for prop in actual:
            if prop not in expected:
                extra.append(prop)

        return {
            "missing_properties": missing,
            "mismatched_types": mismatched_types,
            "extra_properties": extra,
        }

    # ============================================================
    # MASTER STRUCTURE CHECK
    # ============================================================
    def run_structure_check(self, db_id: str, expected_props: Dict[str, str]):
        actual = self.get_structure(db_id)
        comparison = self.compare(expected_props, actual["properties"])

        return {
            "db_id": db_id,
            "actual_property_count": actual["property_count"],
            "expected_property_count": len(expected_props),
            "differences": comparison,
        }
