# Release checklist (PyPI + GitHub)

## Before the first public release (one-time)

- [ ] **Licensing decision for Indra weights.** If you sell Inklight, or offer it as a product that competes
      with Datalab, or your organisation is above $20M in revenue or funding: get a commercial license from Datalab
      or ship with a different OCR engine. See THIRD_PARTY_LICENSES.md.
- [ ] **Name clearance.** `inklight` was free on PyPI on 2026-10-23, and a web search found no product by that
      name. This is **not** a trademark search: run one (USPTO/EUIPO/WIPO) for software classes 9 and 42 before
      investing in the brand. `lumen` was rejected because it is taken on PyPI (HoloViz "Lumen AI", same domain).
- [ ] Check domain availability (e.g. inklight.dev / inklight.ai). Not verified here.
- [x] GitHub repository `MahmoudYahiaAhmed/inklight` (the URLs in `pyproject.toml` and the README point there).
- [x] Copyright holder set in `NOTICE` and `pyproject.toml` (`Mahmoud AboEl-Wfa`); change both if it should be a company.
- [ ] On PyPI, create the project with **Trusted Publishing** for `.github/workflows/release.yml`
      (environment `pypi`) — no API token is stored anywhere.
- [ ] Optionally reserve `inklight` on TestPyPI and do a dry run there first.

## Every release

- [ ] `ruff format --check src tests && ruff check src tests && mypy src`
- [ ] `pytest` is green locally and in CI on Linux, Windows and macOS for Python 3.11–3.13.
- [ ] `python bench/run.py` (and `bench/memory.py`); update evaluation/BENCHMARKS.md only from that output.
- [ ] Bump `version` in `pyproject.toml` **and** `src/inklight/__init__.py`; update CHANGELOG.md.
- [ ] `python -m build && twine check dist/*`; install the wheel in a clean venv and run
      `inklight doctor`, `inklight process examples/documents`, `inklight ask examples/documents "Find all invoices above $5,000"`.
- [ ] Commit, `git tag vX.Y.Z`, `git push --tags`. The release workflow tests, builds and publishes, then creates the GitHub release.
- [ ] Verify `pip install inklight==X.Y.Z` from PyPI in a clean environment.
- [ ] Optional: `docker build -t inklight .` and push the image. (The Dockerfile was not built in the release-candidate environment.)
