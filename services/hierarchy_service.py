from datetime import datetime, timezone
from typing import Dict, List, Optional


class HierarchyError(Exception):
    """Error related to invalid hierarchy operations."""
    pass


class HierarchyService:
    """
    Evolia HierarchyService v2.0 (PRO)
    -----------------------------------------------
    Upravljanje hijerarhijskim strukturama:
    - Parent → Children odnosi
    - automatska propagacija promjena
    - sprečavanje petlji (cikličnih veza)
    - centralizovano skladište hijerarhije
    """

    def __init__(self):
        self.relations: Dict[str, List[str]] = {}  # parent_id → [child_ids]
        self.timestamps: Dict[str, str] = {}       # entity_id → updated

    # ---------------------------------------------------------
    # UTILITIES
    # ---------------------------------------------------------
    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    # ---------------------------------------------------------
    # QUERY METHODS
    # ---------------------------------------------------------
    def get_children(self, parent_id: str) -> List[str]:
        return self.relations.get(parent_id, [])

    def get_parents(self, entity_id: str) -> List[str]:
        return [p for p, children in self.relations.items() if entity_id in children]

    def has_parent(self, parent_id: str, child_id: str) -> bool:
        return child_id in self.relations.get(parent_id, [])

    # ---------------------------------------------------------
    # CYCLE CHECK
    # ---------------------------------------------------------
    def _would_create_cycle(self, parent: str, child: str) -> bool:
        """
        Provjera da li će nova veza stvoriti hijerarhijsku petlju.
        """
        stack = [child]

        while stack:
            current = stack.pop()
            if current == parent:
                return True
            stack.extend(self.get_children(current))

        return False

    # ---------------------------------------------------------
    # CORE OPERATIONS
    # ---------------------------------------------------------
    def link(self, parent_id: str, child_id: str):
        """
        Kreira Parent → Child odnos.
        """
        if parent_id == child_id:
            raise HierarchyError("Element cannot be its own parent.")

        if self._would_create_cycle(parent_id, child_id):
            raise HierarchyError("This operation would create a hierarchy cycle.")

        if parent_id not in self.relations:
            self.relations[parent_id] = []

        if child_id not in self.relations[parent_id]:
            self.relations[parent_id].append(child_id)

        self.timestamps[parent_id] = self._now()
        self.timestamps[child_id] = self._now()

        return {
            "status": "linked",
            "parent": parent_id,
            "child": child_id
        }

    def unlink(self, parent_id: str, child_id: str):
        """
        Uklanja Parent → Child odnos.
        """
        if parent_id in self.relations:
            if child_id in self.relations[parent_id]:
                self.relations[parent_id].remove(child_id)

        self.timestamps[parent_id] = self._now()
        self.timestamps[child_id] = self._now()

        return {
            "status": "unlinked",
            "parent": parent_id,
            "child": child_id
        }

    # ---------------------------------------------------------
    # BULK OPERATIONS
    # ---------------------------------------------------------
    def replace_children(self, parent_id: str, new_children: List[str]):
        """
        Zamjenjuje kompletnu listu djece za parenta.
        Sprečava cikluse.
        """
        for new_child in new_children:
            if self._would_create_cycle(parent_id, new_child):
                raise HierarchyError(f"Cycle prevented for child {new_child}")

        self.relations[parent_id] = list(new_children)
        self.timestamps[parent_id] = self._now()

        return {
            "status": "replaced_children",
            "parent": parent_id,
            "children": new_children
        }

    # ---------------------------------------------------------
    # METADATA
    # ---------------------------------------------------------
    def get_info(self, entity_id: str) -> Dict[str, Any]:
        return {
            "entity": entity_id,
            "parents": self.get_parents(entity_id),
            "children": self.get_children(entity_id),
            "updated_at": self.timestamps.get(entity_id)
        }

    def update(self):
        """
        Legacy API — kept for compatibility.
        """
        return {
            "status": "hierarchy_engine_active",
            "entities_tracked": len(self.timestamps),
            "relations_count": len(self.relations)
        }