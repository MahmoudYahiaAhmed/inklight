# Contributing

Thanks for helping make Inklight better.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[structure,dev]"
pytest                                            # downloads the OCR models on the first run
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

- `ocr`: needs the OCR models (downloads ~76 MB on first use).
- `structure`: needs the structure runtime (`[structure]`) and its models (~384 MB on first use).
- `models`: needs `inklight models pull`; skipped otherwise.

Run the fast subset with `pytest -m "not ocr"`.

## Pull requests

1. Fork the repository and work on a branch in your fork. Only the maintainer can push to this repository.
2. Open a pull request against `main` and fill in the template.
3. CI does not run on a pull request from outside until the maintainer has looked at it and approved the
   run. Fork pull requests never receive repository secrets.
4. A pull request is merged only after the maintainer approves it, every CI check passes and every review
   conversation is resolved. A new push after the approval needs a new approval.
5. Pull requests are squash-merged, so keep the title in Conventional Commits form: it becomes the commit
   message on `main`.

Security problems go through private reporting, not a pull request: see [SECURITY.md](SECURITY.md).
