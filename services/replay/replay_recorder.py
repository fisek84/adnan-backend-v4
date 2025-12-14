# services/replay/replay_recorder.py

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional


# ============================================================
# REPLAY RECORDER (KANONSKI, READ-ONLY)
# ============================================================

class ReplayRecorder:
    """
    Records decision-relevant snapshots for replay & simulation.

    RULES:
    - READ-ONLY
    - NO execution
    - NO CSI mutation
    - Append-only
    """

    BASE_PATH = Path(__file__).resolve().parent.parent.parent / "adnan_ai" / "replay"
    LOG_FILE = BASE_PATH / "replay_log.jsonl"

    def __init__(self):
        self.BASE_PATH.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        intent: Optional[Dict[str, Any]],
        csi_state: str,
        autonomy_signal: Optional[Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = {
            "ts": time.time(),
            "intent": intent,
            "csi_state": csi_state,
            "autonomy_signal": self._serialize_autonomy(autonomy_signal),
            "metadata": metadata or {},
        }

        with open(self.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _serialize_autonomy(self, autonomy_signal: Optional[Any]) -> Optional[Dict[str, Any]]:
        if autonomy_signal is None:
            return None

        # STRICT: autonomy signal must be data-only
        return {
            "proposal": getattr(autonomy_signal, "proposal", None),
            "loop": getattr(autonomy_signal, "loop", None),
            "recovery": getattr(autonomy_signal, "recovery", None),
        }
