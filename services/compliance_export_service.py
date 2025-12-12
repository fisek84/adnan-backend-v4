# services/compliance_export_service.py

"""
COMPLIANCE EXPORT SERVICE — FAZA 21 (SNAPSHOT FREEZE)

Uloga:
- kreira jednokratni, nepromjenjivi snapshot sistema
- namijenjen za:
  - audit
  - compliance
  - board / legal
- READ-ONLY
- NEMA izvršenja
- NEMA mutacije stanja
- NEMA automatike
"""

import json
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

from services.observability_service import ObservabilityService
from services.policy_service import PolicyService
from services.rbac_service import RBACService
from services.approval_state_service import ApprovalStateService


EXPORT_BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "compliance_exports"


class ComplianceExportService:
    def __init__(self):
        self.observability = ObservabilityService()
        self.policy = PolicyService()
        self.rbac = RBACService()
        self.approvals = ApprovalStateService()

        EXPORT_BASE_PATH.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # PUBLIC API
    # ============================================================
    def create_snapshot(self) -> Dict[str, Any]:
        """
        Kreira compliance snapshot.
        Snapshot je READ-ONLY artefakt.
        """

        timestamp = datetime.utcnow().isoformat()
        snapshot = {
            "meta": {
                "created_at": timestamp,
                "type": "compliance_snapshot",
                "read_only": True,
            },
            "system_state": {
                "active_decision": self.observability.get_active_decision(),
                "recent_decisions": self.observability.get_decision_outcomes(limit=50),
                "execution_stats": self.observability.get_execution_stats(),
            },
            "governance": {
                "policies": self.policy.get_policy_snapshot(),
                "rbac": self.rbac.get_rbac_snapshot(),
                "approvals": self.approvals.get_overview(),
            },
        }

        file_path = self._persist_snapshot(snapshot, timestamp)

        return {
            "success": True,
            "snapshot_file": str(file_path),
            "created_at": timestamp,
            "read_only": True,
        }

    # ============================================================
    # INTERNAL
    # ============================================================
    def _persist_snapshot(self, snapshot: Dict[str, Any], timestamp: str) -> Path:
        safe_ts = timestamp.replace(":", "-")
        filename = f"compliance_snapshot_{safe_ts}.json"
        file_path = EXPORT_BASE_PATH / filename

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        return file_path
