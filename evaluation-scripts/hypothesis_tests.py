"""Hypothesis tests for the evaluation chapter.

Reads the stored ledger (`results/runs.jsonl`) and the stored rubric records
(`results/rubric.jsonl`) and writes `output/hypothesis-tests.csv`.

Written for the thesis, after the measurement finished. It touches nothing under
`results/`; it only reads. Pure standard library, so it runs without installing
anything.

Test choice. Completion is a binary outcome per run with six runs per cell, so the
test is Fisher's exact test rather than a t-test: the normal approximation behind a
t-test does not hold for a proportion at this sample size. Wall-clock times are
right-skewed and bounded below, and rubric scores are ordinal on a five-point scale,
so both are compared with the Mann-Whitney U test rather than a t-test on means.
"""

import json
import math
import pathlib
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
RUNS = ROOT / "results" / "runs.jsonl"
RUBRIC = ROOT / "results" / "rubric.jsonl"
OUT = ROOT / "output" / "hypothesis-tests.csv"


def read_jsonl(path):
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


# --- Fisher's exact test -----------------------------------------------------


def _hypergeom(a, b, c, d):
    """Probability of the exact table [[a, b], [c, d]]."""
    return math.exp(
        math.lgamma(a + b + 1)
        + math.lgamma(c + d + 1)
        + math.lgamma(a + c + 1)
        + math.lgamma(b + d + 1)
        - math.lgamma(a + b + c + d + 1)
        - math.lgamma(a + 1)
        - math.lgamma(b + 1)
        - math.lgamma(c + 1)
        - math.lgamma(d + 1)
    )


def fisher_exact(a, b, c, d, alternative="less"):
    """Fisher's exact test on [[a, b], [c, d]].

    `alternative="less"` tests whether the odds ratio of the first row is smaller
    than that of the second, that is, whether a/(a+b) is below c/(c+d).
    `alternative="two-sided"` sums every table no more probable than the observed one.
    """
    n = a + b + c + d
    row1, col1 = a + b, a + c
    lo = max(0, row1 + col1 - n)
    hi = min(row1, col1)
    observed = _hypergeom(a, b, c, d)
    total = 0.0
    for x in range(lo, hi + 1):
        p = _hypergeom(x, row1 - x, col1 - x, n - row1 - col1 + x)
        if alternative == "less" and x <= a:
            total += p
        elif alternative == "greater" and x >= a:
            total += p
        elif alternative == "two-sided" and p <= observed * (1 + 1e-9):
            total += p
    return min(total, 1.0)


# --- Mann-Whitney U ----------------------------------------------------------


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def mann_whitney(x, y, alternative="two-sided"):
    """Mann-Whitney U with a tie-corrected normal approximation.

    Returns U for the first sample, the p value, and the rank-biserial
    correlation as an effect size.
    """
    n1, n2 = len(x), len(y)
    ranks = _ranks(list(x) + list(y))
    r1 = sum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1
    mu = n1 * n2 / 2
    counts = defaultdict(int)
    for value in list(x) + list(y):
        counts[value] += 1
    n = n1 + n2
    tie_term = sum(t**3 - t for t in counts.values())
    sigma = math.sqrt(n1 * n2 / 12 * ((n + 1) - tie_term / (n * (n - 1))))
    if sigma == 0:
        return u1, 1.0, 0.0
    z = (u1 - mu) / sigma
    correction = 0.5 / sigma
    if alternative == "two-sided":
        z_adj = (abs(u1 - mu) - 0.5) / sigma
        p = 2 * (1 - _normal_cdf(abs(z_adj)))
    elif alternative == "greater":
        p = 1 - _normal_cdf(z - correction)
    else:
        p = _normal_cdf(z + correction)
    effect = 2 * u1 / (n1 * n2) - 1
    return u1, min(max(p, 0.0), 1.0), effect


def _normal_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return float("nan")
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


# --- The hypotheses ----------------------------------------------------------

DIFFICULTY = {"C1", "C2"}
REDESCRIPTION = {"C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13"}


def main():
    runs = read_jsonl(RUNS)
    rubric = read_jsonl(RUBRIC)
    scores = {record["run_id"]: record for record in rubric}
    rows = []

    completed = lambda r: r["terminal_phase"] == "COMPLETED"
    prog = [r for r in runs if r["exercise_type"] == "programming"]
    quiz = [r for r in runs if r["exercise_type"] == "quiz"]

    # H1: a request for a harder programming exercise completes less often than
    # every other request on the same exercise type.
    hard = [r for r in prog if r["config_id"] == "C2"]
    rest = [r for r in prog if r["config_id"] != "C2"]
    a = sum(1 for r in hard if completed(r))
    b = len(hard) - a
    c = sum(1 for r in rest if completed(r))
    d = len(rest) - c
    p = fisher_exact(a, b, c, d, "less")
    rows.append(
        [
            "H1",
            "Completion, programming C2 (harder) against the other 13 programming configurations",
            "Fisher's exact test, one-sided",
            f"{a}/{len(hard)} vs {c}/{len(rest)}",
            f"{p:.2e}",
            f"rate {a / len(hard):.2f} vs {c / len(rest):.2f}",
        ]
    )

    # H2: readiness is lower for difficulty requests than for requests that only
    # redescribe the exercise (domain, narrative, or both).
    for exercise_type in ("programming", "quiz"):
        diff_scores = [
            scores[r["run_id"]]["scores"]["readiness"]
            for r in runs
            if r["exercise_type"] == exercise_type
            and r["config_id"] in DIFFICULTY
            and r["run_id"] in scores
        ]
        redesc_scores = [
            scores[r["run_id"]]["scores"]["readiness"]
            for r in runs
            if r["exercise_type"] == exercise_type
            and r["config_id"] in REDESCRIPTION
            and r["run_id"] in scores
        ]
        u, p, effect = mann_whitney(diff_scores, redesc_scores, "less")
        rows.append(
            [
                "H2" + ("p" if exercise_type == "programming" else "q"),
                f"Readiness, difficulty requests against redescription requests, {exercise_type}",
                "Mann-Whitney U, one-sided",
                f"n={len(diff_scores)} vs n={len(redesc_scores)}, U={u:.1f}",
                f"{p:.2e}",
                f"median {median(diff_scores):.1f} vs {median(redesc_scores):.1f}, rank-biserial {effect:.2f}",
            ]
        )

    # H3: a programming variant takes longer to produce than a quiz variant.
    u, p, effect = mann_whitney(
        [r["wall_seconds"] for r in prog], [r["wall_seconds"] for r in quiz], "greater"
    )
    rows.append(
        [
            "H3",
            "Wall-clock time per run, programming against quiz",
            "Mann-Whitney U, one-sided",
            f"n={len(prog)} vs n={len(quiz)}, U={u:.1f}",
            f"{p:.2e}",
            f"median {median([r['wall_seconds'] for r in prog]) / 60:.1f} vs "
            f"{median([r['wall_seconds'] for r in quiz]) / 60:.1f} minutes, "
            f"rank-biserial {effect:.2f}",
        ]
    )

    # H4: a run that needs more than one verification attempt takes longer.
    for exercise_type in ("programming", "quiz"):
        subset = [r for r in runs if r["exercise_type"] == exercise_type]
        once = [r["wall_seconds"] for r in subset if r["attempts_used"] <= 1]
        more = [r["wall_seconds"] for r in subset if r["attempts_used"] > 1]
        u, p, effect = mann_whitney(more, once, "greater")
        rows.append(
            [
                "H4" + ("p" if exercise_type == "programming" else "q"),
                f"Wall-clock time, runs with repairs against runs without, {exercise_type}",
                "Mann-Whitney U, one-sided",
                f"n={len(more)} vs n={len(once)}, U={u:.1f}",
                f"{p:.2e}",
                f"median {median(more) / 60:.1f} vs {median(once) / 60:.1f} minutes, "
                f"rank-biserial {effect:.2f}",
            ]
        )

    with OUT.open("w") as handle:
        handle.write("hypothesis,comparison,test,sample,p_value,effect\n")
        for row in rows:
            handle.write(",".join('"' + str(field).replace('"', "'") + '"' for field in row) + "\n")
    for row in rows:
        print(" | ".join(str(field) for field in row))


if __name__ == "__main__":
    main()
