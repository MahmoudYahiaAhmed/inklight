"""OCR engine registry. Add an engine by registering a factory under a name."""

from __future__ import annotations

from collections.abc import Callable

from ..config import OCRSettings
from ..errors import ConfigError
from .base import OCREngine
from .indra import IndraEngine
from .plaintext import PlainTextEngine

_FACTORIES: dict[str, Callable[[OCRSettings], OCREngine]] = {
    "indra": IndraEngine,
}


def register_engine(name: str, factory: Callable[[OCRSettings], OCREngine]) -> None:
    _FACTORIES[name] = factory


def create_engine(settings: OCRSettings) -> OCREngine:
    try:
        return _FACTORIES[settings.engine](settings)
    except KeyError as exc:
        raise ConfigError(f"Unknown OCR engine {settings.engine!r}; known: {sorted(_FACTORIES)}") from exc


__all__ = ["OCREngine", "IndraEngine", "PlainTextEngine", "create_engine", "register_engine"]
