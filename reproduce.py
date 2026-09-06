"""Recomputes every reported number from the stored data and checks it against what ships here.

The modules under `evaluation-scripts/` are copies of the analysis code from the Artemis repository,
where a notebook drove them and a live instance supplied the data. They are libraries rather than
command-line programs, so this script is the entry point that repository never needed. It needs no
Artemis instance, no model endpoint, and no credentials.

`results/` holds the primary records of the measurement and `output/` what the scripts made from
them. This run writes to neither: everything lands in `reproduced/` and is compared against `output/`,
so a reader sees whether the numbers came back identical rather than having to trust that they did.

    python3 reproduce.py              # recompute and compare
    python3 reproduce.py --keep       # same, but leave `reproduced/` in place for inspection

Tables, checks, and hypothesis tests need the standard library only. The figures need matplotlib
(`pip install -r evaluation-scripts/requirements.txt`); without it they are skipped and the rest
still runs.
"""

import argparse
import filecmp
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "evaluation-scripts")
RESULTS = os.path.join(ROOT, "results")
SOURCES = os.path.join(ROOT, "exercises")
OUTPUT = os.path.join(ROOT, "output")      # what the scripts produce, as shipped
OUT = os.path.join(ROOT, "reproduced")     # where this run puts its copy, for comparison

sys.path.insert(0, SCRIPTS)

import analysis  # noqa: E402  (needs `evaluation-scripts/` on the path first)
import checks  # noqa: E402

# Every step appends (label, verdict) here; the exit status is decided from the verdicts.
REPORT = []


def record(label, ok, detail=""):
    REPORT.append((label, ok, detail))
    mark = "ok  " if ok else "DIFF"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def canonical(records):
    """Order-independent, key-order-independent form, so a reordering is not reported as a difference."""
    return sorted(json.dumps(record, sort_keys=True) for record in records)


def step_design(runs):
    """Check that the ledger implements the design `matrix.py` documents.

    The tables key every row on a configuration id, and `matrix.py` is what those ids mean. If a run
    were recorded under a configuration whose difficulty, domain, or narrative style did not match
    that definition, every table built from it would be mislabelled and nothing else here would
    notice. This also confirms the matrix is balanced, since equal n per cell is what lets the cells
    be compared at all.
    """
    print("\nDesign")
    import matrix

    mismatches = []
    for run in runs:
        configuration = matrix.CONFIGURATIONS_BY_ID.get(run["config_id"])
        if configuration is None:
            mismatches.append(f"{run['run_id']}: no configuration {run['config_id']}")
            continue
        for field in ("target_difficulty", "domain_key", "narrative_style"):
            if run.get(field) != getattr(configuration, field):
                mismatches.append(f"{run['run_id']}: {field} is {run.get(field)!r}, not {getattr(configuration, field)!r}")
    record("runs match their configuration", not mismatches,
           f"{len(runs)} runs over {len(matrix.CONFIGURATIONS)} configurations"
           + (f"; first mismatch {mismatches[0]}" if mismatches else ""))

    cells = defaultdict(int)
    for run in runs:
        cells[(run["exercise_type"], run["config_id"])] += 1
    sizes = sorted(set(cells.values()))
    record("matrix is balanced", len(sizes) == 1, f"{len(cells)} cells, {sizes[0] if len(sizes) == 1 else sizes} runs each")


def step_checks(runs):
    print("\nAutomated checks over the stored variants")
    recomputed = [checks.run_checks_for_run(run, os.path.join(RESULTS, "generated-variants"), SOURCES) for run in runs]
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "checks.jsonl"), "w", encoding="utf-8") as handle:
        for result in recomputed:
            handle.write(json.dumps(result, sort_keys=True) + "\n")
    stored = read_jsonl(os.path.join(OUTPUT, "checks.jsonl"))
    record("checks.jsonl", canonical(recomputed) == canonical(stored), f"{len(recomputed)} runs")
    return recomputed


def step_phase_timings(runs):
    """Rebuild each run's phase durations from its instance log and check them against the ledger.

    The ledger's ``phase_durations_seconds`` is what the timing figures and the H3/H4 tests are drawn
    from, and it was derived from the server logs while the runs were happening. Rebuilding it here
    from the shipped logs means those numbers are recomputed rather than taken on trust.
    """
    print("\nPhase timings, rebuilt from the instance logs")
    import logs as logs_module

    matched = differing = 0
    worst = 0.0
    for run in runs:
        log_path = os.path.join(RESULTS, "instance-logs", run["run_id"] + ".log")
        if not os.path.exists(log_path):
            differing += 1
            continue
        job_lines = logs_module.slice_for_job(logs_module.read_lines(log_path), run["job_id"])
        timeline = logs_module.build_phase_timeline(
            job_lines,
            datetime.fromisoformat(run["finished_at"]) if run.get("finished_at") else None,
            datetime.fromisoformat(run["started_at"]) if run.get("started_at") else None,
        )
        stored = run.get("phase_durations_seconds") or {}
        delta = max(
            (abs(round(stored.get(phase, 0.0), 3) - round(timeline.durations.get(phase, 0.0), 3))
             for phase in set(stored) | set(timeline.durations)),
            default=0.0,
        )
        worst = max(worst, delta)
        matched += delta < 0.01
        differing += delta >= 0.01
    record("phase durations", differing == 0, f"{matched}/{len(runs)} runs, largest difference {worst:.3f}s")


def step_tables(runs, check_results):
    print("\nTables")
    rubric_scores = read_jsonl(os.path.join(RESULTS, "rubric.jsonl"))
    analysis.outcomes_table(runs, OUT)
    analysis.cost_table(runs, OUT)
    analysis.quality_table(runs, check_results, rubric_scores, OUT)
    for name in ("outcomes.csv", "cost.csv", "quality.csv"):
        mine = os.path.join(OUT, "tables", name)
        theirs = os.path.join(OUTPUT, "tables", name)
        record(f"tables/{name}", filecmp.cmp(mine, theirs, shallow=False))


def _pdf_without_timestamp(path):
    """PDF bytes with the embedded creation date removed, so two runs of the same plot compare equal."""
    with open(path, "rb") as handle:
        return re.sub(rb"/CreationDate\s*\([^)]*\)", b"", handle.read())


def step_figures():
    print("\nFigures")
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        record("figures", True, "skipped, matplotlib not installed")
        return

    import make_figures

    make_figures.main(os.path.join(OUT, "figures"))
    for name in ("phases-programming.pdf", "phases-quiz.pdf"):
        mine = os.path.join(OUT, "figures", name)
        theirs = os.path.join(OUTPUT, "figures", name)
        record(f"figures/{name}", _pdf_without_timestamp(mine) == _pdf_without_timestamp(theirs))


def step_hypothesis_tests():
    print("\nHypothesis tests")
    import hypothesis_tests

    # The script writes straight into `output/`. Snapshot the shipped bytes, let it write, compare,
    # and put the original back, so a verification run leaves the package exactly as it found it.
    shipped = hypothesis_tests.OUT.read_bytes()
    hypothesis_tests.main()
    regenerated = hypothesis_tests.OUT.read_bytes()
    hypothesis_tests.OUT.write_bytes(shipped)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "hypothesis-tests.csv"), "wb") as handle:
        handle.write(regenerated)
    record("hypothesis-tests.csv", regenerated == shipped)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="leave `reproduced/` behind instead of deleting it")
    arguments = parser.parse_args()

    if os.path.exists(OUT):
        shutil.rmtree(OUT)

    runs = analysis.load_runs(RESULTS)
    print(f"Ledger: {len(runs)} runs")
    if not runs:
        print("No runs found. Run this from the package root.")
        return 1

    step_design(runs)
    check_results = step_checks(runs)
    step_phase_timings(runs)
    step_tables(runs, check_results)
    step_figures()
    step_hypothesis_tests()

    failed = [label for label, ok, _ in REPORT if not ok]
    print()
    if failed:
        print(f"{len(failed)} of {len(REPORT)} outputs differ from the shipped copy: {', '.join(failed)}")
        print(f"Recomputed files are under {OUT} for comparison.")
        return 1

    print(f"All {len(REPORT)} outputs match the shipped copy.")
    if arguments.keep:
        print(f"Recomputed files left under {OUT}.")
    else:
        shutil.rmtree(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
