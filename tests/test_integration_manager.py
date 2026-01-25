import pytest
from services.kpi_adapter import KPIAdapter
from services.integration_manager import IntegrationManager
from unittest.mock import MagicMock


@pytest.fixture
def integration_manager():
    manager = IntegrationManager()
    # Kreiramo KPIAdapter
    kpi_adapter = KPIAdapter()
    # Dodajemo ga u IntegrationManager
    manager.add_adapter("KPI", kpi_adapter)
    return manager


def test_fetch_and_send_data(integration_manager):
    # Mocking external system interface method responses
    kpi_adapter = integration_manager.adapters["KPI"]

    # Pretpostavljamo da je fetch_data uspešan
    kpi_adapter.fetch_data = MagicMock(
        return_value={"revenue": 100000, "cost": 50000, "profit_margin": 50}
    )
    kpi_adapter.send_data = MagicMock(return_value=True)

    # Pozivamo funkciju fetch_and_send_data
    integration_manager.fetch_and_send_data()

    # Proveravamo da li su pozvane funkcije sa ispravnim rezultatima
    kpi_adapter.fetch_data.assert_called_once()
    kpi_adapter.send_data.assert_called_once_with(
        {"revenue": 100000, "cost": 50000, "profit_margin": 50}
    )

    # Proveravamo ispis (ako treba, može se usmeriti na logove umesto printa)
    assert kpi_adapter.send_data.return_value is True


def test_integration_with_no_adapter():
    manager = IntegrationManager()

    # Testiramo ponašanje kada nije dodan nijedan adapter
    with pytest.raises(KeyError):
        manager.fetch_and_send_data()
