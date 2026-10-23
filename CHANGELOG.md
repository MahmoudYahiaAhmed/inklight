# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [SemVer](https://semver.org/).

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
