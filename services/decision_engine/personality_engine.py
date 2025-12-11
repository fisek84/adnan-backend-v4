import json
from pathlib import Path
from typing import Dict, Any

BASE_PATH = Path(__file__).resolve().parent.parent.parent / "adnan_ai"
PERSONALITY_FILE = BASE_PATH / "personality.json"


DEFAULT_PERSONALITY = {
    "values": [],
    "philosophy": [],
    "psychology": [],
    "business_mind": [],
    "communication_style": [],
    "decision_frameworks": [],
    "emotional_profile": [],
    "personal_rules": []
}


class PersonalityEngine:
    def __init__(self):
        self.base_path = BASE_PATH
        self.file_path = PERSONALITY_FILE
        self.personality: Dict[str, Any] = self._load_or_init()

    def _load_or_init(self) -> Dict[str, Any]:
        if self.file_path.exists():
            with open(self.file_path, "r", encoding="utf-8-sig") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = {}
        else:
            data = {}

        # osiguraj da svi ključevi postoje
        changed = False
        for key, default_val in DEFAULT_PERSONALITY.items():
            if key not in data or not isinstance(data[key], list):
                data[key] = list(default_val)
                changed = True

        if changed:
            self._save(data)

        return data

    def _save(self, data: Dict[str, Any]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _classify_statement(self, text: str) -> str:
        """
        Jako lagan heuristički classifier koji odlučuje
        u koji personality bucket ide ova rečenica.
        """
        t = text.lower()

        # filozofija / pogled na svijet
        if any(k in t for k in ["život", "zivot", "svijeta", "svijet", "smisao", "filozof", "filozofija"]):
            return "philosophy"

        # vrijednosti / principi
        if any(k in t for k in ["vrijednost", "vrijednosti", "princip", "principi", "integritet", "poštenje", "postenje"]):
            return "values"

        # psihologija / mindset
        if any(k in t for k in ["mindset", "psiholog", "psihologija", "podsvjes", "podsvijest", "ego"]):
            return "psychology"

        # biznis / strategija
        if any(k in t for k in ["biznis", "posao", "strategija", "strategiju", "rast", "skaliranje", "prodaja", "kpi"]):
            return "business_mind"

        # stil komunikacije
        if any(k in t for k in ["komuniciram", "kako pričam", "kako pricam", "govorim", "pišem", "pisem", "stil komunikacije"]):
            return "communication_style"

        # odlučivanje / framework
        if any(k in t for k in ["odluku", "odlučujem", "odlucujem", "decision", "framework", "pravilo odlučivanja", "pravilo odlucivanja"]):
            return "decision_frameworks"

        # emocije
        if any(k in t for k in ["emocija", "emocije", "osjećam", "osjecam", "reakcija", "reagujem", "strah", "ljutnja", "tuga"]):
            return "emotional_profile"

        # lična pravila
        if any(k in t for k in ["pravilo", "pravila", "nikad", "uvijek", "za mene važi", "za mene vazi"]):
            return "personal_rules"

        # default bucket
        return "values"

    def learn_from_text(self, text: str) -> Dict[str, Any]:
        """
        Sačuvaj novu informaciju o CEO / Adnanu u personality.json
        i vrati metapodatke o tome šta je spremljeno.
        """
        category = self._classify_statement(text)
        entry = text.strip()

        if not entry:
            return {
                "stored": False,
                "reason": "empty_text",
                "category": None
            }

        if entry not in self.personality[category]:
            self.personality[category].append(entry)
            self._save(self.personality)
            stored = True
        else:
            stored = False

        return {
            "stored": stored,
            "category": category,
            "text": entry
        }
