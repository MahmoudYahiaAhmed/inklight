# Archived evaluation material

Superseded runs and retired tooling were removed from the active tree on 2026-10-27. Nothing was rewritten or
deleted from Git history: every file is still in commit
[`146d275`](https://github.com/MahmoudYahiaAhmed/inklight/tree/146d27556684cdd872b41e3de37d619092e1fe02), at its
original path. The reports in this folder keep their numbers, including every failure, and link to the archived
files at that commit.

To get the files back in a checkout:

```bash
git restore --source=146d275 -- evaluation/results/external pilot
```

or browse a single file at `https://github.com/MahmoudYahiaAhmed/inklight/blob/146d275/<original path>`.

## What was archived, and why

| Original path | Files | Why it left the active tree | Reported in |
|---|---:|---|---|
| `evaluation/results/external/{base,fix1,fix2,prefinal,unplanned,final,digitloss,devtasks,partial,fresh1,fresh2,diagnostic}-*.json` | 93 | Development history of the receipt and invoice benchmark (builds A–I). The 0.3 reruns (`v030-*.json`) replace them as current results. | [BENCHMARKS.md](BENCHMARKS.md) |
| `evaluation/results/external/rescored/*.json`, except builds H on the fresh split | 88 | The same runs re-scored with five outcomes. Build H on the fresh split, which the report cites, stays. | [BENCHMARKS.md](BENCHMARKS.md) |
| `evaluation/results/usecases/{dev,p0}-*.json`, `synthetic-bench-p0.json` | 9 | Development iterations of the use-case evaluation, before its final runs. | [EVALUATION.md](EVALUATION.md) |
| `evaluation/results/usecases/fresh{2,3,4,5}-first-access-*` for builds other than each split's frozen build | 5 | Before-and-after comparisons of fixes. The frozen build's first run on each fresh split stays. | [EVALUATION.md](EVALUATION.md) |
| `evaluation/results/capability-diag-baseline4.*`, `capability-diag-dates.json` | 3 | Earlier capability diagnostics; the `diag26` runs are the ones reported. | [CAPABILITIES.md](CAPABILITIES.md) |
| `evaluation/structure_showcase_0.2.ipynb` | 1 | A 0.2.0b1 notebook with its outputs. It uses that version's Docling runtime and does not run on 0.3. | — |
| `pilot/`, `evaluation/results/pilot/`, `tests/test_pilot.py` | 17 | The invoice-only pilot protocol, never started: no genuine invoice was collected and the human rehearsal was not run. Its frozen baseline (0.1.1.dev0 with the separate `indra-ocr` 1.1.2 package and its lock file) is two releases old, and its stored runs used baseline 1. The tooling still imported on 0.3 and its tests passed at `146d275`. To resume it, restore `pilot/` and `tests/test_pilot.py` and freeze a new baseline with `pilot/freeze.py`. | [pilot/README.md at 146d275](https://github.com/MahmoudYahiaAhmed/inklight/blob/146d27556684cdd872b41e3de37d619092e1fe02/pilot/README.md) |

The exact list is the output of `git diff --name-status 146d275 <cleanup commit> -- evaluation pilot tests`.

## What stays

- The [technical report](REPORT.md) and everything `report/build.py` reads to regenerate it.
- Each report's summary of its runs, with every failure.
- The raw results each report rests on: the 0.3 reruns, the first run of each independent split, the agent-run
  evaluation and its amendment, the structure comparisons and the model-move check.
- The scripts in `bench/` that produced them.

`tests/test_textnorm.py` re-scores the stored predictions with the current comparison. It used to re-score all
21,632 archived rows and now re-scores the 2,794 rows still in the tree (both datasets, dev, holdout and fresh
splits). Restoring `rescored/` from `146d275` runs it on every row again.

## Size

Removing files from the tree does not shrink the repository's history: a clone still downloads the archived files
as old Git objects. What shrinks is the checkout, the source of every build and anything that copies the tree.
