"""Tables and figures over the stored ledger and artifacts.

Everything here reads `results/` only, so it can rerun over stored data without a live instance and a
crashed kernel loses nothing.

Reporting rules baked in deliberately:

* **Every rate is quoted with its n and a Wilson 95 % interval, never as a bare percentage.** At six
  replicates a single cell's interval spans roughly 44-97 %, so a bare "83 %" would be misleading.
* **Pooling is used for headline reliability only.** Pooling C5-C8 answers "how often does the
  narrative-only group complete"; it cannot answer whether narrative *strength* costs reliability, because
  that question is about the differences between those cells and pooling is what destroys them. The
  narrative sweeps are therefore reported cell by cell, as a described trend with no significance claim.
* Serial timing runs are separated from the concurrent ones: contention on one build agent inflates wall
  time and would make the phase breakdown dishonest.
"""

import csv
import json
import math
import os
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

PHASES_IN_ORDER = ("QUEUED", "ANALYZING", "PLANNING", "PROVISIONING", "TRANSFORMING", "VERIFYING", "REPAIRING", "FINALIZING")
# Which phases are bound by the model and which by the local build agent — the report must say so.
MODEL_BOUND_PHASES = ("PLANNING", "TRANSFORMING")
BUILD_BOUND_PHASES = ("VERIFYING", "REPAIRING")
SURVIVING_PHASES = ("COMPLETED", "DRAFT_WITH_WARNINGS")
OUTCOME_ORDER = ("COMPLETED", "DRAFT_WITH_WARNINGS", "FAILED", "TIMEOUT", "CANCELLED", "LOST")
# Not outcomes of the pipeline: runs whose builds were rate-limited by Maven Central resolved no
# dependencies, ran 0 tests, and failed both build gates for reasons that have nothing to do with the
# generation. They are excluded from every rate and reported as a separate count, so a throttled afternoon
# cannot masquerade as "the pipeline is unreliable".
QUARANTINED_PHASES = ("INVALID_ENVIRONMENT",)


def load_runs(results_dir: str, report_duplicates: bool = True) -> List[Dict[str, Any]]:
    """The ledger, de-duplicated by ``run_id`` with the last line winning.

    The ledger is append-only, so a run that had to be repeated — a cancelled client, a job lost to the
    24-hour TTL or a server restart — leaves an earlier line with the same id. Resume already skips those,
    but counting both would inflate n and, worse, count a discarded attempt as an outcome. Last-wins is
    the right rule because a repeat is always the run that actually stands.
    """
    path = os.path.join(results_dir, "runs.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]

    by_id: Dict[str, Dict[str, Any]] = {}
    duplicates: Dict[str, int] = defaultdict(int)
    for record in records:
        if record["run_id"] in by_id:
            duplicates[record["run_id"]] += 1
        by_id[record["run_id"]] = record
    if duplicates and report_duplicates:
        print(f"note: {len(duplicates)} run id(s) appear more than once; keeping the last line of each: {dict(duplicates)}")
    return list(by_id.values())


def wilson_interval(successes: int, total: int, z: float = 1.96) -> Optional[Tuple[float, float]]:
    """Wilson score interval — the reason a bare percentage is never reported at these sample sizes."""
    if total == 0:
        return None
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _write_csv(path: str, rows: List[Dict[str, Any]], columns: Iterable[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Programming and quiz rows carry different keys, so the first row's columns are not the full set.
    fieldnames = list(columns)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def outcomes_table(runs: List[Dict[str, Any]], results_dir: str) -> List[Dict[str, Any]]:
    """Outcomes per configuration and exercise type, with n, a Wilson interval, and repair effort."""
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    quarantined: Dict[Tuple[str, str], int] = defaultdict(int)
    for run in runs:
        if run.get("serial"):
            continue  # the serial subset exists for timing, not for rates
        key = (run["exercise_type"], run["config_id"])
        if run["terminal_phase"] in QUARANTINED_PHASES:
            quarantined[key] += 1
            continue
        grouped[key].append(run)

    rows: List[Dict[str, Any]] = []
    for (exercise_type, config_id), cell in sorted(grouped.items()):
        counts = {phase: sum(1 for run in cell if run["terminal_phase"] == phase) for phase in OUTCOME_ORDER}
        total = len(cell)
        completed = counts["COMPLETED"]
        interval = wilson_interval(completed, total)
        first_attempt = sum(1 for run in cell if run["terminal_phase"] == "COMPLETED" and (run.get("attempts_used") or 1) <= 1)
        attempts = [run.get("attempts_used") for run in cell if run.get("attempts_used") is not None]
        gate_ran = sum(1 for run in cell if (run.get("semantic_gate") or {}).get("ran") is True)
        rows.append(
            {
                "exercise_type": exercise_type,
                "config_id": config_id,
                "n": total,
                **{f"outcome_{phase.lower()}": counts[phase] for phase in OUTCOME_ORDER},
                "completion_rate": round(completed / total, 3) if total else None,
                "completion_ci_low": round(interval[0], 3) if interval else None,
                "completion_ci_high": round(interval[1], 3) if interval else None,
                "first_attempt_passes": first_attempt,
                "median_attempts_used": _median([float(a) for a in attempts]),
                "semantic_gate_ran": gate_ran,
                # Excluded from n above; reported so the report can state how much was discarded and why.
                "quarantined_environment_failures": quarantined.get((exercise_type, config_id), 0),
            }
        )
    _write_csv(os.path.join(results_dir, "tables", "outcomes.csv"), rows, rows[0].keys() if rows else ["exercise_type"])
    return rows


def cost_table(runs: List[Dict[str, Any]], results_dir: str) -> List[Dict[str, Any]]:
    """Wall time, phase shares, and tokens. Serial runs are reported as their own rows, never merged."""
    grouped: Dict[Tuple[str, str, bool], List[Dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[(run["exercise_type"], run["config_id"], bool(run.get("serial")))].append(run)

    rows: List[Dict[str, Any]] = []
    for (exercise_type, config_id, serial), cell in sorted(grouped.items()):
        walls = [run["wall_seconds"] for run in cell if run.get("wall_seconds") is not None]
        tokens = [run["total_tokens_used"] for run in cell if run.get("total_tokens_used") is not None]
        phase_totals = {phase: [] for phase in PHASES_IN_ORDER}
        for run in cell:
            for phase, seconds in (run.get("phase_durations_seconds") or {}).items():
                phase_totals.setdefault(phase, []).append(seconds)
        row: Dict[str, Any] = {
            "exercise_type": exercise_type,
            "config_id": config_id,
            "timing_mode": "serial" if serial else "concurrent",
            "n": len(cell),
            "wall_seconds_median": _median(walls),
            "wall_seconds_min": min(walls) if walls else None,
            "wall_seconds_max": max(walls) if walls else None,
            "tokens_median": _median([float(t) for t in tokens]),
        }
        for phase in PHASES_IN_ORDER:
            row[f"{phase.lower()}_median_seconds"] = _median(phase_totals.get(phase) or [])
        row["model_bound_median_seconds"] = _median([sum((run.get("phase_durations_seconds") or {}).get(p, 0.0) for p in MODEL_BOUND_PHASES) for run in cell])
        row["build_bound_median_seconds"] = _median([sum((run.get("phase_durations_seconds") or {}).get(p, 0.0) for p in BUILD_BOUND_PHASES) for run in cell])
        rows.append(row)
    _write_csv(os.path.join(results_dir, "tables", "cost.csv"), rows, rows[0].keys() if rows else ["exercise_type"])
    return rows


def quality_table(runs: List[Dict[str, Any]], check_results: List[Dict[str, Any]], rubric_scores: List[Dict[str, Any]], results_dir: str) -> List[Dict[str, Any]]:
    """The three automated checks plus the rubric scores, per configuration and exercise type."""
    checks_by_run = {result["run_id"]: result for result in check_results}
    rubric_by_run: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for score in rubric_scores:
        rubric_by_run[score["run_id"]].append(score)

    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run["terminal_phase"] in SURVIVING_PHASES:
            grouped[(run["exercise_type"], run["config_id"])].append(run)

    rows: List[Dict[str, Any]] = []
    for (exercise_type, config_id), cell in sorted(grouped.items()):
        checks = [checks_by_run.get(run["run_id"]) for run in cell]
        checks = [check for check in checks if check and check.get("has_artifacts")]
        row: Dict[str, Any] = {"exercise_type": exercise_type, "config_id": config_id, "survivors": len(cell), "checked": len(checks)}

        if exercise_type == "programming":
            row["with_stray_testid"] = sum(1 for check in checks if check.get("statement", {}).get("has_stray_testid"))
            row["with_dangling_task_reference"] = sum(1 for check in checks if check.get("statement", {}).get("has_dangling_task_reference"))
            row["with_fenced_plantuml"] = sum(1 for check in checks if check.get("statement", {}).get("has_fenced_plantuml"))
            for repository in ("template", "solution", "tests"):
                fractions = [check[f"{repository}_preservation"]["identical_fraction"] for check in checks if check.get(f"{repository}_preservation", {}).get("identical_fraction") is not None]
                row[f"{repository}_identical_fraction_median"] = _median(fractions)
        else:
            row["invalid_quizzes"] = sum(1 for check in checks if not check.get("quiz", {}).get("is_valid", True))
            row["question_count_mismatches"] = sum(1 for check in checks if not check.get("quiz", {}).get("question_count_matches_source", True))

        primary = [score for run in cell for score in rubric_by_run.get(run["run_id"], []) if score.get("scorer") == "primary"]
        row["rubric_scored"] = len(primary)
        for criterion in ("intent_fidelity", "preservation", "statement_quality", "readiness"):
            row[f"{criterion}_median"] = _median([float(score["scores"][criterion]) for score in primary if criterion in score.get("scores", {})])
        rows.append(row)

    _write_csv(os.path.join(results_dir, "tables", "quality.csv"), rows, rows[0].keys() if rows else ["exercise_type"])
    return rows
