# Reproducibility Package: AI-Generated Exercise Variants in Artemis

Data and scripts behind the evaluation chapter of the master's thesis *Self-Paced Practice with Adaptive Exercise Variation in Learning Platforms*
by Lara Dvorsek and Dominik Remo (Technical University of Munich). The chapter reports 168 generation
runs of the exercise variant generation feature, automated checks over the resulting variants, and a
rubric rating of every variant.

Everything needed to recompute the reported numbers runs without an Artemis instance, a model
endpoint, or credentials. One command recomputes every reported number and tells you whether it came
back identical.

```
python3 reproduce.py
```

```
Ledger: 168 runs
  [ok  ] runs match their configuration: 168 runs over 14 configurations
  [ok  ] matrix is balanced: 28 cells, 6 runs each
  [ok  ] checks.jsonl: 168 runs
  [ok  ] phase durations: 168/168 runs, largest difference 0.000s
  [ok  ] tables/outcomes.csv
  [ok  ] tables/cost.csv
  [ok  ] tables/quality.csv
  [ok  ] figures/phases-programming.pdf
  [ok  ] figures/phases-quiz.pdf
  [ok  ] hypothesis-tests.csv
All 10 outputs match the shipped copy.
```

Python 3.9 or newer, verified on 3.9.6 and 3.14. The checks, the timings, the tables, and the hypothesis tests use the standard
library only; the figures need matplotlib and are skipped with a note if it is absent:

```
pip install -r evaluation-scripts/requirements.txt
```

The package separates the two kinds of file it holds. `results/` is the primary record of the
measurement: what Artemis returned, what it generated, and what the rating model wrote. `output/` is
everything the scripts here made from that record. `reproduce.py` touches neither: it writes to
`reproduced/` and compares that against `output/`, then deletes it again unless you pass `--keep`. The
exit status is non-zero if anything differs, so it also works as a check in a pipeline.

Each script can also be run on its own, and writes into `output/` where the shipped copy already sits:

```
python3 evaluation-scripts/make_figures.py        # output/figures/*.pdf
python3 evaluation-scripts/hypothesis_tests.py    # output/hypothesis-tests.csv
```

## What is measured

| | |
|---|---|
| Pipeline under test | Exercise variant generation in Artemis, branch `feature/exercise-variants-ai-generation`, prompts frozen at commit `f8bbc1b` |
| Generation model | `openai/gpt-oss-120b`, served by Logos at `https://logos.aet.cit.tum.de/v1`, temperature 0.2, no seed and no reasoning-effort setting |
| Rating model | `claude-fable-5` through Claude Code at medium thinking effort, in a session that did not run the generations and did not write the prompts |
| Design | 14 configurations × 2 exercise types × 6 replicates = 168 runs |
| Run window | 2026-08-05T19:20Z to 2026-08-06T11:50Z, rated 2026-08-06 |
| Hardware | Inference on the research group's GPU cluster; Artemis and one build agent on a MacBook Pro M1 Max, three generations in flight throughout |

## What gets recomputed, and from what

| Reported result | Recomputed from | Compared against |
|---|---|---|
| The design behind every table row | The ledger | The 14 configurations in `matrix.py` |
| Automated checks | The stored variants and the two source exercises | `output/checks.jsonl` |
| Phase durations | The per-run Artemis server logs | `phase_durations_seconds` in `results/runs.jsonl` |
| Outcome, cost, and quality tables | The ledger, the checks, and the rubric records | `output/tables/*.csv` |
| Figures | The ledger | `output/figures/`, compared byte for byte |
| Hypothesis tests | The ledger and the rubric records | `output/hypothesis-tests.csv` |

The run outcomes and the rubric scores are primary records: an outcome is what Artemis returned, and a
score is what the rating model wrote. Neither can be recomputed, so both ship in full, each rubric
score with its written reason and a verbatim excerpt from the variant it describes.

## Reading a single variant

Numbers aside, the variants themselves are readable. `review.py` renders one against the exercise it
was generated from: the problem statement, the diff across all three repositories, and the automated
checks side by side.

```
python3 evaluation-scripts/review.py results programming-C1-r1
```

## Contents

Directory names use the Artemis concepts: an *exercise* is the source exercise an instructor already
has, a *variant* is what the generation produced from it, and a *job* is one run of the generation
pipeline.

| Path | Contents |
|---|---|
| `reproduce.py` | Recomputes every reported number and checks it against the shipped copy. |
| `exercises/` | The two source exercises every variant was generated from: the programming exercise as problem statement, template, solution and test file sets, and test-case list, and the quiz as `quiz.json`. |
| `prompts/` | The seven prompt templates, as frozen at `f8bbc1b`, under which all 168 runs executed. |
| `results/runs.jsonl` | The ledger. One record per run: configuration, outcome, phase durations, tokens, wall time, attempts used, prompt commit. |
| `results/generated-variants/` | The variant each run produced, one directory per run. These are the files the rating was made from. |
| `results/rubric.jsonl` | Four scores per variant, each with a written reason and a verbatim excerpt. |
| `results/job-records/` | Full detail of the generation job per run, including warnings and step outputs. The failure taxonomy in the chapter comes from these. |
| `results/instance-logs/` | The Artemis server log lines belonging to each run. The phase timings are rebuilt from these. |
| `output/tables/` | The three tables the chapter reports. |
| `output/figures/` | The two phase-breakdown panels the chapter prints. The only figures in the package, and the only ones the thesis uses. |
| `output/checks.jsonl` | The automated checks over the generated variants. |
| `output/hypothesis-tests.csv` | The four hypothesis tests with exact p values and effect sizes. |
| `rubric.md` | The rubric: criteria, anchors, procedure, and what it does not control for. Frozen before the first score. |
| `evaluation-scripts/` | The analysis code, below. |
| `live-run/` | The code that drove the 168 generations against a running Artemis instance, and the code that built the two source exercises there. Included for the record; it cannot run without that instance, a model endpoint, and credentials, and recomputes nothing. |
| `LICENSE` | MIT. |

### evaluation-scripts

Eight files, each on the path from stored data to a reported number. None of them contacts a server.

| File | What it does |
|---|---|
| `analysis.py` | Builds `output/tables/*.csv` from the ledger. Behind every table in the chapter. |
| `checks.py` | The automated checks over the stored variants: statement integrity, byte-identical preservation per repository, quiz validity. |
| `logs.py` | Rebuilds a run's phase timeline from its server log. |
| `make_figures.py` | Draws `output/figures/*.pdf`, the two panels the chapter prints. |
| `hypothesis_tests.py` | Fisher's exact test and Mann-Whitney U for the four hypotheses, writing `output/hypothesis-tests.csv`. Standard library only. |
| `review.py` | Renders one stored variant against its source exercise. |
| `matrix.py` | The 14 configurations and the two application-domain texts, each with the reason it is in the matrix. This is what `C1` to `C14` mean in every table, and `reproduce.py` checks the ledger against it. |
| `requirements.txt` | matplotlib, for the figures; requests and urllib3, for `live-run/`. |

The code that drove the generations against a live Artemis instance is not among these eight; it is
not needed to recompute anything. It ships anyway, under `live-run/`, for the record.

## Provenance

Six files under `evaluation-scripts/` (`analysis.py`, `checks.py`, `logs.py`, `matrix.py`,
`review.py`, `requirements.txt`), the eleven files under `live-run/`, and `rubric.md` are copied from
`supporting_scripts/evaluation/` in the Artemis repository at commit `f57a0e7`, and the seven files
under `prompts/` from `src/main/resources/prompts/hyperion/variants/` at the frozen commit `f8bbc1b`.
Both commits are on the public branch `feature/exercise-variants-ai-generation`, so every copy can be
checked against its original. The other three scripts, `reproduce.py`, `make_figures.py`, and
`hypothesis_tests.py`, were written for the thesis and have no counterpart in Artemis.

The copies differ from their originals in directory names and in three removals, all listed here. No
logic was changed, and no number depends on any of it.

| Artemis | Here |
|---|---|
| `corpus/sources/` | `exercises/` |
| the analysis modules at the top level | `evaluation-scripts/` |
| `results/artifacts/` | `results/generated-variants/` |
| `results/raw/` | `results/job-records/` |
| `results/logs/` | `results/instance-logs/` |

`checks.py`, `matrix.py`, and `requirements.txt` are byte-identical to the Artemis original.
`review.py` carries four edited lines and `logs.py` one: three replace a directory name from the table
above, and the fourth is a comment that used a word this repository does not. `review.py` also
resolves its inputs from the repository root rather than from its own directory, which is what makes
it runnable here: the Artemis copy expected to sit beside `corpus/` and `results/` rather than in a
directory of its own.

Under `live-run/`, `artifacts.py`, `status.py`, `logging_config.py`, `config.ini.example`,
`quiz_questions.py`, and `exercises.json` are byte-identical to the Artemis original. `runner.py`,
`utils.py`, `run_evaluation.py`, `run_evaluation.ipynb`, and `create_exercises.py` carry edited lines,
all replacing a directory name from the table above.

Two files were also trimmed, so that nothing ships that an instructor reproducing these results would
never call. No trim changes a number: `reproduce.py` reports every output as identical either way.

- `analysis.py` lost two functions. `rescan_environment_failures` re-read the server logs for build
  failures caused by Maven Central rate limiting and appended corrected records to the ledger; its
  effect is already baked into the shipped ledger, and a shipped function that rewrites `runs.jsonl`
  is a hazard rather than a feature. `figures()` drew four figures in matplotlib's default palette,
  with an in-plot title and an inset legend. The chapter prints none of them: it uses the restyled
  panels now under `output/figures/`, and reports outcomes as a table rather than a chart. Keeping both
  would have left the package holding two versions of the same plot in different colours. The
  now-unused `datetime` import went with them, and nothing else in the file was added or altered.
- `logs.py` kept the three functions that rebuild a phase timeline (`read_lines`, `slice_for_job`,
  `build_phase_timeline`) with their helpers, and lost six that only the live-run code called:
  telemetry parsing, build-wait parsing, rate-limit detection, and the two semantic-gate readers,
  along with the constants they alone used. The file went from 318 lines to 151.

The unmodified originals of both files, and the four default-palette figures, are in the Artemis
commit named above and are kept with the thesis sources.

## One older path

`rubric.md` is kept as it was written, so it names one path this layout has since changed:

| Named in `rubric.md` | Here |
|---|---|
| `results/tables/quality.csv` | `output/tables/quality.csv` |

## Scope

This package holds what is needed to recompute and inspect the results the evaluation chapter reports.
It is not the full working record of the project. Left out, and retained with the thesis sources: the
pre-freeze pilot runs and their defect list, the gate the prompts had to pass before being frozen, and
the internal evaluation report the chapter was drafted from.
