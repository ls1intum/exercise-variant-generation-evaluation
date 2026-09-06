"""Redraws the phase-breakdown figures as the thesis prints them.

`evaluation-scripts/analysis.py` already produces a version of these two panels, and that version a version of these two panels, in
matplotlib's default colours with an in-plot title and an inset legend, none of which match the rest
of the thesis. That function is not part of this package. This script reads the ledger and draws the
panels the chapter prints: no title, since the caption carries it; the legend outside the axes; one
palette shared by both.

Only the four phases that are visible at this scale are drawn. The remaining phases (QUEUED,
ANALYZING, PROVISIONING, FINALIZING) have cell medians below one second and would not produce a
drawable band; the constant printed below the axis records their share.

Writes to `output/figures/`. Run from anywhere:

    python3 evaluation-scripts/make_figures.py
"""

import json
import os
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(ROOT, "results", "runs.jsonl")
FIGURES = os.path.join(ROOT, "output", "figures")

# Drawn in stacking order, bottom to top, with the colour each keeps in both panels. The colours
# come from the thesis palette: the three phases every run passes through take the blue ramp from
# dark to light, and the repair, which only some runs reach, takes the orange.
PHASES = [
    ("PLANNING", "Planning", "#105391"),
    ("TRANSFORMING", "Transforming", "#68A0C6"),
    ("VERIFYING", "Verifying", "#9BC6E8"),
    ("REPAIRING", "Repairing", "#E07430"),
]
OMITTED = ["QUEUED", "ANALYZING", "PROVISIONING", "FINALIZING"]


def load_runs():
    """Last record wins per run id, matching the append-only ledger semantics of the measurement."""
    by_id = {}
    with open(LEDGER, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                record = json.loads(line)
                by_id[record["run_id"]] = record
    return list(by_id.values())


def median_seconds(runs, config_id, phase):
    durations = [
        (run.get("phase_durations_seconds") or {}).get(phase, 0.0)
        for run in runs
        if run["config_id"] == config_id
    ]
    return statistics.median(durations) if durations else 0.0


def draw(runs, exercise_type, out_path):
    cell_runs = [r for r in runs if r["exercise_type"] == exercise_type and not r.get("serial")]
    config_ids = sorted({r["config_id"] for r in cell_runs}, key=lambda v: int(v[1:]))

    figure, axes = plt.subplots(figsize=(9.0, 3.4))
    bottoms = [0.0] * len(config_ids)
    for phase, label, colour in PHASES:
        values = [median_seconds(cell_runs, c, phase) for c in config_ids]
        axes.bar(config_ids, values, bottom=bottoms, label=label, color=colour, width=0.68)
        bottoms = [b + v for b, v in zip(bottoms, values)]

    omitted_share = sum(
        median_seconds(cell_runs, c, phase) for c in config_ids for phase in OMITTED
    ) / max(sum(bottoms), 1.0)

    axes.set_xlabel(
        "Configuration (n = 6 per cell; %s account for %.1f %% of the total)"
        % (", ".join(p.capitalize() for p in OMITTED), omitted_share * 100)
    )
    axes.set_ylabel("Median seconds")
    axes.set_axisbelow(True)
    axes.yaxis.grid(True, color="#DAD7CC", linewidth=0.6)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    axes.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        frameon=False,
        fontsize="small",
        borderaxespad=0.0,
    )
    figure.patch.set_facecolor("white")
    figure.tight_layout()
    figure.savefig(out_path, format="pdf")
    plt.close(figure)
    print("wrote", out_path)


def main(out_dir=FIGURES):
    os.makedirs(out_dir, exist_ok=True)
    runs = load_runs()
    for exercise_type in ("programming", "quiz"):
        draw(runs, exercise_type, os.path.join(out_dir, "phases-%s.pdf" % exercise_type))


if __name__ == "__main__":
    main()
