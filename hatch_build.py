"""Stamp the source commit into the build (inklight/_build.py), so an installed build says exactly what it is.

Built from a git checkout, the sdist and the wheel record the short commit and whether the tree had uncommitted
changes. The sdist carries that record as src/inklight/_build.py, so a wheel built later from the sdist (no git there)
keeps the commit it came from. A build without either (a Docker build: .git stays out of its context) takes
INKLIGHT_BUILD_COMMIT from the environment. Otherwise the record says "unknown". `inklight --version` and the
workspace show it.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

STAMP = "src/inklight/_build.py"  # in the sdist; ignored in the checkout (.gitignore)


def _git(root: str, *args: str) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - fixed git arguments, no user input
            ["git", *args],  # noqa: S607 - git from PATH, as a developer runs it
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _from_git(root: str) -> str:
    # Only this project's own repository counts: an sdist unpacked inside some other checkout must not take its commit.
    top = _git(root, "rev-parse", "--show-toplevel")
    if not top or Path(top).resolve() != Path(root).resolve():
        return ""
    commit = _git(root, "rev-parse", "--short=10", "HEAD")
    if commit and _git(root, "status", "--porcelain", "--untracked-files=no"):
        commit += "+modified"
    return commit


def _from_stamp(root: str) -> str:
    stamp = Path(root) / STAMP
    if not stamp.is_file():
        return ""
    found = re.search(r'^COMMIT = "([^"]+)"', stamp.read_text(encoding="utf-8"), re.M)
    return found.group(1) if found else ""


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:  # noqa: ARG002
        given = os.environ.get("INKLIGHT_BUILD_COMMIT", "")
        given = given if re.fullmatch(r"[0-9a-f]{7,40}", given) else ""
        commit = _from_git(self.root) or _from_stamp(self.root) or given[:10] or "unknown"
        target = Path(tempfile.mkdtemp(prefix="inklight-build-")) / "_build.py"
        target.write_text(f'"""Written when the package was built."""\n\nCOMMIT = "{commit}"\n', encoding="utf-8")
        destination = STAMP if self.target_name == "sdist" else "inklight/_build.py"
        build_data["force_include"][str(target)] = destination
