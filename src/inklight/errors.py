"""Exception hierarchy. Every error a user can hit derives from InklightError."""

from __future__ import annotations


class InklightError(Exception):
    """Base class for all Inklight errors."""


class ConfigError(InklightError):
    """Invalid configuration file or value."""


class InputRejected(InklightError):
    """A file failed validation (type, size, page count, path)."""


class OCRError(InklightError):
    """The OCR backend could not read a document."""


class ModelUnavailable(InklightError):
    """A requested model is not installed or cannot be loaded."""


class PermissionDenied(InklightError):
    """A tool needs a permission the current policy does not grant."""


class UnsafePath(PermissionDenied):
    """A path escapes its allowed root or targets a forbidden location."""


class ToolError(InklightError):
    """A tool failed. `recoverable` tells the runner whether a retry may help."""

    def __init__(self, message: str, *, recoverable: bool = False) -> None:
        super().__init__(message)
        self.recoverable = recoverable


class TaskCancelled(InklightError):
    """The task was cancelled or ran out of its time budget."""


class LimitExceeded(InklightError):
    """A configured execution limit (steps, time, pages, size) was hit."""


class PlanError(InklightError):
    """A plan whose steps would not enforce what it claims; refused before anything runs."""


class StoreClosed(InklightError):
    """The library database was closed (``close()`` or leaving a ``with`` block)."""
