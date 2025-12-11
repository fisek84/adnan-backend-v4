import json
from pathlib import Path
from typing import Dict, Any

# Putanja: backend/services/adnan_ai/personality.json
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

    # -------------------------------
    # LOAD OR INITIALIZE
    # -------------------------------
    def _load_or_init(self) -> Dict[str, Any]:
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

        # Ensure all keys exist
        changed = False
        for key, default_val in DEFAULT_PERSONALITY.items():
            if key not in data or not isinstance(data[key], list):
                data[key] = list(default_val)
                changed = True

        if changed:
            self._save(data)

        return data

    # -------------------------------
    # SAVE
    # -------------------------------
    def _save(self, data: Dict[str, Any]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # -------------------------------
    # CATEGORY CLASSIFIER
    # -------------------------------
    def _classify_statement(self, text: str) -> str:
        t = text.lower()

        if any(k in t for k in ["život", "zivot", "svijeta", "svijet", "smisao", "filozof", "filozofija"]):
            return "philosophy"

        if any(k in t for k in ["vrijednost", "vrijednosti", "princip", "integritet", "poštenje", "postenje"]):
            return "values"

        if any(k in t for k in ["mindset", "psiholog", "psihologija", "podsvjes", "podsvijest", "ego"]):
            return "psychology"

        if any(k in t for k in ["biznis", "posao", "strategija", "rast", "skaliranje", "prodaja", "kpi"]):
            return "business_mind"

        if any(k in t for k in ["komuniciram", "pričam", "pricam", "govorim", "pišem", "pisem", "stil komunikacije"]):
            return "communication_style"

        if any(k in t for k in ["odluku", "odlučujem", "odlucujem", "decision", "framework"]):
            return "decision_frameworks"

        if any(k in t for k in ["emocija", "emocije", "osjećam", "osjecam", "reakcija", "strah", "tuga", "ljutnja"]):
            return "emotional_profile"

        if any(k in t for k in ["pravilo", "pravila", "nikad", "uvijek", "za mene važi", "za mene vazi"]):
            return "personal_rules"

        return "values"

    # -------------------------------
    # ORIGINAL learn_from_text  (AI auto mode)
    # -------------------------------
    def learn_from_text(self, text: str) -> Dict[str, Any]:
        category = self._classify_statement(text)
        entry = text.strip()

        if not entry:
            return {"stored": False, "reason": "empty_text", "category": None}

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

    # -------------------------------
    # NEW → REQUIRED BY GATEWAY
    # -------------------------------
    def add_trait(self, category: str, text: str):
        """ manual teach_personality input """
        if category not in self.personality:
            raise ValueError(f"Unknown personality category: {category}")

        text = text.strip()
        if not text:
            return False

        if text not in self.personality[category]:
            self.personality[category].append(text)
            self._save(self.personality)
            return True

        return False

    # -------------------------------
    # REQUIRED BY GATEWAY
    # -------------------------------
    def get_personality(self):
        return self.personality

    # -------------------------------
    # REQUIRED BY GATEWAY
    # -------------------------------
    def reset(self):
        """ Full wipe → restore defaults """
        self.personality = {k: list(v) for k, v in DEFAULT_PERSONALITY.items()}
        self._save(self.personality)
