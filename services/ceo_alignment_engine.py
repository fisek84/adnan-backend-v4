# services/ceo_alignment_engine.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

JsonDict = Dict[str, Any]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_dumps(x: Any) -> str:
    # DeterministiÄŤki JSON string (sort_keys=True) za hashing / determinism tests
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _safe_str(x: Any) -> str:
    if isinstance(x, str) and x.strip():
        return x.strip()
    return "NIJE POZNATO"


def _safe_bool(x: Any) -> bool:
    return bool(x is True)


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None or isinstance(x, bool):
            return default
        return int(x)
    except Exception:
        return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or isinstance(x, bool):
            return default
        return float(x)
    except Exception:
        return default


def _get(d: Any, path: List[str]) -> Any:
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _as_list(x: Any) -> List[Any]:
    return x if isinstance(x, list) else []


def _cap_list(items: List[Any], cap: int) -> List[Any]:
    c = max(0, _safe_int(cap, 0))
    return items[:c]


# ============================================================
# Thresholds / weights (v1) â€” deterministic
# ============================================================
@dataclass(frozen=True)
class AlignmentThresholds:
    # Strategic alignment scoring
    aligned_min_score: int = 75
    at_risk_min_score: int = 45

    # Law compliance risk mapping
    high_risk_violations: int = 1  # if >=1 high risk violation -> risk_level high

    # Executive priorities caps
    max_top_priorities: int = 3
    max_deprioritize: int = 3
    max_kill_candidates: int = 3

    # Risk register caps
    max_top_risks: int = 3

    # CEO action queue cap
    max_pending_decisions: int = 5

    # Misaligned focus areas cap
    max_misaligned_focus_areas: int = 3

    # Identity conflicts cap
    max_identity_conflicts: int = 5


class CEOAlignmentEngine:
    """
    CEO Alignment Engine (Option A)
    DeterministiÄŤka evaluacija identity_pack + world_state_snapshot -> alignment_snapshot (v1)

    HARD RULES:
      - NO Notion access
      - NO LLM calls
      - NO "free reasoning"
      - Pure deterministic logic (if/else + scoring + thresholds)
    """

    SNAPSHOT_VERSION = "ceo_alignment.v1"

    def __init__(self, *, thr: Optional[AlignmentThresholds] = None) -> None:
        self._thr = thr or AlignmentThresholds()

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------
    def evaluate(self, identity_pack: Any, world_state_snapshot: Any) -> JsonDict:
        generated_at = _utc_now_iso()

        required_missing: List[str] = []
        identity = identity_pack if isinstance(identity_pack, dict) else {}
        world = world_state_snapshot if isinstance(world_state_snapshot, dict) else {}

        # META inputs
        tw = world.get("time_window") if isinstance(world.get("time_window"), dict) else None
        time_window = tw if tw else {"label": "NIJE POZNATO", "start": "NIJE POZNATO", "end": "NIJE POZNATO"}

        alerts_present = bool(_as_list(world.get("alerts")))

        # Extract key identity structures (best-effort; do not assume)
        # Identity trajectory targets (expected somewhere under identity_pack)
        traj_targets = self._extract_trajectory_targets(identity)
        if traj_targets is None:
            required_missing.append("identity_pack.trajectory_targets (NIJE POZNATO)")

        # Immutable laws (kernel.json-like). We do not assume exact location.
        immutable_laws = self._extract_immutable_laws(identity)
        if immutable_laws is None:
            required_missing.append("identity_pack.immutable_laws/kernel (NIJE POZNATO)")

        # Compute sections
        strategic_alignment = self._eval_strategic_alignment(world, traj_targets, required_missing)
        law_compliance = self._eval_law_compliance(identity, world, immutable_laws, required_missing)
        decision_engine_eval = self._eval_decision_engine(identity, world, strategic_alignment, law_compliance, required_missing)
        executive_priorities = self._eval_executive_priorities(world, strategic_alignment, law_compliance)
        risk_register = self._eval_risk_register(world, law_compliance)
        ceo_action_required = self._eval_ceo_action_required(world, strategic_alignment, law_compliance, decision_engine_eval)

        # Confidence level (deterministic)
        confidence_level = self._confidence(required_missing, world)

        alignment_snapshot: JsonDict = {
            "snapshot_version": self.SNAPSHOT_VERSION,
            "generated_at": generated_at,
            "time_window": time_window,
            "confidence_level": confidence_level,
            "alerts_present": bool(alerts_present),

            "strategic_alignment": strategic_alignment,
            "law_compliance": law_compliance,
            "decision_engine_eval": decision_engine_eval,
            "executive_priorities": executive_priorities,
            "risk_register": risk_register,
            "ceo_action_required": ceo_action_required,

            # Determinism trace (for A1 testing)
            "trace": {
                "required_inputs_missing": required_missing,
                "input_hash": {
                    "identity_pack_sha256": _sha256_hex(_stable_dumps(identity)),
                    "world_state_sha256": _sha256_hex(_stable_dumps(world)),
                },
                "engine": {
                    "version": self.SNAPSHOT_VERSION,
                    "thresholds": {
                        "aligned_min_score": self._thr.aligned_min_score,
                        "at_risk_min_score": self._thr.at_risk_min_score,
                    },
                },
            },
        }
        return alignment_snapshot

    # ------------------------------------------------------------
    # Extraction helpers (do not assume exact identity schema)
    # ------------------------------------------------------------
    def _extract_trajectory_targets(self, identity: JsonDict) -> Optional[JsonDict]:
        # Try common locations without assuming any is present.
        candidates = [
            _get(identity, ["trajectory_targets"]),
            _get(identity, ["identity", "trajectory_targets"]),
            _get(identity, ["trajectory", "targets"]),
            _get(identity, ["identity", "trajectory", "targets"]),
        ]
        for c in candidates:
            if isinstance(c, dict) and c:
                return c
        return None

    def _extract_immutable_laws(self, identity: JsonDict) -> Optional[List[JsonDict]]:
        # Expect list of laws like [{"id":"...", "rule":"...", "severity":"high"}]
        candidates = [
            _get(identity, ["immutable_laws"]),
            _get(identity, ["kernel", "immutable_laws"]),
            _get(identity, ["kernel", "laws"]),
            _get(identity, ["kernel_json", "laws"]),
        ]
        for c in candidates:
            if isinstance(c, list) and c:
                out: List[JsonDict] = []
                for it in c:
                    if isinstance(it, dict):
                        out.append(it)
                return out if out else None
        return None

    # ------------------------------------------------------------
    # 3.2 STRATEGIC_ALIGNMENT
    # ------------------------------------------------------------
    def _eval_strategic_alignment(
        self,
        world: JsonDict,
        traj_targets: Optional[JsonDict],
        required_missing: List[str],
    ) -> JsonDict:
        actual_dist = self._derive_trajectory_distribution(world)

        if actual_dist is None:
            required_missing.append("world_state_snapshot.trajectory_distribution (NIJE POZNATO)")
            actual_dist = {"NIJE POZNATO": 1.0}

        # Score: if we have targets, compute closeness; else unknown score.
        score = 50  # deterministic neutral default
        misaligned_focus: List[str] = []
        identity_conflicts: List[str] = []

        # If distribution is unknown, do NOT penalize to 0; treat as "at_risk" due to missing signal.
        dist_unknown = (
            isinstance(actual_dist, dict)
            and set(actual_dist.keys()) == {"NIJE POZNATO"}
        )

        if dist_unknown:
            # keep score=50, and ensure it evaluates as at_risk (given default thresholds)
            identity_conflicts.append("trajectory_distribution_missing")
        elif traj_targets is None or not isinstance(traj_targets, dict) or not traj_targets:
            required_missing.append("strategic_alignment.alignment_score_inputs_missing")
            score = 50
        else:
            score, misaligned_focus, identity_conflicts = self._score_distribution_vs_targets(actual_dist, traj_targets)

        overall_status = self._status_from_score(int(score))

        return {
            "overall_status": overall_status,
            "alignment_score": int(score),
            "trajectory_distribution": actual_dist,
            "misaligned_focus_areas": _cap_list(misaligned_focus, self._thr.max_misaligned_focus_areas),
            "identity_conflicts": _cap_list(identity_conflicts, self._thr.max_identity_conflicts),
        }

    def _derive_trajectory_distribution(self, world: JsonDict) -> Optional[JsonDict]:
        pipeline = world.get("pipeline")
        if isinstance(pipeline, dict):
            stages = pipeline.get("stages")
            if isinstance(stages, list) and stages:
                counts: Dict[str, int] = {}
                total = 0
                for st in stages:
                    if isinstance(st, dict):
                        cat = st.get("category")
                        if isinstance(cat, str) and cat.strip():
                            counts[cat.strip()] = counts.get(cat.strip(), 0) + 1
                            total += 1
                if total > 0:
                    return {k: round(v / total, 4) for k, v in sorted(counts.items())}
        return None

    def _score_distribution_vs_targets(
        self, actual: JsonDict, targets: JsonDict
    ) -> Tuple[int, List[str], List[str]]:
        diffs: List[Tuple[str, float]] = []
        for k, tv in targets.items():
            if not isinstance(k, str) or not k.strip():
                continue
            t = _safe_float(tv, default=0.0)
            a = _safe_float(actual.get(k, 0.0), default=0.0) if isinstance(actual, dict) else 0.0
            diffs.append((k.strip(), abs(a - t)))

        if not diffs:
            return 50, ["NIJE POZNATO"], ["trajectory_targets_empty_or_invalid"]

        total_diff = sum(d for _, d in diffs)
        raw_score = 100.0 - (total_diff * 100.0)
        score = int(max(0.0, min(100.0, raw_score)))

        diffs_sorted = sorted(diffs, key=lambda x: x[1], reverse=True)
        misaligned = [k for k, d in diffs_sorted if d >= 0.10]  # 10pp threshold
        conflicts: List[str] = []
        if score < self._thr.at_risk_min_score:
            conflicts.append("trajectory_distribution_far_from_targets")

        return score, misaligned, conflicts

    def _status_from_score(self, score: int) -> str:
        if score >= self._thr.aligned_min_score:
            return "aligned"
        if score >= self._thr.at_risk_min_score:
            return "at_risk"
        return "misaligned"

    # ------------------------------------------------------------
    # 3.3 LAW_COMPLIANCE
    # ------------------------------------------------------------
    def _eval_law_compliance(
        self,
        identity: JsonDict,
        world: JsonDict,
        immutable_laws: Optional[List[JsonDict]],
        required_missing: List[str],
    ) -> JsonDict:
        violations: List[JsonDict] = []
        system_integrity = "intact"
        risk_level = "none"

        # 1) Explicit law violations signaled by SotW alerts (deterministic, schema-driven)
        # Expected alert shape from SotW: {"type": "...", "severity": "...", "details": "..."}
        for a in _as_list(world.get("alerts")):
            if not isinstance(a, dict):
                continue

            atype = _safe_str(a.get("type")).lower()
            asev_raw = _safe_str(a.get("severity")).lower()
            details = _safe_str(a.get("details"))

            # normalize severity to: low/medium/high
            if asev_raw in ("med", "medium"):
                asev = "medium"
            elif asev_raw == "high":
                asev = "high"
            elif asev_raw == "low":
                asev = "low"
            else:
                asev = "medium"

            # Only treat explicit law-related alert types as violations
            if atype in ("law_violation", "immutable_law_violation", "canon_violation"):
                violations.append(
                    {
                        "law_id": atype,  # deterministic id from alert type
                        "severity": asev,
                        "example": details if details != "NIJE POZNATO" else f"Alert type={atype}",
                    }
                )

        # Deterministic checks we CAN do purely from known canon:
        canon = world.get("trace", {}).get("determinism") if isinstance(world.get("trace"), dict) else None
        _ = canon  # placeholder

        # If immutable_laws exist, apply simple rule matching:
        if immutable_laws is None:
            required_missing.append("law_compliance.laws (NIJE POZNATO)")
        else:
            world_text = _stable_dumps(world)
            for law in immutable_laws:
                if not isinstance(law, dict):
                    continue
                law_id = _safe_str(law.get("id"))
                sev = _safe_str(law.get("severity")).lower()
                keyword = law.get("keyword")
                if isinstance(keyword, str) and keyword.strip():
                    if keyword.strip() in world_text:
                        violations.append(
                            {
                                "law_id": law_id,
                                "severity": sev if sev in ("low", "medium", "high") else "medium",
                                "example": f"Matched keyword in world_state: {keyword.strip()}",
                            }
                        )

        # Also check explicit known canon flags if present
        wcanon = world.get("canon") if isinstance(world.get("canon"), dict) else None
        if isinstance(wcanon, dict):
            if wcanon.get("no_tools") is False:
                violations.append({"law_id": "canon.no_tools", "severity": "high", "example": "no_tools=False"})
            if wcanon.get("read_only") is False:
                violations.append({"law_id": "canon.read_only", "severity": "high", "example": "read_only=False"})

        # Compute risk_level and integrity
        if violations:
            risk_level = self._risk_from_violations(violations)
            if risk_level in ("medium", "high"):
                system_integrity = "threatened"

        return {
            "violations": violations,  # 0..N objects
            "risk_level": risk_level,  # none/low/medium/high
            "examples": _cap_list([v.get("example") for v in violations if isinstance(v, dict)], 5),
            "system_integrity": system_integrity,  # intact/threatened
        }

    def _risk_from_violations(self, violations: List[JsonDict]) -> str:
        sev_rank = {"high": 3, "medium": 2, "low": 1}
        max_rank = 0
        for v in violations:
            sev = _safe_str(v.get("severity")).lower()
            max_rank = max(max_rank, sev_rank.get(sev, 2))
        if max_rank >= 3:
            return "high"
        if max_rank == 2:
            return "medium"
        return "low"

    # ------------------------------------------------------------
    # 3.4 DECISION_ENGINE_EVAL
    # ------------------------------------------------------------
    def _eval_decision_engine(
        self,
        identity: JsonDict,
        world: JsonDict,
        strategic_alignment: JsonDict,
        law_compliance: JsonDict,
        required_missing: List[str],
    ) -> JsonDict:
        risks = _as_list(world.get("risks"))
        alerts = _as_list(world.get("alerts"))

        if not isinstance(world.get("goals"), dict):
            required_missing.append("world_state_snapshot.goals (NIJE POZNATO)")
        if not isinstance(world.get("projects"), dict):
            required_missing.append("world_state_snapshot.projects (NIJE POZNATO)")
        if not isinstance(world.get("tasks"), dict):
            required_missing.append("world_state_snapshot.tasks (NIJE POZNATO)")

        overall = _safe_str(strategic_alignment.get("overall_status")).lower()
        system_integrity = _safe_str(law_compliance.get("system_integrity")).lower()

        required_inputs_missing: List[str] = []
        if "identity_pack.trajectory_targets (NIJE POZNATO)" in required_missing:
            required_inputs_missing.append("trajectory_targets")

        decision_clarity = "clear"
        recommended_decision_type = "none"
        confidence_score = 0.6  # deterministic default

        if system_integrity == "threatened":
            decision_clarity = "clear"
            recommended_decision_type = "structural"
            confidence_score = 0.9
        else:
            if overall == "misaligned":
                decision_clarity = "clear"
                recommended_decision_type = "strategic"
                confidence_score = 0.8
            elif overall == "at_risk":
                decision_clarity = "ambiguous" if required_inputs_missing else "clear"
                recommended_decision_type = "priority"
                confidence_score = 0.7 if not required_inputs_missing else 0.55
            else:
                if risks or alerts:
                    decision_clarity = "ambiguous"
                    recommended_decision_type = "priority"
                    confidence_score = 0.6
                else:
                    decision_clarity = "clear"
                    recommended_decision_type = "none"
                    confidence_score = 0.75

        return {
            "decision_clarity": decision_clarity,  # clear/ambiguous/blocked
            "required_inputs_missing": required_inputs_missing,
            "recommended_decision_type": recommended_decision_type,  # strategic/structural/priority/none
            "confidence_score": round(float(confidence_score), 3),
        }

    # ------------------------------------------------------------
    # 3.5 EXECUTIVE_PRIORITIES
    # ------------------------------------------------------------
    def _eval_executive_priorities(
        self,
        world: JsonDict,
        strategic_alignment: JsonDict,
        law_compliance: JsonDict,
    ) -> JsonDict:
        top_priorities: List[str] = []
        deprioritize: List[str] = []
        kill_candidates: List[str] = []

        tasks = world.get("tasks") if isinstance(world.get("tasks"), dict) else {}
        critical = _as_list(tasks.get("critical_path"))
        overdue = _as_list(tasks.get("overdue"))
        _ = critical  # currently not used, kept for deterministic expansion

        projects = world.get("projects") if isinstance(world.get("projects"), dict) else {}
        at_risk = _as_list(projects.get("at_risk"))

        overall = _safe_str(strategic_alignment.get("overall_status")).lower()
        integrity = _safe_str(law_compliance.get("system_integrity")).lower()

        if integrity == "threatened":
            top_priorities.append("Restore system integrity (immutable law compliance)")
            deprioritize.append("All non-critical expansion")
        else:
            if overall == "misaligned":
                top_priorities.append("Realign execution to identity trajectory targets")
                deprioritize.append("Work not contributing to trajectory distribution")
            elif overall == "at_risk":
                top_priorities.append("Reduce drift risk (tighten focus + deadlines)")
            else:
                top_priorities.append("Maintain aligned execution; focus on critical path")

        if overdue:
            top_priorities.append("Clear overdue tasks blocking delivery")
        if at_risk:
            top_priorities.append("Stabilize at-risk projects (next steps + ownership)")

        blocked = _as_list(projects.get("blocked"))
        for b in blocked:
            if isinstance(b, dict):
                title = _safe_str(b.get("title"))
                if title != "NIJE POZNATO":
                    kill_candidates.append(f"Project candidate: {title} (blocked: {_safe_str(b.get('reason'))})")

        return {
            "top_priorities": _cap_list(top_priorities, self._thr.max_top_priorities),
            "deprioritize": _cap_list(deprioritize, self._thr.max_deprioritize),
            "kill_candidates": _cap_list(kill_candidates, self._thr.max_kill_candidates),
            "rationale_summary": self._priority_rationale(world, strategic_alignment, law_compliance),
        }

    def _priority_rationale(self, world: JsonDict, strategic_alignment: JsonDict, law_compliance: JsonDict) -> str:
        overall = _safe_str(strategic_alignment.get("overall_status"))
        score = _safe_int(strategic_alignment.get("alignment_score"), 0)
        integrity = _safe_str(law_compliance.get("system_integrity"))
        tasks = world.get("tasks") if isinstance(world.get("tasks"), dict) else {}
        overdue_n = _safe_int(_get(tasks, ["counts", "overdue"]), 0)
        blockers_n = _safe_int(_get(tasks, ["counts", "blockers"]), 0)
        return f"alignment={overall} score={score}; system_integrity={integrity}; overdue_tasks={overdue_n}; blockers={blockers_n}"

    # ------------------------------------------------------------
    # 3.6 RISK_REGISTER
    # ------------------------------------------------------------
    def _eval_risk_register(self, world: JsonDict, law_compliance: JsonDict) -> JsonDict:
        top_risks: List[JsonDict] = []

        for r in _as_list(world.get("risks")):
            if isinstance(r, dict):
                title = _safe_str(r.get("title"))
                sev = _safe_str(r.get("severity")).lower()
                if title != "NIJE POZNATO":
                    top_risks.append(
                        {
                            "title": title,
                            "risk_type": self._classify_risk_type(r),
                            "time_sensitivity": self._time_sensitivity_from_severity(sev),
                            "mitigation_hint": "NIJE POZNATO",
                        }
                    )

        if _safe_str(law_compliance.get("system_integrity")).lower() == "threatened":
            top_risks.insert(
                0,
                {
                    "title": "System integrity threatened (immutable law compliance)",
                    "risk_type": "system",
                    "time_sensitivity": "now",
                    "mitigation_hint": "Stop and correct violations (no plan here).",
                },
            )

        def key(x: JsonDict) -> Tuple[int, int, str]:
            rt = _safe_str(x.get("risk_type")).lower()
            ts = _safe_str(x.get("time_sensitivity")).lower()
            rt_rank = {"system": 0, "strategic": 1, "operational": 2, "cognitive": 3}.get(rt, 9)
            ts_rank = {"now": 0, "soon": 1, "can_wait": 2}.get(ts, 9)
            return (rt_rank, ts_rank, _safe_str(x.get("title")))

        top_risks_sorted = sorted(top_risks, key=key)
        return {
            "top_risks": _cap_list(top_risks_sorted, self._thr.max_top_risks),
        }

    def _classify_risk_type(self, r: JsonDict) -> str:
        cat = r.get("category")
        if isinstance(cat, str):
            c = cat.strip().lower()
            if c in ("delivery", "strategy", "strategic"):
                return "strategic"
            if c in ("ops", "operational"):
                return "operational"
        return "operational"

    def _time_sensitivity_from_severity(self, sev: str) -> str:
        if sev == "high":
            return "now"
        if sev in ("med", "medium"):
            return "soon"
        return "can_wait"

    # ------------------------------------------------------------
    # 3.7 CEO_ACTION_REQUIRED
    # ------------------------------------------------------------
    def _eval_ceo_action_required(
        self,
        world: JsonDict,
        strategic_alignment: JsonDict,
        law_compliance: JsonDict,
        decision_engine_eval: JsonDict,
    ) -> JsonDict:
        pending: List[str] = []
        action_window = "can_wait"
        delay_cost_estimate = "NIJE POZNATO"

        overall = _safe_str(strategic_alignment.get("overall_status")).lower()
        integrity = _safe_str(law_compliance.get("system_integrity")).lower()
        decision_type = _safe_str(decision_engine_eval.get("recommended_decision_type")).lower()
        _ = decision_type  # deterministic placeholder

        if integrity == "threatened":
            pending.append("Decide: halt/contain and restore immutable law compliance")
            action_window = "now"
            delay_cost_estimate = "High (system integrity)"
        elif overall == "misaligned":
            pending.append("Decide: reallocate focus to match trajectory targets")
            action_window = "soon"
            delay_cost_estimate = "Medium-High (strategic drift)"
        elif overall == "at_risk":
            pending.append("Decide: priority reshuffle to reduce drift risk")
            action_window = "soon"
            delay_cost_estimate = "Medium (delivery risk)"
        else:
            if _as_list(world.get("risks")) or _as_list(world.get("alerts")):
                pending.append("Decide: address top risk/alert")
                action_window = "soon"
                delay_cost_estimate = "Low-Medium"
            else:
                pending = []

        pending = _cap_list(pending, self._thr.max_pending_decisions)
        requires_action = bool(pending)

        return {
            "requires_action": requires_action,
            "pending_decisions": pending,
            "delay_cost_estimate": delay_cost_estimate,
            "action_window": action_window if requires_action else "can_wait",
        }

    # ------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------
    def _confidence(self, required_missing: List[str], world: JsonDict) -> str:
        core_ok = all(isinstance(world.get(k), dict) for k in ("goals", "projects", "tasks"))
        if core_ok and not required_missing:
            return "high"
        if core_ok:
            return "medium"
        return "low"
