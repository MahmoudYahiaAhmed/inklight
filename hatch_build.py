"""Stamp the source commit into the wheel (inklight/_build.py), so an installed build says exactly what it is.

A wheel built from a git checkout records the short commit and whether the tree had uncommitted changes; built
elsewhere, it records "unknown". `inklight --version` and the workspace show it.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


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


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:  # noqa: ARG002
        commit = _git(self.root, "rev-parse", "--short=10", "HEAD") or "unknown"
        if commit != "unknown" and _git(self.root, "status", "--porcelain", "--untracked-files=no"):
            commit += "+modified"
        target = Path(tempfile.mkdtemp(prefix="inklight-build-")) / "_build.py"
        target.write_text(f'"""Written when the wheel was built."""\n\nCOMMIT = "{commit}"\n', encoding="utf-8")
        build_data["force_include"][str(target)] = "inklight/_build.py"
