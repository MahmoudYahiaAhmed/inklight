# Inklight pilot: human-reviewed genuine invoices

**Status: the workflow is ready; data collection is pending.** No genuine invoices have been collected,
reviewed or measured yet. Every number in this folder comes from synthetic invoices or from development
data, and is labelled so. Nothing here is a pilot result.

The pilot measures, on 50–100 permissioned **genuine** invoices from several vendors and layouts:

- **field accuracy**, **silent errors** (wrong values that ask for no review) and **coverage without
  review**, against values a person approved;
- **review burden**: how many values are flagged and corrected, and how long a review takes;
- **time against manual entry** of the same fields;
- whether later improvements help, on a **reserved group** of vendors that development never sees.

Synthetic invoices and receipts can be run through the same workflow, but each stays in its own cohort
(`synthetic-invoice`, `receipt`), and no number ever combines cohorts.

## 1. The frozen baseline

The pilot runs one exact build. `pilot/baseline.json` and `pilot/requirements-lock.txt` record it:

| | |
|---|---|
| Code | `inklight 0.1.1.dev0`, built at `aaa8c31` (src tree `35997c3`, identical to `89e03e3`) |
| Installed package digest | `cbb355dc978c…` (sha256 over every file of the installed package) |
| Wheel | `inklight-0.1.1.dev0-py3-none-any.whl`, built at `200e0f3` (same src tree), sha256 `a7645ea92b086206…` |
| Python and packages | 3.12.10; 42 packages pinned in `requirements-lock.txt` |
| OCR | `indra-ocr 1.1.2` with its pinned model snapshot; 12 files copied and hashed |
| Small models | reader `Xenova/distilbert-base-cased-distilled-squad` @ `bdbb0a5`, embedder `Xenova/bge-small-en-v1.5` @ `ea104da`; copied and hashed (not used by the `rules` brain the pilot runs with) |
| Settings | `brain = rules`, `second_reading = true`, `allow_download = false` (`pilot-config.toml`) |

The model files live outside the repository (`--models-out`, about 170 MB). **Before every review
session**, run:

```bash
python -I pilot/freeze.py verify --models <models dir> --config <models dir>/pilot-config.toml
```

It recomputes the package digest, the installed versions, every model hash and the settings, and exits
non-zero on any difference. It was tested to fail on a changed model byte, on `second_reading = false`, and
in a different environment.

A new build (after fixes) gets a **new** frozen baseline. Reviews record which baseline produced their
predictions, and `evaluate.py` refuses to mix baselines.

## 2. Permissions and intake

1. For each invoice, get permission from its owner. The permission scope must include **evaluation**. If
   the invoice is also to be used for development (looking at failures), the scope must say so. Record
   where the permission is kept (`permission_ref`).
2. Redact personal data the permission does not cover. The intake rejects a document marked
   `personal_data = yes` that is neither redacted nor covered by the scope.
3. Fill in a manifest (`manifest_template.csv`): file, cohort, vendor, layout tag, source, permission
   reference and scope, personal data, redacted.
4. Run the intake:

```bash
python -I pilot/intake.py --manifest manifest.csv --data <pilot data dir> --reserved-share 0.4
```

The intake checks every row and takes each file at most once (sha256). It stores files under
`<data>/<cohort>/<split>/<hash>.<ext>`, so no names appear in paths. It writes `<data>/intake.json`, which
holds vendor names; keep it with the data, never in the repository.

**Genuine invoices are split by vendor, not by document.** About 40% of vendors, chosen by a salted hash,
go to `reserved` with all their invoices. The salt and share are recorded and cannot change. The intake
warns when the reserved group has fewer than 20 invoices or 5 vendors.

Targets for the 50–100 invoices: at least 10 vendors and at least 3 layouts, with no vendor above 15% of the
documents. Record the layout tag consistently (for example "two-column header", "table summary", "scan",
"photo").

## 3. Review sessions

Ingest the documents into the pilot library, then start the workspace:

```bash
inklight process <data>/genuine-invoice -c <models dir>/pilot-config.toml
set INKLIGHT_PILOT_BASELINE=aaa8c31     # recorded on every review; use export on macOS and Linux
inklight serve -c <models dir>/pilot-config.toml
```

In the **Review** tab, a reviewer opens a document in the viewer and starts a review. For every field
(vendor, customer, invoice number, date, due date, subtotal, tax, total) they see:
- the predicted value and its OCR text
- its confidence and warning (⚠ marks a flagged value)
- the page with the value's box outlined, by clicking the prediction

They then **accept**, **correct**, or mark the field **absent**. Approval needs a decision on every
field.

What is kept, and cannot be changed afterwards:
- the prediction as it was when the review opened (a database trigger refuses edits)
- the warning, the reviewer's final value and action, and the approval
- an append-only history (opened, set, approved, reopened with a reason, exported)

Only approved reviews are exported: in the Review tab, or with `inklight review export --out file.csv
--actor <name>`.

**Manual entry, for the time comparison.** Choose "Manual entry" mode. The predictions stay hidden (they
are still recorded) and the reviewer types every value. Protocol:
- Assign about 25% of the documents, at random, to a manual entry by a **second** reviewer, done **before**
  anyone reviews that document. This avoids anchoring on the predictions and on the first reviewer's
  answers.
- Every document still gets a normal review by the first reviewer.
- `evaluate.py` then compares the two final values on those documents. That agreement is the check on the
  ground truth itself.

Timing records two things:
- **wall time**, from opening a review to approval
- **active time**, counted only while the review page is visible and focused, and kept across a reload

Ask reviewers to finish one document before starting the next, and not to leave a review open during a
break. The active timer depends on the browser reporting focus correctly. In the automated rehearsal it
reported 0 s, so compare it with wall time before trusting it.

## 4. Evaluation

```bash
# development group: metrics plus a failure list for development
python -I pilot/evaluate.py --config <models dir>/pilot-config.toml --intake <data>/intake.json \
    --cohort genuine-invoice --split dev --out results/

# a finished improvement (new frozen baseline installed): new predictions, same approved values
python -I pilot/evaluate.py ... --split dev --repredict --out results-new/

# the reserved group: only for a finished build; needs a reason, and every access is logged
python -I pilot/evaluate.py ... --split reserved --repredict \
    --reason "evaluate build <commit> after fixes A, B" --out results-reserved/
```

Ground truth is the approved final value. Metrics are reported with 95% Wilson intervals; with 50–100
invoices they are wide, so read them:
- field accuracy, coverage without review, precision among unflagged values, and silent-error rate, overall
  and per field
- share of predicted values flagged and corrected
- active and wall seconds per document
- manual-entry time, the review/manual time ratio, and agreement on documents entered both ways

**Development uses dev failures only.** `--split dev` writes `*-failures.csv`, with every wrong or missing
value, its OCR text, method, confidence and warning. `--split reserved` writes aggregates only and appends
to `<data>/reserved_access.log`. Evaluate the reserved group once per finished build, never while choosing
what to change, and report every access in the write-up.

## 5. What has been checked so far (not pilot results)

**Rehearsal on synthetic invoices** (`results/dryrun-synthetic/`): 60 Voxel51 *development* invoices, the
frozen environment and config, and a **scripted** reviewer that takes final values from the dataset
annotations.
- The run completed: intake 60/60, 75 approved reviews (15 entered both ways), 450 exported rows.
- The evaluator gives the same accuracy and silent-error rate as the benchmark harness on the same
  predictions: 99.4% and 0.3%.
- `--repredict` with the same build reproduces the frozen-prediction numbers exactly.
- The failure list names 2 values. One is the known case where the dataset annotates the net amount as the
  total, so a human reviewer looking at the page would approve Inklight's value instead.
- Timings are 0 s and agreement is perfect by construction. Neither means anything for real reviewers.

**Latency of the second OCR reading** (`results/latency-dev/latency.json`): development splits only, the
frozen environment, 3 alternating repeats, AMD Zen 4 laptop CPU.

| Dev data | Extraction per document, median (on / off) | p90 (on / off) | Mean (on / off) | Second readings per 60 documents | OCR ingest per document |
|---|---|---|---|---|---|
| Voxel51 invoices (synthetic) | 10.8 / 11.3 ms | 16.1 / 15.8 ms | 26.1 / 11.7 ms | 2 (0.34 s each) | 0.32 s |
| CORD receipts (genuine) | 4.1 / 4.2 ms | 7.8 / 8.1 ms | 4.7 / 4.9 ms | 0 | 0.13 s |

A second reading costs about 0.34 s, close to OCR'ing a whole invoice page, because it decodes the page
again. It runs on few documents, so the median is unchanged; the mean rises by 14 ms per invoice. Run it
again on the pilot's own dev invoices: how often it triggers depends on the documents.

## 6. Remaining limitations

1. **No genuine invoice has been measured.** Collection, permission and review are still to do. The workflow
   was rehearsed only on synthetic invoices with a scripted reviewer.
2. **Ground truth is a person.** Reviewers can anchor on predictions. The 25% manual-entry subset measures
   agreement, but does not remove the bias. A single reviewer per document is not double annotation.
3. **Small samples.** With 50–100 invoices, and a reserved group of perhaps 20–40, confidence intervals are
   wide. A difference of a few points between builds may not be distinguishable.
4. **Active time depends on the browser's focus events.** It read 0 s in the automated rehearsal. Wall time
   includes interruptions. Compare the two before reporting.
5. **Manual-entry time is measured in Inklight's own form,** not in the tool reviewers use today. The real
   saving against an existing process needs a timing in that process.
6. **Reviews need the review screen.** The viewer and the field table sit side by side only on screens at
   least 1100 px wide. On narrower screens the viewer covers the form and must be closed.
7. **Reviewer identity is self-declared** (a name typed into the form). For audit-grade records, run the
   server behind real authentication (`INKLIGHT_SERVER_TOKEN` only checks for a shared token).
8. **The fields are fixed** to the invoice set listed above. Line items, currency codes and tax
   breakdowns are not reviewed.
9. **The second reading works only for images at rotation 0.** For PDFs and rotated scans, the amount check
   uses its other signals only.
10. **The aggregate-state fix (`69675a0`) changes reported states, not extracted values.** It is not
    expected to change any accuracy figure, and none is attributed to it.
