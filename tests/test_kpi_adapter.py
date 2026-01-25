# tests/test_kpi_adapter.py

from __future__ import annotations

from typing import Mapping, Any
import pytest

from services.kpi_adapter import KPIAdapter


def test_kpi_adapter_fetch_data_returns_mapping_with_expected_keys():
    adapter = KPIAdapter()
    data = adapter.fetch_data()

    assert isinstance(data, Mapping)
    assert set(data.keys()) >= {"revenue", "cost", "profit_margin"}
    assert isinstance(data["revenue"], (int, float))
    assert isinstance(data["cost"], (int, float))
    assert isinstance(data["profit_margin"], (int, float))


def test_kpi_adapter_send_data_returns_bool_true_for_valid_payload():
    adapter = KPIAdapter()

    payload: dict[str, Any] = {
        "revenue": 100000,
        "cost": 50000,
        "profit_margin": 50,
    }

    result = adapter.send_data(payload)
    assert isinstance(result, bool)
    assert result is True


@pytest.mark.parametrize(
    "bad_payload",
    [
        None,
        "not-a-dict",
        123,
        ["list"],
    ],
)
def test_kpi_adapter_send_data_rejects_non_mapping_payloads(bad_payload):
    adapter = KPIAdapter()

    # Trenutni KPIAdapter uvijek vraća True; ovaj test definira očekivanje
    # za produkcijski adapter: ne prihvata nevalidan payload.
    with pytest.raises((TypeError, ValueError)):
        adapter.send_data(bad_payload)  # type: ignore[arg-type]
