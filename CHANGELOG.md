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

### Configuration
- Config schema version `1`. Configs declaring a newer version are rejected with a clear message.
  Future migrations will run oldest-first in `config._migrate`.
- Library database schema version `1` (`meta.schema_version`).
