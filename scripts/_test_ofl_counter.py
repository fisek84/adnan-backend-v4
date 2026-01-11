import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.outcome_feedback_loop_service import OutcomeFeedbackLoopService as S  # noqa: E402


svc = S()
payload = {
    "decision_id": "dec_counter_001",
    "timestamp": "2026-01-10T00:00:00Z",
    "recommendation_summary": "counter test (RETURNING id)",
    "accepted": True,
    "executed": False,
    "owner": "system",
}

print("run#1:", svc.schedule_reviews_for_decision(decision_record=payload))
print("run#2:", svc.schedule_reviews_for_decision(decision_record=payload))
