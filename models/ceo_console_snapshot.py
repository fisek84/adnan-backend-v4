from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class CeoConsoleSnapshotResponse(BaseModel):
    system: Dict[str, Any] = Field(default_factory=dict)
    identity: Dict[str, Any] = Field(default_factory=dict)
    mode: Dict[str, Any] = Field(default_factory=dict)
    state: Dict[str, Any] = Field(default_factory=dict)
    approvals: Dict[str, Any] = Field(default_factory=dict)

    # Reliability additions (CEO Console must never render empty UI)
    snapshot_meta: Dict[str, Any] = Field(default_factory=dict)
    knowledge_snapshot: Dict[str, Any] = Field(default_factory=dict)
    ceo_dashboard_snapshot: Dict[str, Any] = Field(default_factory=dict)

    # Legacy compatibility
    goals_summary: List[Any] = Field(default_factory=list)
    tasks_summary: List[Any] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")
