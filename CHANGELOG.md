# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [SemVer](https://semver.org/).

## [0.1.1] — Unreleased

Fixes from a second external review of `914d321`. **0.1.0 (already on PyPI) is affected by the three
defects below.** Upgrade once 0.1.1 is published.

### Fixed
- **Conditions on extraction were not applied.** "Extract totals from Acme" showed the Acme condition under
  "Understood as" but returned every document: the extraction plan had no filter step. Conditions are now
  enforced first for every workflow (extract, filter, count, aggregate, inconsistencies, summarize,
  compare, find, ask, export). The document scope narrows to the matches before the operation runs.
- **Boolean grouping was flattened.** "between $100 and $6,000 or above $10,000" became
  `>=100 OR <=6000 OR >10000`. Conditions are now a typed expression (`Cond | All[...] | Any[...]`).
  Ranges, years and months are grouped operands, and `or` between alternatives on the same field forms one
  group. The same expression is executed and rendered in "Understood as", so the two cannot drift apart.
- **Coordinated names were dropped.** "from Acme or Globex" silently lost Globex. Vendor lists
  ("Acme or Globex", "Acme, Globex and Initech") are one group, and a shared amount condition applies to the
  whole group. "not from Acme or Globex" excludes both.
- **Dropped fragments are reported.** A connector left after a condition ("… above $5,000 or Globex"), an
  unconsumed proper noun ("List Acme's invoices"), a month without a year, a time span such as
  "under 30 days", and an amount with an unknown unit ("over 5 bucks") make the result `partial` and are
  listed under Not applied.
- **Partial selections are never exported.** `write_output` refuses while any part of the request is not
  applied. Partial previews are labelled "PARTIAL RESULT, not the complete answer to your request".
- **Ambiguous `and`/`or` mixes are not guessed.** For example "from Acme or above $10,000 in 2026". Nothing
  runs, and the result state is the new `unsupported`.
- **Filtering failures cannot leak unfiltered rows.** If the filter step fails, or `max_steps` would cut it
  off, no records are returned and the state is `failed`.
- A filter that could not evaluate some documents (missing value, incompatible currency) is now `partial`,
  not `succeeded`.
- Added "N grand" (×1000) and month-year ranges ("in March 2026").

### Changed
- `validate_plan()` refuses any plan whose steps do not filter with exactly the stated expression, after
  extracting every field it reads, and before any step that uses records or the document scope.
- Requested output columns are kept separate from fields read only to evaluate conditions. Records,
  tables, CSV and JSON exports show only the requested columns.
- The optional 135M writer can no longer replace an answer. Its wording is appended under an explicit
  "not verified" label. `grounded()` is documented as a surface check (entity order and negation count),
  not semantic verification.
- Results carry `checks`, which keeps provenance, interpretation and evidence separate. The confidence fields
  are documented as heuristics, not calibrated probabilities.
- The `TaskState` enum gained `unsupported`.

## [0.1.0] — 2026-10-23

First public release candidate.

### Added
- Document library: incremental ingest (unchanged files skipped, identical content reuses OCR), SQLite +
  FTS5 index, layout-aware chunks, classification, prompt-injection scan, re-index and delete.
- Indra OCR backend (PDF text layer first, OCR where needed; PNG/JPEG/TIFF/BMP/WebP), plain-text and
  Markdown reader, pluggable engine registry.
- Typed field extraction with page/box provenance, confidence, warnings and `subtotal + tax = total`
  checks; schema files in three formats.
- Bounded agent: rule planner, 11 allow-listed tools, step limits, time budgets, cancellation, retries, trace.
- Small local models on ONNX Runtime: 66M extractive reader, 33M embedder (hybrid search), optional
  135M writer with grounding checks. Optional OpenAI-compatible remote model with quote verification.
- CLI (`process, ask, extract, search, docs, show, remove, reindex, history, watch, serve, tools, doctor, models`).
- Local web workspace: upload, library, page preview with evidence highlighting, agent, extraction, search, history, settings.
- Folder watcher automation.
- Benchmarks (`bench/`), 128 tests, CI and release workflows, Dockerfile.

### Fixed before release (external review of 478fc3d)
- Vendor and customer constraints ("invoices from Acme above $5,000") were silently dropped. They are now
  conditions (`vendor contains "Acme"`), including negation ("not from", "except").
- `or` between conditions was applied as AND. It now means any. A mix of `and`/`or` is reported instead of guessed.
- Added `between X and Y` and year conditions ("in 2026").
- Amounts in different currencies were summed into one number. Money values now carry a `unit`, sums are
  reported per currency, and filters never compare € amounts with a $ threshold.
- Requests with words no tool can apply ("paid late", "last month", "top 3", a stray amount) used to return
  `succeeded`. They now return `partial` and list the words under **Not applied**.
- Counting with conditions ("how many invoices above $8,000") ignored the conditions.
- Ambiguous numeric dates (`03/04/2026`) were read silently. They are now flagged, and `[extraction] day_first`
  sets the order.
- The currency is read from a label ("TOTAL DUE (USD)") when the amount has no symbol. Added EGP / E£.
- `grounded()` accepted "Acme owes Bob" against "Bob owes Acme". It now also requires the evidence's order of
  names and numbers, and is documented as a necessary check, not proof of correctness.
- Reader answers whose surroundings share no word with the question are penalised.

### Changed
- Results report confidence twice: `interpretation_confidence` (was the request understood) and
  `evidence_confidence` (do the documents support it). `confidence` is the lower of the two. Results also
  carry `interpretation` and `not_understood`, shown in the CLI and the web workspace.
- Docs: "verified" now explicitly means provenance (the text exists where cited), not semantic correctness.
- Benchmarks: three invoice layouts instead of one, plus a request-handling score.

### Configuration
- Config schema version `1`. Configs declaring a newer version are rejected with a clear message.
  Future migrations will run oldest-first in `config._migrate`.
- Library database schema version `1` (`meta.schema_version`).
