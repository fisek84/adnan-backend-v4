# services/integration_manager.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, MutableMapping, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class IntegrationAdapter(Protocol):
    """
    Minimalni kontrakt koji adapter mora imati.
    Namjerno samo ono što sistem treba: fetch_data + send_data.
    """

    def fetch_data(self) -> Mapping[str, Any]: ...
    def send_data(self, data: Mapping[str, Any]) -> bool: ...


class AdapterRegistrationError(ValueError):
    """Neispravna registracija adaptera (ime/instanca/kontrakt)."""


class IntegrationRunError(RuntimeError):
    """Greška tokom izvršenja adaptera (fetch/send)."""


@dataclass(slots=True)
class IntegrationManager:
    """
    Centralni orkestrator integracija preko adaptera.

    Test očekuje:
      - manager.adapters['KPI'] pristup
      - add_adapter('KPI', adapter)
      - fetch_and_send_data() poziva fetch_data() i send_data(data)
      - KeyError ako nema registrovanih adaptera
    """

    adapters: MutableMapping[str, IntegrationAdapter] = field(default_factory=dict)
    fail_fast: bool = True  # produkcijski default: prekini na prvoj grešci

    def add_adapter(self, name: str, adapter: IntegrationAdapter) -> None:
        normalized = self._normalize_name(name)
        self._validate_adapter(adapter)

        if normalized in self.adapters:
            # U produkciji je bolje eksplicitno failati nego “tiho” pregaziti.
            raise AdapterRegistrationError(
                f"Adapter '{normalized}' is already registered."
            )

        self.adapters[normalized] = adapter
        logger.info(
            "Integration adapter registered: name=%s type=%s",
            normalized,
            type(adapter).__name__,
        )

    def fetch_and_send_data(self) -> Dict[str, bool]:
        """
        Pokreće fetch->send za sve adaptere.
        Vraća mapu {adapter_name: send_result_bool} radi observability.
        (Test ne koristi return, ali ne smeta.)
        """
        if not self.adapters:
            raise KeyError("No adapters registered.")

        results: Dict[str, bool] = {}
        errors: Dict[str, Exception] = {}

        for name, adapter in self.adapters.items():
            try:
                data = self._safe_fetch(name, adapter)
                ok = self._safe_send(name, adapter, data)
                results[name] = ok
            except (
                Exception
            ) as exc:  # namjerno hvatanje, da možemo agregirati/izlogovati
                logger.exception(
                    "Integration adapter failed: name=%s error=%s", name, exc
                )
                errors[name] = exc
                if self.fail_fast:
                    raise IntegrationRunError(f"Adapter '{name}' failed.") from exc

        if errors:
            # Ako nije fail_fast, propagiramo zbirno stanje kroz izuzetak
            # (ali ostavljamo rezultate koji su uspjeli).
            raise IntegrationRunError(
                f"{len(errors)} adapter(s) failed: {', '.join(errors.keys())}"
            )

        return results

    # -------------------------
    # Internal helpers
    # -------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str):
            raise AdapterRegistrationError("Adapter name must be a string.")
        normalized = name.strip()
        if not normalized:
            raise AdapterRegistrationError("Adapter name must be non-empty.")
        return normalized

    @staticmethod
    def _validate_adapter(adapter: Any) -> None:
        if adapter is None:
            raise AdapterRegistrationError("Adapter instance must not be None.")

        # Pouzdana runtime validacija bez oslanjanja na Protocol/isinstance.
        fetch = getattr(adapter, "fetch_data", None)
        send = getattr(adapter, "send_data", None)

        if not callable(fetch):
            raise AdapterRegistrationError(
                "Adapter must implement callable fetch_data()."
            )
        if not callable(send):
            raise AdapterRegistrationError(
                "Adapter must implement callable send_data(data)."
            )

    @staticmethod
    def _safe_fetch(name: str, adapter: IntegrationAdapter) -> Mapping[str, Any]:
        logger.debug("Fetching data via adapter: name=%s", name)
        data = adapter.fetch_data()
        if data is None:
            raise IntegrationRunError(
                f"Adapter '{name}' returned None from fetch_data()."
            )
        if not isinstance(data, Mapping):
            raise IntegrationRunError(
                f"Adapter '{name}' must return a mapping/dict from fetch_data()."
            )
        return data

    @staticmethod
    def _safe_send(
        name: str, adapter: IntegrationAdapter, data: Mapping[str, Any]
    ) -> bool:
        logger.debug(
            "Sending data via adapter: name=%s keys=%s", name, list(data.keys())
        )
        ok = adapter.send_data(data)
        if not isinstance(ok, bool):
            raise IntegrationRunError(
                f"Adapter '{name}' must return bool from send_data(data)."
            )
        return ok
