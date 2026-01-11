from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from services.ceo_alignment_engine import CEOAlignmentEngine
from services.identity_loader import load_ceo_identity_pack
from services.world_state_engine import WorldStateEngine


class ConfigurationError(RuntimeError):
    pass


logger = logging.getLogger("ofl.service")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_first(*names: str) -> Optional[str]:
    for n in names:
        v = os.getenv(n)
        if v and v.strip():
            return v.strip()
    return None


def _parse_iso_datetime(s: Any) -> Optional[datetime]:
    if not isinstance(s, str) or not s.strip():
        return None
    raw = s.strip()
    try:
        raw = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _safe_json_payload(d: Any, max_chars: int = 8000) -> Any:
    """
    JSON/JSONB: moĹľe dict/list direktno.
    TEXT fallback: skraÄ‡eni JSON string.
    """
    try:
        if isinstance(d, (dict, list)):
            s = json.dumps(d, ensure_ascii=False, default=str)
            if len(s) <= max_chars:
                return d
            return s[: max_chars - 1] + "â€¦"
        if isinstance(d, str):
            return d[:max_chars]
        return str(d)[:max_chars]
    except Exception:
        return str(d)[:max_chars]


def _is_bool(x: Any) -> bool:
    return isinstance(x, bool)


def _alignment_payload_from_hash(alignment_snapshot_hash: Any) -> Dict[str, Any]:
    if isinstance(alignment_snapshot_hash, str) and alignment_snapshot_hash.strip():
        return {"alignment_snapshot_hash": alignment_snapshot_hash.strip()}
    return {"alignment_snapshot_hash": None}


def _extract_alignment_score(snapshot: Any) -> Optional[float]:
    """
    OÄŤekuje CEOAlignmentEngine snapshot shape:
      snapshot["strategic_alignment"]["alignment_score"] (int 0..100)
    """
    if not isinstance(snapshot, dict):
        return None
    sa1 = snapshot.get("strategic_alignment")
    if not isinstance(sa1, dict):
        return None
    v = sa1.get("alignment_score")
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except Exception:
        return None


def _extract_risk_level(snapshot: Any) -> Optional[str]:
    """
    OÄŤekuje CEOAlignmentEngine snapshot shape:
      snapshot["law_compliance"]["risk_level"] in {"none","low","medium","high"} (case-insensitive)
    """
    if not isinstance(snapshot, dict):
        return None
    lc = snapshot.get("law_compliance")
    if not isinstance(lc, dict):
        return None
    rl = lc.get("risk_level")
    if isinstance(rl, str) and rl.strip():
        return rl.strip().lower()
    return None


def _risk_level_to_numeric(risk_level: Optional[str]) -> float:
    """
    DeterministiÄŤki mapping za numeric delta_risk.
    """
    m = {"none": 0.0, "low": 1.0, "medium": 2.0, "high": 3.0}
    if not risk_level:
        return 0.0
    return m.get(risk_level.lower(), 0.0)


def _compute_delta_score_and_risk(
    *, alignment_before: Any, alignment_after: Any
) -> Tuple[float, float, List[str]]:
    notes: List[str] = []

    b_score = _extract_alignment_score(alignment_before)
    a_score = _extract_alignment_score(alignment_after)

    b_risk_level = _extract_risk_level(alignment_before)
    a_risk_level = _extract_risk_level(alignment_after)

    if b_score is None:
        notes.append("alignment_before_score_missing")
        b_score_eff = a_score if a_score is not None else 0.0
    else:
        b_score_eff = b_score

    if a_score is None:
        notes.append("alignment_after_score_missing")
        a_score_eff = b_score if b_score is not None else 0.0
    else:
        a_score_eff = a_score

    if b_risk_level is None:
        notes.append("alignment_before_risk_missing")
        b_risk_eff = _risk_level_to_numeric(a_risk_level)
    else:
        b_risk_eff = _risk_level_to_numeric(b_risk_level)

    if a_risk_level is None:
        notes.append("alignment_after_risk_missing")
        a_risk_eff = _risk_level_to_numeric(b_risk_level)
    else:
        a_risk_eff = _risk_level_to_numeric(a_risk_level)

    delta_score = float(a_score_eff - b_score_eff)
    delta_risk = float(a_risk_eff - b_risk_eff)

    return delta_score, delta_risk, notes


def _extract_kpis_from_world_state(world_state_snapshot: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    WorldStateEngine snapshot (services/world_state_engine.py) canonical:
      snapshot["kpis"] = {"summary": [...], "alerts": [...], "as_of": "...Z"}

    Zato je canonical extract:
      - world_state_snapshot["kpis"] ako je dict
      - inaÄŤe None + note
    """
    if not isinstance(world_state_snapshot, dict):
        return None, "world_state_snapshot_not_dict"
    k = world_state_snapshot.get("kpis")
    if isinstance(k, dict):
        return k, "kpis_from_world_state.kpis"
    return None, "kpis_missing_or_not_dict"


def _diff_numeric_kpis(
    *, before: Any, after: Any
) -> Tuple[Dict[str, float], List[str]]:
    """
    DeterministiÄŤki diff: common keys gdje su i before i after numeric (int/float, ne bool).
    Ako shape nije dict -> vraÄ‡a prazno + note.

    Napomena:
      world_state_engine.py kpis shape sadrĹľi liste (summary/alerts),
      pa numeric diff tipiÄŤno neÄ‡e imati output. To je OK i eksplicitno se notira.
    """
    notes: List[str] = []
    if not isinstance(before, dict):
        notes.append("kpi_before_not_dict")
        return {}, notes
    if not isinstance(after, dict):
        notes.append("kpi_after_not_dict")
        return {}, notes

    out: Dict[str, float] = {}
    common = set(before.keys()) & set(after.keys())
    for k in sorted(common, key=lambda x: str(x)):
        b = before.get(k)
        a = after.get(k)
        if isinstance(b, bool) or isinstance(a, bool):
            continue
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            out[str(k)] = float(a) - float(b)

    if not out:
        notes.append("kpi_no_numeric_common_keys")
    return out, notes


@dataclass(frozen=True)
class _SchemaCols:
    id: str
    decision_id: str
    timestamp: str
    review_at: str
    evaluation_window_days: str

    alignment_snapshot_hash: Optional[str]
    behaviour_mode: Optional[str]
    recommendation_type: Optional[str]
    recommendation_summary: str

    accepted: str
    executed: str
    execution_result: Optional[str]
    owner: Optional[str]

    kpi_before: Optional[str]
    kpi_after: Optional[str]
    delta: Optional[str]

    alignment_before: Optional[str]
    alignment_after: Optional[str]
    delta_score: Optional[str]
    delta_risk: Optional[str]
    notes: Optional[str]


class OutcomeFeedbackLoopService:
    """
    outcome_feedback_loop â€” SSOT persistence (DB).

    Kanon:
      - schedule_reviews_for_decision(): INSERT .. ON CONFLICT DO NOTHING (Postgres unique index)
        + RETURNING id za taÄŤan inserted counter.
      - evaluate_due_reviews(): marker evaluacije je delta (JSONB) (nema status kolone)
    """

    TABLE_NAME = "outcome_feedback_loop"
    DEFAULT_REVIEW_DAYS = [7, 14, 30]
    DEFAULT_LIMIT = 50

    UNIQUE_INDEX_ELEMENTS = ("decision_id", "evaluation_window_days")

    # -------------------------
    # ENGINE / TABLE
    # -------------------------
    def _db_url_or_raise(self) -> str:
        db_url = _env_first("DATABASE_URL")
        if not db_url:
            raise ConfigurationError("DATABASE_URL is not set")
        return db_url

    def _engine(self) -> sa.Engine:
        return sa.create_engine(
            self._db_url_or_raise(), pool_pre_ping=True, future=True
        )

    def _table(self, engine: sa.Engine) -> sa.Table:
        md = sa.MetaData()
        return sa.Table(self.TABLE_NAME, md, autoload_with=engine)

    def _require_cols(self, table: sa.Table) -> _SchemaCols:
        cols = {c.name for c in table.columns}

        def req(name: str) -> str:
            if name not in cols:
                raise ConfigurationError(f"schema_missing_required_column:{name}")
            return name

        def opt(name: str) -> Optional[str]:
            return name if name in cols else None

        return _SchemaCols(
            id=req("id"),
            decision_id=req("decision_id"),
            timestamp=req("timestamp"),
            review_at=req("review_at"),
            evaluation_window_days=req("evaluation_window_days"),
            alignment_snapshot_hash=opt("alignment_snapshot_hash"),
            behaviour_mode=opt("behaviour_mode"),
            recommendation_type=opt("recommendation_type"),
            recommendation_summary=req("recommendation_summary"),
            accepted=req("accepted"),
            executed=req("executed"),
            execution_result=opt("execution_result"),
            owner=opt("owner"),
            kpi_before=opt("kpi_before"),
            kpi_after=opt("kpi_after"),
            delta=opt("delta"),
            alignment_before=opt("alignment_before"),
            alignment_after=opt("alignment_after"),
            delta_score=opt("delta_score"),
            delta_risk=opt("delta_risk"),
            notes=opt("notes"),
        )

    # -------------------------
    # CONFIG
    # -------------------------
    def _review_days(self) -> List[int]:
        raw = (os.getenv("OUTCOME_FEEDBACK_LOOP_REVIEW_DAYS") or "").strip()
        if not raw:
            return list(self.DEFAULT_REVIEW_DAYS)

        out: List[int] = []
        for part in raw.split(","):
            p = part.strip()
            if not p:
                continue
            if p.isdigit():
                v = int(p)
                if v > 0:
                    out.append(v)

        return out or list(self.DEFAULT_REVIEW_DAYS)

    # -------------------------
    # PUBLIC API
    # -------------------------
    def schedule_reviews_for_decision(
        self, *, decision_record: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(decision_record, dict) or not decision_record:
            return {"ok": False, "error": "invalid_decision_record"}

        decision_id = decision_record.get("decision_id")
        if not isinstance(decision_id, str) or not decision_id.strip():
            return {"ok": False, "error": "decision_record_missing_decision_id"}
        decision_id = decision_id.strip()

        decided_at = _parse_iso_datetime(decision_record.get("timestamp")) or _utc_now()

        recommendation_summary = decision_record.get("recommendation_summary")
        if (
            not isinstance(recommendation_summary, str)
            or not recommendation_summary.strip()
        ):
            return {
                "ok": False,
                "error": "decision_record_missing_recommendation_summary",
            }
        recommendation_summary = recommendation_summary.strip()

        accepted = decision_record.get("accepted")
        executed = decision_record.get("executed")
        if not _is_bool(accepted):
            return {
                "ok": False,
                "error": "decision_record_missing_or_invalid_accepted_bool",
            }
        if not _is_bool(executed):
            return {
                "ok": False,
                "error": "decision_record_missing_or_invalid_executed_bool",
            }

        review_days = self._review_days()

        engine = self._engine()
        table = self._table(engine)
        sc = self._require_cols(table)

        inserted = 0
        skipped = 0
        errors: List[str] = []

        alignment_snapshot_hash = decision_record.get("alignment_snapshot_hash")
        behaviour_mode = decision_record.get("behaviour_mode")
        recommendation_type = decision_record.get("recommendation_type")
        execution_result = decision_record.get("execution_result")
        owner = decision_record.get("owner")

        # Optional: caller can pass:
        # - kpi_before (dict preferred)
        # - alignment_before (dict preferred)
        kpi_before = decision_record.get("kpi_before")
        alignment_before_payload = decision_record.get("alignment_before")

        with engine.begin() as conn:
            is_pg = conn.dialect.name == "postgresql"

            for d in review_days:
                due = decided_at + timedelta(days=int(d))

                row: Dict[str, Any] = {
                    sc.decision_id: decision_id,
                    sc.timestamp: decided_at,
                    sc.review_at: due,
                    sc.evaluation_window_days: int(d),
                    sc.recommendation_summary: recommendation_summary,
                    sc.accepted: bool(accepted),
                    sc.executed: bool(executed),
                }

                if (
                    sc.alignment_snapshot_hash
                    and isinstance(alignment_snapshot_hash, str)
                    and alignment_snapshot_hash.strip()
                ):
                    row[sc.alignment_snapshot_hash] = alignment_snapshot_hash.strip()
                if (
                    sc.behaviour_mode
                    and isinstance(behaviour_mode, str)
                    and behaviour_mode.strip()
                ):
                    row[sc.behaviour_mode] = behaviour_mode.strip()
                if (
                    sc.recommendation_type
                    and isinstance(recommendation_type, str)
                    and recommendation_type.strip()
                ):
                    row[sc.recommendation_type] = recommendation_type.strip()
                if (
                    sc.execution_result
                    and isinstance(execution_result, str)
                    and execution_result.strip()
                ):
                    row[sc.execution_result] = execution_result.strip()
                if sc.owner and isinstance(owner, str) and owner.strip():
                    row[sc.owner] = owner.strip()

                if sc.kpi_before and kpi_before is not None:
                    row[sc.kpi_before] = _safe_json_payload(kpi_before)

                # alignment_before at decision time (preferred if provided)
                if sc.alignment_before:
                    if isinstance(alignment_before_payload, dict) and alignment_before_payload:
                        row[sc.alignment_before] = _safe_json_payload(alignment_before_payload)
                    else:
                        # fallback: at least keep hash reference payload
                        row[sc.alignment_before] = _safe_json_payload(
                            _alignment_payload_from_hash(alignment_snapshot_hash)
                        )

                try:
                    if is_pg:
                        stmt = (
                            pg_insert(table)
                            .values(**row)
                            .on_conflict_do_nothing(
                                index_elements=list(self.UNIQUE_INDEX_ELEMENTS)
                            )
                            .returning(table.c[sc.id])
                        )
                        res = conn.execute(stmt)
                        returned_ids = res.scalars().all()
                        if returned_ids:
                            inserted += len(returned_ids)
                        else:
                            skipped += 1
                    else:
                        conn.execute(sa.insert(table).values(**row))
                        inserted += 1
                except Exception as e:
                    errors.append(f"insert_failed_days={d}:{e}")

        logger.info(
            "ofl_schedule_summary",
            extra={
                "decision_id": decision_id,
                "inserted": inserted,
                "skipped": skipped,
                "errors": len(errors),
                "review_days": review_days,
            },
        )

        return {
            "ok": len(errors) == 0,
            "decision_id": decision_id,
            "inserted": inserted,
            "skipped": skipped,
            "errors": errors,
            "review_days": review_days,
        }

    def evaluate_due_reviews(self, *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
        limit_eff = int(limit or 0)
        if limit_eff <= 0:
            limit_eff = self.DEFAULT_LIMIT

        engine = self._engine()
        table = self._table(engine)
        sc = self._require_cols(table)

        marker_col: Optional[str]
        if sc.delta:
            marker_col = sc.delta
        elif sc.kpi_after:
            marker_col = sc.kpi_after
        else:
            return {"ok": False, "error": "schema_missing_delta_and_kpi_after_columns"}

        now = _utc_now()

        # Evaluate "after" snapshots ONCE per run
        identity_pack = load_ceo_identity_pack()
        world_state_snapshot = WorldStateEngine().build_snapshot()
        alignment_after_snapshot = CEOAlignmentEngine().evaluate(
            identity_pack, world_state_snapshot
        )

        kpis_after, kpi_after_note = _extract_kpis_from_world_state(world_state_snapshot)

        marker_expr = table.c[marker_col].is_(None)

        select_cols = [
            table.c[sc.id],
            table.c[sc.decision_id],
            table.c[sc.evaluation_window_days],
        ]
        if sc.kpi_before:
            select_cols.append(table.c[sc.kpi_before])
        if sc.alignment_before:
            select_cols.append(table.c[sc.alignment_before])
        if sc.alignment_snapshot_hash:
            select_cols.append(table.c[sc.alignment_snapshot_hash])

        sel = (
            sa.select(*select_cols)
            .where(sa.and_(table.c[sc.review_at] <= now, marker_expr))
            .order_by(table.c[sc.review_at].asc())
            .limit(limit_eff)
        )

        processed = 0
        updated = 0
        update_errors: List[str] = []

        with engine.begin() as conn:
            rows = conn.execute(sel).fetchall()
            processed = len(rows)

            for row in rows:
                rid = row[0]
                decision_id = row[1]
                window_days = row[2]

                kpi_before_value: Any = None
                alignment_before_value: Any = None
                alignment_hash_value: Any = None

                idx = 3
                if sc.kpi_before:
                    kpi_before_value = row[idx]
                    idx += 1
                if sc.alignment_before:
                    alignment_before_value = row[idx]
                    idx += 1
                if sc.alignment_snapshot_hash:
                    alignment_hash_value = row[idx] if idx < len(row) else None

                delta_score_val, delta_risk_val, delta_notes = _compute_delta_score_and_risk(
                    alignment_before=alignment_before_value,
                    alignment_after=alignment_after_snapshot,
                )

                # KPI delta (numeric only, deterministic)
                kpi_deltas: Dict[str, float] = {}
                kpi_delta_notes: List[str] = []
                if kpis_after is not None:
                    kpi_deltas, kpi_delta_notes = _diff_numeric_kpis(
                        before=kpi_before_value, after=kpis_after
                    )
                else:
                    kpi_delta_notes.append("kpis_after_missing")

                notes_parts = [
                    f"evaluated_at={now.isoformat()}",
                    "source=alignment_engine+world_state_engine",
                    f"kpi_extract_note={kpi_after_note}",
                ]
                if isinstance(alignment_hash_value, str) and alignment_hash_value.strip():
                    notes_parts.append(
                        f"alignment_snapshot_hash={alignment_hash_value.strip()}"
                    )
                if delta_notes:
                    notes_parts.append("flags=" + ",".join(delta_notes))
                if kpi_delta_notes:
                    notes_parts.append("kpi_flags=" + ",".join(kpi_delta_notes))

                upd: Dict[str, Any] = {}

                if sc.kpi_after:
                    # store canonical kpis dict as-is (JSONB)
                    upd[sc.kpi_after] = _safe_json_payload(kpis_after)

                if sc.delta:
                    upd[sc.delta] = _safe_json_payload(
                        {
                            "evaluation_result": "evaluated",
                            "evaluated_at": now.isoformat(),
                            "decision_id": decision_id,
                            "evaluation_window_days": int(window_days),
                            "alignment": {
                                "delta_score": float(delta_score_val),
                                "delta_risk": float(delta_risk_val),
                            },
                            "kpi_extract_note": kpi_after_note,
                            "kpi_deltas_numeric": kpi_deltas,
                            "note": "delta is marker+summary; numeric deltas are also in delta_score/delta_risk columns if present",
                        }
                    )

                if sc.alignment_after:
                    upd[sc.alignment_after] = _safe_json_payload(alignment_after_snapshot)

                if sc.delta_score:
                    upd[sc.delta_score] = float(delta_score_val)

                if sc.delta_risk:
                    upd[sc.delta_risk] = float(delta_risk_val)

                if sc.notes:
                    upd[sc.notes] = " ".join(notes_parts)

                try:
                    res = conn.execute(
                        sa.update(table).where(table.c[sc.id] == rid).values(**upd)
                    )
                    if res.rowcount and int(res.rowcount) > 0:
                        updated += int(res.rowcount)
                except Exception:
                    update_errors.append(f"update_failed_id={rid}")
                    logger.exception(
                        "ofl_evaluate_row_failed",
                        extra={
                            "id": rid,
                            "decision_id": decision_id,
                            "evaluation_window_days": window_days,
                        },
                    )

        logger.info(
            "ofl_evaluate_summary",
            extra={
                "processed": processed,
                "updated": updated,
                "errors": len(update_errors),
                "limit": limit_eff,
                "marker_column": marker_col,
            },
        )

        return {
            "ok": len(update_errors) == 0,
            "processed": processed,
            "updated": updated,
            "errors": update_errors,
            "limit": limit_eff,
            "marker_column": marker_col,
        }
