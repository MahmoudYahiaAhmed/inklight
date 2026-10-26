"""Validated, versioned configuration.

Precedence (lowest to highest): built-in defaults < config file < environment
variables < explicit keyword overrides. The config file is TOML and lives at
``$INKLIGHT_HOME/config.toml`` unless ``$INKLIGHT_CONFIG`` points elsewhere.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ._brand import CONFIG_ENV, HOME_ENV
from .errors import ConfigError

CONFIG_VERSION = 1


class Limits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_file_mb: float = Field(100.0, gt=0)
    max_pages: int = Field(500, ge=1, description="Pages read per document; the rest is skipped with a warning.")
    max_files_per_task: int = Field(500, ge=1)
    max_steps: int = Field(12, ge=1, le=100)
    task_timeout_s: float = Field(600.0, gt=0)
    step_timeout_s: float = Field(300.0, gt=0)
    max_retries: int = Field(1, ge=0, le=5)
    ocr_workers: int = Field(0, ge=0, description="0 = let the OCR pick from available cores.")
    context_chars: int = Field(6000, ge=500, description="Evidence budget handed to any model.")


class OCRSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: str = "inklight"
    dpi: float = Field(200.0, ge=72, le=600)
    mode: Literal["auto", "ocr", "text"] = "auto"
    threads: int = Field(4, ge=1, le=64)
    model_dir: str | None = None


class ModelSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    brain: Literal["auto", "local", "rules"] = Field(
        "auto",
        description="auto: use local small models when installed, rules otherwise. "
        "local: require them. rules: deterministic only, never load a model.",
    )
    reader: str = "Xenova/distilbert-base-cased-distilled-squad"
    embedder: str = "Xenova/bge-small-en-v1.5"
    writer: str = "HuggingFaceTB/SmolLM2-135M-Instruct"
    # Pin a model to an exact Hugging Face commit, so an upstream change cannot alter results. None: latest.
    reader_revision: str | None = None
    embedder_revision: str | None = None
    writer_revision: str | None = None
    use_writer: bool = Field(False, description="Let the 135M writer phrase answers (verified against evidence).")
    allow_download: bool = Field(False, description="Allow fetching model weights on first use.")
    model_dir: str | None = None
    # Optional stronger model behind an OpenAI-compatible API. Off unless set.
    remote_base_url: str | None = None
    remote_model: str | None = None
    remote_api_key_env: str = "INKLIGHT_REMOTE_API_KEY"
    remote_for: Literal["never", "fallback", "always"] = "never"


class ExtractionSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    day_first: bool = Field(False, description="Read 03/04/2026 as 3 April (day first), as in most of the world.")
    second_reading: bool = Field(
        True,
        description="OCR the image region of a suspicious amount again before flagging it. Off: the amount check "
        "uses the other signals only (faster, fewer confirmed flags).",
    )


class StructureSettings(BaseModel):
    """Inklight document structure (layout, reading order, tables), built on the OCR's text.

    Off by default: its runtime (PyTorch) and models (~380 MB, downloaded once) are an optional install,
    ``pip install "inklight[structure]"``. See docs/STRUCTURE.md.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: Literal["none", "inklight", "docling"] = Field(
        "none",
        description="'inklight': layout, reading order and table structure on the OCR's text "
        "('docling' is the earlier name of the same setting).",
    )
    table_mode: Literal["accurate", "fast"] = Field("accurate", description="Table structure model: accurate or fast.")
    pages: Literal["all", "tables"] = Field(
        "all", description="'tables': only pages where the OCR's layout found a table or form are structured."
    )
    threads: int = Field(0, ge=0, le=64, description="CPU threads for the layout and table models; 0 = all cores.")
    batch_size: int = Field(4, ge=1, le=64, description="Pages per layout model call.")

    @property
    def enabled(self) -> bool:
        return self.engine != "none"


class Privacy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    store_text: bool = Field(True, description="Keep extracted text in the local index.")
    log_document_text: bool = False


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = CONFIG_VERSION
    home: Path = Field(default_factory=lambda: default_home())
    output_dir: Path | None = Field(None, description="Where the agent may write files. Default: <home>/outputs.")
    limits: Limits = Limits()
    ocr: OCRSettings = OCRSettings()
    models: ModelSettings = ModelSettings()
    extraction: ExtractionSettings = ExtractionSettings()
    structure: StructureSettings = StructureSettings()
    privacy: Privacy = Privacy()

    @property
    def db_path(self) -> Path:
        return self.home / "library.db"

    @property
    def outputs(self) -> Path:
        return self.output_dir or (self.home / "outputs")

    @property
    def uploads(self) -> Path:
        return self.home / "uploads"

    @property
    def model_cache(self) -> Path | None:
        return Path(self.models.model_dir) if self.models.model_dir else None

    def with_overrides(self, **changes: Any) -> Settings:
        """Return a copy with nested changes, e.g. ``limits={"max_steps": 4}``."""
        data = self.model_dump()
        _deep_merge(data, changes)
        return _validate(data)


def default_home() -> Path:
    env = os.environ.get(HOME_ENV)
    return Path(env).expanduser() if env else Path.home() / ".inklight"


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _validate(data: dict[str, Any]) -> Settings:
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration:\n{exc}") from exc


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    version = int(data.get("version", CONFIG_VERSION))
    if version > CONFIG_VERSION:
        raise ConfigError(
            f"Config version {version} is newer than this release supports ({CONFIG_VERSION}). "
            "Upgrade Inklight or remove the version key."
        )
    # Version 1 is the first schema; future migrations go here, oldest first.
    return {**data, "version": CONFIG_VERSION}


def _env_overrides() -> dict[str, Any]:
    """INKLIGHT_<SECTION>__<KEY>=value, e.g. INKLIGHT_LIMITS__MAX_STEPS=6."""
    out: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith("INKLIGHT_") or "__" not in key:
            continue
        section, _, field = key[len("INKLIGHT_") :].lower().partition("__")
        out.setdefault(section, {})[field] = value
    return out


def load_settings(path: str | Path | None = None, **overrides: Any) -> Settings:
    """Load settings from file + environment + overrides, validating everything."""
    data: dict[str, Any] = {}
    explicit = path or os.environ.get(CONFIG_ENV)
    file = Path(explicit) if explicit else default_home() / "config.toml"
    if file.is_file():
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Cannot read config {file}: {exc}") from exc
    elif explicit:
        raise ConfigError(f"Config file not found: {file}")
    data = _migrate(data)
    _deep_merge(data, _env_overrides())
    _deep_merge(data, overrides)
    return _validate(data)
