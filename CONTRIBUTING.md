# Contributing

Thanks for helping make Inklight better.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                            # downloads Indra's models on the first run
inklight models pull                              # optional: enables the model tests
```

## Ground rules

- **Tests first.** New behaviour comes with a test. Bug fixes come with a regression test. Tests must not
  need network access or external APIs (mock them, as `tests/test_models_remote_watch.py` does).
- **Evidence over eloquence.** Any feature that returns facts must return provenance (`Source`) and must
  be able to say "not found".
- **No new agent capabilities without a threat review.** New tools need typed arguments, a permission
  level and documented side effects. Shell or code execution will not be accepted as a default.
- **Benchmarks are reproducible or absent.** Do not add numbers to docs that `bench/` cannot regenerate.
- Style: `ruff format`, `ruff check`, `mypy src` must pass. Keep modules focused (< 500 lines).
- Commits: [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` …).

## Test markers

- `ocr`: needs Indra (downloads ~76 MB on first use).
- `models`: needs `inklight models pull`; skipped otherwise.

Run the fast subset with `pytest -m "not ocr"`.
