"""The Brain: which models are available, loaded lazily and shared.

Modes:
* ``rules``  — deterministic only; never loads a model.
* ``auto``   — use each local small model that is installed; otherwise rules.
* ``local``  — require the reader and embedder; fail clearly if missing.
A remote model is layered on top only when explicitly configured.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from ..config import Settings
from ..errors import ModelUnavailable
from . import hub
from .onnx_models import Embedder, Reader, Span, Writer
from .remote import RemoteModel

log = logging.getLogger(__name__)

PARAMS = {"reader": "66M", "embedder": "33M", "writer": "135M"}


class Brain:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mode = settings.models.brain
        self._cache: dict[str, Any] = {}
        self._failed: dict[str, str] = {}
        self._lock = threading.Lock()

    def _repo(self, role: str) -> str:
        return str(getattr(self.settings.models, role))

    def _load(self, role: str) -> Any:
        if self.mode == "rules":
            return None
        with self._lock:
            if role in self._cache:
                return self._cache[role]
            if role in self._failed and self.mode == "auto":
                return None
            cls = {"reader": Reader, "embedder": Embedder, "writer": Writer}[role]
            try:
                files = hub.resolve(
                    self._repo(role), hub.FILES[role], self.settings.model_cache, self.settings.models.allow_download
                )
                model = cls(files, self._repo(role), threads=self.settings.ocr.threads)
            except ModelUnavailable as exc:
                self._failed[role] = str(exc)
                if self.mode == "local" and role != "writer":
                    raise
                log.info("%s unavailable, using rules: %s", role, exc)
                return None
            self._cache[role] = model
            return model

    @property
    def reader(self) -> Reader | None:
        return self._load("reader")

    @property
    def embedder(self) -> Embedder | None:
        return self._load("embedder")

    @property
    def writer(self) -> Writer | None:
        return self._load("writer") if self.settings.models.use_writer else None

    @property
    def remote(self) -> RemoteModel | None:
        if self.settings.models.remote_for == "never":
            return None
        if "remote" not in self._cache:
            try:
                self._cache["remote"] = RemoteModel(self.settings.models)
            except ModelUnavailable as exc:
                self._failed["remote"] = str(exc)
                self._cache["remote"] = None
        return self._cache["remote"]  # type: ignore[no-any-return]

    def label(self) -> str:
        if self.mode == "rules":
            return "rules"
        parts = [f"{role}:{PARAMS[role]}" for role in ("reader", "embedder", "writer") if self._cache.get(role)]
        if self._cache.get("remote"):
            parts.append(self._cache["remote"].name)
        return "+".join(parts) if parts else "rules"

    def status(self) -> dict[str, dict[str, Any]]:
        cache = self.settings.model_cache
        out = {}
        for role in ("reader", "embedder", "writer"):
            repo = self._repo(role)
            out[role] = {
                "repo": repo,
                "params": PARAMS[role],
                "installed": hub.installed(repo, hub.FILES[role], cache),
                "loaded": role in self._cache and self._cache[role] is not None,
                "error": self._failed.get(role),
            }
        out["remote"] = {
            "configured": bool(self.settings.models.remote_base_url and self.settings.models.remote_model),
            "used_for": self.settings.models.remote_for,
        }
        return out


__all__ = ["Brain", "Embedder", "Reader", "Span", "Writer", "RemoteModel", "hub"]
