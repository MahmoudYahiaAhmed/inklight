"""Running Docling's standard PDF / image pipeline on a document Indra has already read.

Docling's own components do the structural work, unchanged:

- layout analysis (the Heron layout model by default) finds text, headings, lists, tables, pictures and captions;
- reading-order assembly orders them and nests them into a ``DoclingDocument``;
- TableFormer recovers each table's rows, columns, spans and header cells, matched to the text cells it is given;

and the text cells are Indra's stored lines (``indra_ocr``), so no second OCR runs.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ..config import StructureSettings
from ..errors import ModelUnavailable
from ..schemas import DocumentContent, PageContent

log = logging.getLogger(__name__)

_CONVERTERS: dict[tuple[Any, ...], Any] = {}
_RASTER_DPI = 144  # pages handed to Docling's layout model (it renders at 2x of 72 dpi too)
_LOCK = threading.Lock()  # one conversion at a time: a DocumentConverter is not thread-safe
_BUILD_LOCK = threading.Lock()
_TABLE_LABELS = {"Table", "Form", "Table-Of-Contents"}  # Indra's layout labels worth Docling's table model


@dataclass(frozen=True)
class DoclingRun:
    document: Any  # docling_core DoclingDocument
    seconds: float
    load_seconds: float  # building the converter and loading its models (0 when reused)
    cells_delivered: int  # Indra lines handed to Docling as its OCR cells
    components: dict[str, str]
    pages: list[int] = field(default_factory=list)  # the pages Docling was run on
    upright: list[int] = field(default_factory=list)  # pages Indra read turned, given to Docling turned upright


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
        "layout": f"Heron ({settings.layout_runtime})",
        "tables": (
            "TableFormer V2" if settings.table_model == "tableformer_v2" else f"TableFormer ({settings.table_mode})"
        )
        + ", cell matching on the given text cells",
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
    pdf = _is_pdf(path)
    chosen = chosen_pages(list(content.pages), settings) if pdf else list(content.pages)
    if not chosen:  # no page with a table or form: nothing for Docling to add, and no model to load
        from docling_core.types.doc import DoclingDocument

        empty = DoclingDocument(name=path.stem)
        return DoclingRun(empty, time.perf_counter() - started, 0.0, 0, components(settings), [])
    converter, load_seconds = _converter(settings)
    # A page Indra read turned (rotation 90/180/270) has its lines in the upright frame: Docling is given that page
    # turned upright too, so its boxes are in the same frame (frames.py). Docling numbers the pages it is given from
    # 1; they are mapped back to the document's own numbers.
    turns = {p.number: p.rotation % 360 for p in chosen if p.rotation % 360}
    given = [p.model_copy(update={"number": i + 1, "rotation": 0}) for i, p in enumerate(chosen)]
    with tempfile.TemporaryDirectory(prefix="inklight-structure-") as work:
        numbers = [p.number for p in chosen]
        if pdf:
            source = _images_only(path, numbers, Path(work), password, turns)
        elif turns:
            source = _frames_upright(path, numbers, Path(work), turns)
        else:
            source = path
        with _LOCK, indra_ocr.lines_for(source, given) as delivered:
            result = converter.convert(source, max_num_pages=max(len(given), 1), raises_on_error=True)
    document = _renumbered(result.document, {i + 1: p.number for i, p in enumerate(chosen)})
    return DoclingRun(
        document=document,
        seconds=time.perf_counter() - started,
        load_seconds=load_seconds,
        cells_delivered=delivered.get("cells", 0),
        components=components(settings),
        pages=[p.number for p in chosen],
        upright=sorted(turns),
    )


def chosen_pages(pages: list[PageContent], settings: StructureSettings) -> list[PageContent]:
    """The pages Docling is run on: all of them, or (pages = "tables") those where Indra's layout found a table or
    a form. The others keep Indra's layout, as with structure off."""
    if settings.pages == "all":
        return pages
    return [p for p in pages if {b.label for b in p.blocks} & _TABLE_LABELS]


def _renumbered(document: Any, numbers: dict[int, int]) -> Any:
    """The document with its page numbers changed from Docling's (1..n of the pages given) to the document's."""
    if all(k == v for k, v in numbers.items()):
        return document
    for item, _ in document.iterate_items(traverse_pictures=True, with_groups=True):
        for prov in getattr(item, "prov", []) or []:
            prov.page_no = numbers.get(prov.page_no, prov.page_no)
    pages = {}
    for number, page in document.pages.items():
        page.page_no = numbers.get(number, number)
        pages[page.page_no] = page
    document.pages = pages
    return document


def _is_pdf(path: Path) -> bool:
    with path.open("rb") as fh:
        return fh.read(5) == b"%PDF-"


def preload(settings: StructureSettings) -> None:
    """Build the converter (loading the layout and table models) on a background thread, so the load overlaps
    Indra's OCR of the first document. Idempotent; ``run`` waits for it through the build lock."""
    if not available():
        return

    def build() -> None:
        try:
            _converter(settings)
        except Exception as exc:  # noqa: BLE001 - reported by the first document that needs the structure
            log.warning("Docling preload failed: %s", exc)

    threading.Thread(target=build, name="inklight-docling-preload", daemon=True).start()


def threads(settings: StructureSettings) -> int:
    """CPU threads for Docling's models: the setting, or every core when it is 0."""
    return settings.threads or os.cpu_count() or 4


def _images_only(
    path: Path, numbers: list[int], work: Path, password: str | None, turns: dict[int, int] | None = None
) -> Path:
    """The PDF's pages ``numbers`` (1-based) rendered one by one into a PDF of images, at the original page size;
    a page in ``turns`` (Indra's rotation) is turned upright."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path), password=password)
    out = work / f"{path.stem}.pdf"
    turns = turns or {}
    try:
        wanted = [n for n in numbers if 1 <= n <= len(pdf)]
        if not wanted:
            raise ValueError("the PDF has none of the pages asked for")
        render = (
            _upright(pdf[n - 1].render(scale=_RASTER_DPI / 72).to_pil().convert("RGB"), turns.get(n, 0)) for n in wanted
        )
        first = next(render)
        first.save(out, save_all=True, append_images=render, resolution=_RASTER_DPI)  # one page in memory at a time
    finally:
        pdf.close()
    return out


def _frames_upright(path: Path, numbers: list[int], work: Path, turns: dict[int, int]) -> Path:
    """An image file's frames ``numbers`` as Indra read them, each turned upright, in a PDF of images."""
    from indra_ocr.document import read_images
    from PIL import Image

    frames = read_images(path)
    wanted = [n for n in numbers if 1 <= n <= len(frames)]
    if not wanted:
        raise ValueError("the image has none of the pages asked for")
    out = work / f"{path.stem}-upright.pdf"
    images = (_upright(Image.fromarray(frames[n - 1]).convert("RGB"), turns.get(n, 0)) for n in wanted)
    first = next(images)
    first.save(out, save_all=True, append_images=images, resolution=_RASTER_DPI)
    return out


def _upright(image: Any, turn: int) -> Any:
    """The page image turned upright: Indra's rotation is how far it is turned counter-clockwise (frames.py)."""
    return image.rotate(-turn, expand=True, fillcolor="white") if turn else image


def _converter(settings: StructureSettings) -> tuple[Any, float]:
    key = (
        settings.table_model,
        settings.table_mode,
        settings.layout_runtime,
        settings.artifacts_path,
        threads(settings),
        settings.batch_size,
    )
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
        from docling.datamodel.object_detection_engine_options import OnnxRuntimeObjectDetectionEngineOptions
        from docling.datamodel.pipeline_options import (
            LayoutObjectDetectionOptions,
            PdfPipelineOptions,
            TableFormerMode,
            TableStructureOptions,
            TableStructureV2Options,
        )
        from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

        from . import indra_ocr

        indra_ocr.register()
        options = PdfPipelineOptions(
            do_ocr=True,
            ocr_options=indra_ocr.IndraLinesOcrOptions(),
            do_table_structure=True,
            allow_external_plugins=False,
            accelerator_options=AcceleratorOptions(num_threads=threads(settings), device=AcceleratorDevice.CPU),
            layout_batch_size=settings.batch_size,
            table_batch_size=settings.batch_size,
            ocr_batch_size=settings.batch_size,
        )
        if settings.table_model == "tableformer_v2":
            options.table_structure_options = TableStructureV2Options(do_cell_matching=True)
        else:
            mode = TableFormerMode.ACCURATE if settings.table_mode == "accurate" else TableFormerMode.FAST
            # cells matched to the text cells given: Indra's lines
            options.table_structure_options = TableStructureOptions(mode=mode, do_cell_matching=True)
        if settings.layout_runtime == "onnx":  # the same Heron model, exported to ONNX by Docling
            options.layout_options = LayoutObjectDetectionOptions.from_preset(
                "layout_heron_default", engine_options=OnnxRuntimeObjectDetectionEngineOptions()
            )
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
