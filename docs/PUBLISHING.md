# Publishing Inklight: GitHub and PyPI, step by step

Checked on 2026-10-24: `inklight` is free on PyPI and TestPyPI, and `github.com/MahmoudYahiaAhmed/inklight`
does not exist yet. The local repository is initialised on branch `main` with the first commit.

No secrets are needed anywhere: PyPI publishing uses **Trusted Publishing** (GitHub proves its identity to
PyPI). Do not create or paste PyPI API tokens.

## 1. Create the GitHub repository (browser, 2 minutes)

1. Open https://github.com/new while signed in as `MahmoudYahiaAhmed`.
2. Repository name: `inklight`. Description: `See documents. Understand meaning. Take action. A local-first OCR document agent.`
3. Visibility: **Public** (PyPI users expect public source; private also works for CI).
4. **Do not** add a README, .gitignore or license: the project already has them.
5. Click **Create repository**.

## 2. Push the code (terminal)

```bash
cd C:\Users\pc\inklight
```
```bash
git remote add origin https://github.com/MahmoudYahiaAhmed/inklight.git
```
```bash
git push -u origin main
```

Git will ask you to sign in through the browser the first time. After the push, open the **Actions** tab:
the `ci` workflow runs lint, the tests on Linux/Windows/macOS × Python 3.11–3.13, and a wheel build.
Expect the first run to take ~10 minutes (it downloads Indra's models once, then caches them).

## 3. Repository settings (browser)

- **About** (gear icon on the repo page): website = your landing page, topics = `ocr`, `document-ai`, `agent`,
  `python`, `pdf`, `invoice`, `local-first`.
- **Settings → Code security**: enable *Private vulnerability reporting*, *Dependabot alerts* and *security updates*.
- **Settings → Branches**: add a rule for `main` that requires the `ci` checks to pass before merging.
- **Settings → Environments**: create two environments, `pypi` and `testpypi`. For `pypi`, add yourself as a
  required reviewer so a release waits for your click.

## 4. Connect PyPI (browser, one time)

1. Create accounts on https://pypi.org and https://test.pypi.org (turn on 2FA; PyPI requires it).
2. On **TestPyPI** → *Your account → Publishing → Add a new pending publisher*:
   - PyPI project name: `inklight`
   - Owner: `MahmoudYahiaAhmed` · Repository: `inklight`
   - Workflow name: `testpypi.yml` · Environment: `testpypi`
3. On **PyPI** → *Your account → Publishing → Add a new pending publisher*, same values but
   workflow `release.yml` and environment `pypi`.

"Pending" publishers reserve the name for you until the first upload creates the project.

## 5. Dry run on TestPyPI

GitHub → **Actions → testpypi → Run workflow** (branch `main`). It builds, uploads to TestPyPI, then installs
from there and runs `inklight --version`. Check https://test.pypi.org/project/inklight/ renders the README.

## 6. Release v0.1.0 to PyPI

```bash
git tag -a v0.1.0 -m "Inklight 0.1.0"
```
```bash
git push origin v0.1.0
```

The `release` workflow runs the tests, checks the tag matches the package version, builds, waits for your
approval (the `pypi` environment), publishes to PyPI and creates a GitHub Release with the wheel attached.
Then, from any machine:

```bash
pip install inklight
```

## 7. Every later release

1. Bump `version` in `pyproject.toml` **and** `src/inklight/__init__.py` (the release job checks they match the tag).
2. Add a CHANGELOG.md entry.
3. Commit, push, wait for green CI, then tag `vX.Y.Z` and push the tag.

## 8. After publishing

- Share the landing page (it is an Artifact: use its **Share** menu, or copy `docs/site/landing.html` into a
  GitHub Pages site).
- Pin the repository on your GitHub profile; add the PyPI link to the repo's About box.
- Before charging money for it: settle the Indra weights licence (THIRD_PARTY_LICENSES.md) and run a trademark search.

## Troubleshooting

| Problem | Fix |
|---|---|
| `remote origin already exists` | `git remote set-url origin https://github.com/MahmoudYahiaAhmed/inklight.git` |
| Push rejected: repository not empty | You added a README on GitHub. Run `git pull --rebase origin main`, then push. |
| PyPI: `invalid-publisher` | The pending publisher's owner/repo/workflow/environment must match exactly (step 4). |
| Release job fails at "tag matches version" | The tag and `__version__` differ. Fix the version, delete the tag (`git tag -d vX` and `git push origin :refs/tags/vX`), re-tag. |
| CI fails only on macOS/Linux | Run `pytest -x` there; this release candidate was only executed on Windows. |
