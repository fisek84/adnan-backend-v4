import os
import sqlalchemy as sa

eng = sa.create_engine(os.environ["DATABASE_URL"], future=True)

q = sa.text("""
SELECT decision_id, evaluation_window_days, timestamp, review_at
FROM outcome_feedback_loop
WHERE decision_id = :did
ORDER BY evaluation_window_days
""")

with eng.begin() as c:
    rows = c.execute(q, {"did": "dec_unique_003_new"}).fetchall()

print("rows:", len(rows))
for r in rows:
    print(dict(r._mapping))
