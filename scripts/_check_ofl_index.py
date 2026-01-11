import os
import sqlalchemy as sa
from sqlalchemy import inspect

eng = sa.create_engine(os.environ["DATABASE_URL"], future=True)
insp = inspect(eng)

idx = insp.get_indexes("outcome_feedback_loop")
print("all_indexes:", [i.get("name") for i in idx])

target = [i for i in idx if i.get("name") == "uq_outcome_feedback_loop_decision_id_window_days"]
print("index_found:", len(target))
if target:
    print("index_def:", target[0])
