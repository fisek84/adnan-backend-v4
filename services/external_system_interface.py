from abc import ABC, abstractmethod
from typing import Dict, Any


class ExternalSystemInterface(ABC):
    """
    Apstraktna klasa za interfejs koji se koristi za povezivanje sa spoljnim sistemima.
    Svi adapteri za spoljne sisteme treba da implementiraju ove metode.
    """

    @abstractmethod
    def fetch_data(self) -> Dict[str, Any]:
        """
        Preuzima podatke sa spoljnog sistema.
        Metoda mora biti implementirana u svakom adapteru.
        """
        pass

    @abstractmethod
    def send_data(self, data: Dict[str, Any]) -> bool:
        """
        Šalje podatke u spoljni sistem.
        Metoda mora biti implementirana u svakom adapteru.
        """
        pass
