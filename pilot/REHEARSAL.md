# Human rehearsal (5–10 invoices) — before the pilot expands

**Status: not run yet.** An automated walkthrough of the same steps in the browser (no people, no timing)
passed on synthetic invoices; it checks the mechanics only and does not count as the rehearsal. It needs two people and 5–10 permissioned genuine invoices. A script cannot stand in
for it: `check_rehearsal.py` refuses to count scripted reviews, and no timing in this repository comes from
a person yet.

The rehearsal checks that the workflow works in real hands: corrections, rejected inputs, approvals, a
reopening, export, and timing. It does **not** measure accuracy, because 5–10 invoices are far too few.
Its documents and reviews stay out of the scored pilot.

## What you need

| | |
|---|---|
| Invoices | 5–10 genuine invoices with permission recorded, from at least 3 vendors and 2 layouts. Include at least one scan or photo. If the pilot will contain Arabic invoices, include one. |
| People | Reviewer A (reviews every invoice) and reviewer B (types 2 invoices by hand, before A sees them) |
| Screen | at least 1100 px wide, so the page and the fields sit side by side |
| Build | the frozen pilot baseline (baseline 3, `0479e68`, installed in `C:/Users/pc/inklight-pilot-b3`) |
| A stopwatch | a phone is fine: it is the independent check on the recorded times |

## Setup (coordinator)

Keep the rehearsal in its own data folder and its own library, so none of it ends up in the scored pilot.

```bash
python -I pilot/freeze.py verify --models <models dir> --config <models dir>/pilot-config.toml
# copy pilot-config.toml to rehearsal-config.toml and point `home` at a new, empty folder
python -I pilot/intake.py --manifest rehearsal-manifest.csv --data <rehearsal data dir>
inklight process <rehearsal data dir>/genuine-invoice -c rehearsal-config.toml
set INKLIGHT_PILOT_BASELINE=0479e68       # use export on macOS and Linux
inklight serve -c rehearsal-config.toml
```

## Session

**Reviewer B first (manual entry, 2 invoices).** Review tab → mode "Manual entry", then for each invoice:
1. Start the stopwatch and start the review.
2. Type every value, or mark it absent.
3. Approve, then stop the stopwatch.
4. Write both times on the sheet below.

**Reviewer A (review, every invoice).** Review tab → mode "Review". For each invoice, start the stopwatch,
start the review, and work through it. Across the session, make sure each of these happens at least once:

| # | Do this | Expect |
|---|---|---|
| 1 | Click a prediction | The page scrolls to it and outlines its box |
| 2 | Accept a correct value | ✓ accepted |
| 3 | Correct a wrong value; type an amount the way the invoice writes it (e.g. `1.234,56`, `Rp 63.000`) | The parsed value is shown next to what you typed |
| 4 | Type `100 + 20`, then `1e3` | Each is refused with a reason; nothing is saved until a plain amount is typed |
| 5 | Type a negative as `(45.00)` | Stored as −45.00 |
| 6 | Mark a field that the invoice does not have as absent | ✓ absent |
| 7 | Approve | The approve button stays disabled until every field has a decision |
| 8 | On one invoice, hide the window for one timed minute (switch to another app), then come back | The active time recorded is about one minute less than the stopwatch |
| 9 | Reopen one approved review with a reason, change a value, approve again | The history shows reopened (with the reason) and the second approval |

Stop the stopwatch at each approval and write the time on the sheet.

At the end, either reviewer exports from the Review tab (Export approved) and saves the CSV.

## Check

```bash
python -I pilot/check_rehearsal.py --config rehearsal-config.toml --export inklight-reviews.csv --out rehearsal-check/
```

The check reads the library through a read-only snapshot, and fails on any of:
- an approved review with an undecided field, or a history that does not run from opened to approved
- a reopening without a reason
- a correction without the reviewer's typed input
- an export that is missing an approved review, holds an unapproved one, or differs from the reviews
- active time missing, zero, or above wall time
- fewer than 2 reviewers, 1 manual entry, 1 correction or 1 reopening

It lists reviews left open for more than 30 minutes.

**Expand the pilot only when:**
- `check_rehearsal.py` passes;
- on every invoice, recorded active time is within 10% of the stopwatch, after removing the deliberate
  one-minute break (if not, report wall time, not active time, in the pilot);
- no correction was lost, and every rejected input in step 4 was refused;
- both reviewers finished without help, or every point where they needed help is written down and fixed.

## Observation sheet

| Invoice | Reviewer | Mode | Stopwatch (s) | Recorded active (s) | Recorded wall (s) | Steps done (1–9) | Problems, confusion, ideas |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

Keep the sheet with the rehearsal data, not in the repository: it may name people and vendors. Record in
the pilot write-up only the check result, the time agreement, and the problems found.
