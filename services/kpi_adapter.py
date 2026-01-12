# services/kpi_adapter.py
from __future__ import annotations

import logging
from typing import Dict, Any, Mapping

from .external_system_interface import ExternalSystemInterface

logger = logging.getLogger(__name__)


class KPIAdapter(ExternalSystemInterface):
    """
    Adapter za KPI platformu.
    Trenutno: stub implementacija.
    """

    def fetch_data(self) -> Dict[str, Any]:
        return {
            "revenue": 100000,
            "cost": 50000,
            "profit_margin": 50,
        }

    def send_data(self, data: Mapping[str, Any]) -> bool:
        if data is None or not isinstance(data, Mapping):
            raise TypeError("data must be a mapping (dict-like).")

        required = ("revenue", "cost", "profit_margin")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Missing required KPI fields: {missing}")

        # Stub: simulacija uspješnog slanja
        logger.info("Sending KPI payload: keys=%s", list(data.keys()))
        return True
