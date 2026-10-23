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

__version__ = "0.1.0"

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
