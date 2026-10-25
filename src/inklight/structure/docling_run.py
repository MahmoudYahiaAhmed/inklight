"""Running Docling's standard PDF / image pipeline on a document Indra has already read.

Docling's own components do the structural work, unchanged:

- layout analysis (the Heron layout model by default) finds text, headings, lists, tables, pictures and captions;
- reading-order assembly orders them and nests them into a ``DoclingDocument``;
- TableFormer recovers each table's rows, columns, spans and header cells, matched to the text cells it is given;

and the text cells are Indra's stored lines (``indra_ocr``), so no second OCR runs.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ..config import StructureSettings
from ..errors import ModelUnavailable
from ..schemas import DocumentContent

log = logging.getLogger(__name__)

_CONVERTERS: dict[tuple[Any, ...], Any] = {}
_RASTER_DPI = 144  # pages handed to Docling's layout model (it renders at 2x of 72 dpi too)
_LOCK = threading.Lock()  # one conversion at a time: a DocumentConverter is not thread-safe
_BUILD_LOCK = threading.Lock()


@dataclass(frozen=True)
class DoclingRun:
    document: Any  # docling_core DoclingDocument
    seconds: float
    load_seconds: float  # building the converter and loading its models (0 when reused)
    cells_delivered: int  # Indra lines handed to Docling as its OCR cells
    components: dict[str, str]


def available() -> bool:
    try:
        import docling  # noqa: F401
        import docling_core  # noqa: F401
    except ImportError:
        return False
    return True


def components(settings: StructureSettings) -> dict[str, str]:
    """What runs, for the record kept with each structured document."""
    return {
        "docling": _version("docling"),
        "docling_core": _version("docling-core"),
        "layout": "docling default layout model (Heron)",
        "tables": f"TableFormer ({settings.table_mode}), cell matching on the given text cells",
        "ocr": "none in Docling: Indra's stored lines are its text cells (OcrMode.FULL_PAGE)",
        "indra_ocr": _version("indra-ocr"),
    }


def run(path: Path, content: DocumentContent, settings: StructureSettings, password: str | None = None) -> DoclingRun:
    """Convert ``path`` with Docling, its text being ``content``'s OCR lines. Raises ModelUnavailable when Docling
    is not installed or its models cannot be loaded.

    A PDF is handed to Docling as images of its pages: with no text layer to read, Docling's tables and items are
    built from Indra's lines only (TableFormer would otherwise match its cells to the PDF's own text)."""
    if not available():
        raise ModelUnavailable('Docling is not installed: pip install "inklight[structure]"')
    from . import indra_ocr

    started = time.perf_counter()
    converter, load_seconds = _converter(settings)
    with tempfile.TemporaryDirectory(prefix="inklight-structure-") as work:
        source = _images_only(path, len(content.pages), Path(work), password)
        with _LOCK, indra_ocr.lines_for(source, list(content.pages)) as delivered:
            result = converter.convert(source, max_num_pages=max(len(content.pages), 1), raises_on_error=True)
    return DoclingRun(
        document=result.document,
        seconds=time.perf_counter() - started,
        load_seconds=load_seconds,
        cells_delivered=delivered.get("cells", 0),
        components=components(settings),
    )


def _images_only(path: Path, pages: int, work: Path, password: str | None) -> Path:
    """A PDF rendered page by page into a PDF of images, at the original page size; other inputs as they are."""
    with path.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            return path
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path), password=password)
    out = work / f"{path.stem}.pdf"
    try:
        count = min(len(pdf), pages)
        if count == 0:
            raise ValueError("the PDF has no pages")
        render = (pdf[i].render(scale=_RASTER_DPI / 72).to_pil().convert("RGB") for i in range(count))
        first = next(render)
        first.save(out, save_all=True, append_images=render, resolution=_RASTER_DPI)  # one page in memory at a time
    finally:
        pdf.close()
    return out


def _converter(settings: StructureSettings) -> tuple[Any, float]:
    key = (settings.table_mode, settings.artifacts_path, settings.threads)
    with _BUILD_LOCK:  # two threads must not each load the models
        with _LOCK:
            if key in _CONVERTERS:
                return _CONVERTERS[key], 0.0
        return _build(settings, key)


def _build(settings: StructureSettings, key: tuple[Any, ...]) -> tuple[Any, float]:
    started = time.perf_counter()
    try:
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode, TableStructureOptions
        from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

        from . import indra_ocr

        indra_ocr.register()
        options = PdfPipelineOptions(
            do_ocr=True,
            ocr_options=indra_ocr.IndraLinesOcrOptions(),
            do_table_structure=True,
            allow_external_plugins=False,
            accelerator_options=AcceleratorOptions(num_threads=settings.threads, device=AcceleratorDevice.CPU),
        )
        tables = options.table_structure_options
        if isinstance(tables, TableStructureOptions):  # TableFormer, the default table engine
            tables.mode = TableFormerMode.ACCURATE if settings.table_mode == "accurate" else TableFormerMode.FAST
            tables.do_cell_matching = True  # cells matched to the text cells given: Indra's lines
        if settings.artifacts_path:
            options.artifacts_path = settings.artifacts_path
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
            }
        )
        converter.initialize_pipeline(InputFormat.PDF)
    except Exception as exc:
        raise ModelUnavailable(f"Could not set up Docling: {type(exc).__name__}: {exc}") from exc
    with _LOCK:
        _CONVERTERS[key] = converter
    return converter, time.perf_counter() - started


def _version(dist: str) -> str:
    try:
        return version(dist)
    except PackageNotFoundError:
        return "not installed"
