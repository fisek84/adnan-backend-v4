import json
from pathlib import Path
from typing import Dict, Any

# ROOT: services/decision_engine/personality_engine.py
BASE_PATH = Path(__file__).resolve().parent.parent.parent / "adnan_ai"
PERSONALITY_FILE = BASE_PATH / "personality.json"


# ==============================
# DEFAULT PERSONALITY STRUCTURE
# ==============================
DEFAULT_PERSONALITY = {
    "values": [],
    "philosophy": [],
    "psychology": [],
    "business_mind": [],
    "communication_style": [],
    "decision_frameworks": [],
    "emotional_profile": [],
    "personal_rules": [],
}


# ==============================
# PERSONALITY ENGINE (Adnan Clone)
# ==============================
class PersonalityEngine:
    def __init__(self):
        self.file_path = PERSONALITY_FILE
        self.personality = self._load_or_initialize()

    # ---------------------------------------------------------------
    # LOAD OR INITIALIZE
    # ---------------------------------------------------------------
    def _load_or_initialize(self) -> Dict[str, Any]:
        """
        Loads personality.json if it exists, otherwise writes
        a new clean personality file.
        Also ensures all keys exist.
        """
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

        # ensure full schema
        changed = False
        for key, default_value in DEFAULT_PERSONALITY.items():
            if key not in data or not isinstance(data[key], list):
                data[key] = list(default_value)
                changed = True

        if changed:
            self._save(data)

        return data

    # ---------------------------------------------------------------
    # SAVE
    # ---------------------------------------------------------------
    def _save(self, data: Dict[str, Any]):
        """Write updated personality.json to disk."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ---------------------------------------------------------------
    # CATEGORY CLASSIFIER
    # ---------------------------------------------------------------
    def _classify_statement(self, text: str) -> str:
        """
        Lightweight heuristic classification into personality buckets.
        """

        t = text.lower()

        # philosophy
        if any(
            k in t
            for k in [
                "život",
                "zivot",
                "svijeta",
                "svijet",
                "smisao",
                "filozof",
                "filozofija",
            ]
        ):
            return "philosophy"

        # values / principles
        if any(
            k in t
            for k in [
                "vrijednost",
                "vrijednosti",
                "princip",
                "principi",
                "integritet",
                "poštenje",
                "postenje",
            ]
        ):
            return "values"

        # psychology / mindset
        if any(
            k in t
            for k in [
                "mindset",
                "psiholog",
                "psihologija",
                "podsvjes",
                "podsvijest",
                "ego",
            ]
        ):
            return "psychology"

        # business mind
        if any(
            k in t
            for k in [
                "biznis",
                "posao",
                "strategija",
                "strategiju",
                "rast",
                "skaliranje",
                "prodaja",
                "kpi",
                "leadership",
                "vođenje",
                "vodjenje",
            ]
        ):
            return "business_mind"

        # communication style
        if any(
            k in t
            for k in [
                "komuniciram",
                "kako pričam",
                "kako pricam",
                "govorim",
                "pišem",
                "pisem",
                "stil komunikacije",
            ]
        ):
            return "communication_style"

        # decision frameworks
        if any(
            k in t
            for k in [
                "odluku",
                "odluke",
                "odlučujem",
                "odlucujem",
                "decision",
                "framework",
                "pravilo odlučivanja",
                "pravilo odlucivanja",
            ]
        ):
            return "decision_frameworks"

        # emotions
        if any(
            k in t
            for k in [
                "emocija",
                "emocije",
                "osjećam",
                "osjecam",
                "reakcija",
                "reagujem",
                "strah",
                "tuga",
                "ljutnja",
            ]
        ):
            return "emotional_profile"

        # personal rules
        if any(
            k in t
            for k in [
                "pravilo",
                "pravila",
                "nikad",
                "uvijek",
                "za mene važi",
                "za mene vazi",
            ]
        ):
            return "personal_rules"

        # default fallback
        return "values"

    # ---------------------------------------------------------------
    # LEARNING: Add new personality trait
    # ---------------------------------------------------------------
    def learn_from_text(self, text: str) -> Dict[str, Any]:
        """
        Automatically classify + store a new personality trait.
        """
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

        return {"stored": stored, "category": category, "text": entry}

    # ---------------------------------------------------------------
    # MANUAL ADD TRAIT (used by /ops/teach_personality)
    # ---------------------------------------------------------------
    def add_trait(self, category: str, text: str):
        """
        Manual category injection — user forces the category.
        """
        if category not in self.personality:
            raise ValueError(f"Unknown personality category: {category}")

        clean = text.strip()
        if clean and clean not in self.personality[category]:
            self.personality[category].append(clean)
            self._save(self.personality)

    # ---------------------------------------------------------------
    # GET FULL PERSONALITY STRUCTURE
    # ---------------------------------------------------------------
    def get_personality(self) -> Dict[str, Any]:
        return self.personality

    # ---------------------------------------------------------------
    # RESET PERSONALITY
    # ---------------------------------------------------------------
    def reset(self):
        """Reset entire personality to empty defaults."""
        self.personality = {k: [] for k in DEFAULT_PERSONALITY.keys()}
        self._save(self.personality)
