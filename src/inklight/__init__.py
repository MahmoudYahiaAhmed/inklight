"""Inklight — a local-first, OCR-powered document agent.

See documents. Understand meaning. Take action.
"""

from __future__ import annotations

from ._brand import NAME, TAGLINE
from .agent import DocumentAgent, Policy
from .config import Settings, load_settings
from .errors import InklightError, InputRejected, ModelUnavailable, OCRError, PermissionDenied
from .library import Library
from .schemas import AgentResult, DocumentInfo, ExtractedValue, Record, Source

__version__ = "0.3.2"


def build_commit() -> str:
    """The source commit this copy was built from: stamped into a wheel at build time; in a git checkout, read from
    git; otherwise "unknown"."""
    try:
        from ._build import COMMIT  # type: ignore[import-not-found]

        return str(COMMIT)
    except ImportError:
        pass
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return "unknown"
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short=10", "HEAD"],  # noqa: S607 - git from PATH in a source checkout
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return (done.stdout.strip() + " (source checkout)") if done.returncode == 0 else "unknown"


__all__ = [
    "NAME",
    "TAGLINE",
    "AgentResult",
    "DocumentAgent",
    "DocumentInfo",
    "ExtractedValue",
    "InklightError",
    "InputRejected",
    "Library",
    "ModelUnavailable",
    "OCRError",
    "PermissionDenied",
    "Policy",
    "Record",
    "Settings",
    "Source",
    "__version__",
    "load_settings",
]
