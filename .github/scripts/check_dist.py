"""Check a built wheel and sdist contain only what an installation needs.

Usage: python .github/scripts/check_dist.py dist/

The wheel may hold the package's code, the workspace's static assets, the license files of bundled model code and
package metadata. The sdist may hold the same sources plus the build hook, README, CHANGELOG and license files. Sample
documents, screenshots, results, notebooks, databases, logs, model weights, caches and repository-only folders fail
the check, wherever they are.
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

PACKAGE = "inklight"
WHEEL_MAX = 2 * 2**20
SDIST_MAX = 2 * 2**20

# Extensions that belong in the package. Anything else (a .pdf, .png, .db, .ipynb, .onnx…) fails.
CODE = {".py", ".typed", ".js", ".css", ".html", ".svg"}
LICENSES = {"LICENSE", "NOTICE", "THIRD_PARTY_LICENSES.md"}
# hatchling adds .gitignore so a wheel built from the sdist ignores the same files
SDIST_TOP = {"pyproject.toml", "PKG-INFO", ".gitignore", "hatch_build.py", "README.md", "CHANGELOG.md", *LICENSES}
BANNED_PARTS = {"__pycache__", "tests", "bench", "evaluation", "examples", "pilot", "docs", ".git", ".venv"}


def wheel_problems(names: list[str]) -> list[str]:
    problems = []
    for name in names:
        path = PurePosixPath(name)
        top = path.parts[0]
        if top.endswith(".dist-info"):
            if len(path.parts) > 2 and path.parts[1] == "licenses" and path.name not in LICENSES:
                problems.append(f"unexpected license file {name}")
            continue
        if top != PACKAGE:
            problems.append(f"outside the package: {name}")
        elif BANNED_PARTS & set(path.parts[1:-1]):
            problems.append(f"repository-only folder: {name}")
        elif path.suffix not in CODE and path.name not in LICENSES:
            problems.append(f"not code, asset or license: {name}")
    return problems


def sdist_problems(names: list[str]) -> list[str]:
    problems = []
    for name in names:
        parts = PurePosixPath(name).parts[1:]  # below inklight-<version>/
        if not parts:
            continue
        if len(parts) == 1:
            if parts[0] not in SDIST_TOP:
                problems.append(f"unexpected top-level file: {name}")
        elif parts[:2] != ("src", PACKAGE):
            problems.append(f"outside src/{PACKAGE}: {name}")
        else:
            problems += [p.replace("outside the package", "outside src") for p in wheel_problems(["/".join(parts[1:])])]
    return problems


def main(folder: str) -> int:
    dist = Path(folder)
    wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(f"expected one wheel and one sdist in {dist}, found {len(wheels)} and {len(sdists)}")
        return 1
    with zipfile.ZipFile(wheels[0]) as z:
        wheel = [n for n in z.namelist() if not n.endswith("/")]
    with tarfile.open(sdists[0]) as t:
        sdist = [m.name for m in t.getmembers() if m.isfile()]
    problems = wheel_problems(wheel) + sdist_problems(sdist)
    for f, limit in ((wheels[0], WHEEL_MAX), (sdists[0], SDIST_MAX)):
        if f.stat().st_size > limit:
            problems.append(f"{f.name} is {f.stat().st_size / 2**20:.1f} MiB, over {limit / 2**20:.0f} MiB")
    if not any(n.endswith("server/static/index.html") for n in wheel):
        problems.append("the wheel has no workspace assets (server/static/index.html)")
    for p in problems:
        print("FAIL", p)
    print(f"{wheels[0].name}: {len(wheel)} files, {wheels[0].stat().st_size / 1024:.0f} KiB")
    print(f"{sdists[0].name}: {len(sdist)} files, {sdists[0].stat().st_size / 1024:.0f} KiB")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dist"))
