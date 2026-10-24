"""A PDF text layer whose Arabic is broken is not trusted: the page is OCR'd instead."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from inklight.config import OCRSettings
from inklight.ocr.indra import IndraEngine
from inklight.ocr.textcheck import broken_arabic_share, layer_is_broken

# UN S/2023/50 (Arabic), page 2, as its text layer decodes: lam-alef split ("األمني"), alef runs ("اااااا").
BROKEN = (
    "و اااااااا األمني في كيفو ام م ميؤ بح ــو الجدرر النمني الذو رألــعس ســاء هإرات األ عاح العامم لدرر وماعم وــيا "
    "أ ياديا ر اود الطوة اإل ليميم لجماعم وـيا أ ياديا ي حوـو ويا يليم التحطق المو ـ ـم ي اا ال ـم ي 15 عا وح "
    "األرر/اي ــــــــــم ي ،2022 عاح يتعإن على ك هابإي حيعم 23 ما س، عمم بال ياح ال ــــــــــاا عن م تمي مم"
)
# Arabic Wikipedia "مصر", page 4: a sound text layer.
CLEAN = (
    "وادي النيل والدلتا الصحراء الغربية الصحراء الشرقية شبه جزيرة سيناء ُتعد الحدود السياسية الحالية لمصر حديثة "
    "للغاية، فأقدم اتفاقية للحدود ترجع إلى عام 1899م. أما قبل فكانت تخوًما، وبحكم طبيعة موقع مصر الجغرافي الرابط "
    "بين قارتي آسيا وإفريقيا؛ فكانت تخوم مصر والحدود البرية المصرية فلكية هندسية، وتتجاور مصر مع الأمم الأخرى"
)


def test_broken_arabic_layer_is_detected():
    assert broken_arabic_share(BROKEN) > 0.05
    assert layer_is_broken(BROKEN)


def test_sound_arabic_layer_is_trusted():
    assert broken_arabic_share(CLEAN) == 0.0
    assert not layer_is_broken(CLEAN)


@pytest.mark.parametrize(
    "text",
    [
        "Letter dated 18 January 2023 from the Chargé d'affaires a.i. of the Permanent Mission " * 3,
        "األمم ااا",  # too few Arabic words to judge
        "",
    ],
)
def test_not_judged_broken(text):
    assert not layer_is_broken(text)


# ---------------------------------------------------------------- the engine re-reads a broken page


def _indra_page(text: str, source: str) -> SimpleNamespace:
    line = SimpleNamespace(text=text, box=[10, 10, 500, 30], conf=1.0 if source == "text" else 0.9)
    return SimpleNamespace(
        lines=[line], blocks=[], markdown=text, source=source, rotation=0, note="", timings={"total_ms": 1.0}
    )


class FakeConverter:
    """Indra's converter with canned pages: page 1 has a broken Arabic layer, page 2 a sound one."""

    def __init__(self) -> None:
        self.ocr_calls = 0

    def convert(self, path, max_pages, password=None):  # noqa: ANN001, ARG002
        yield 0, _indra_page(BROKEN, "text")
        yield 1, _indra_page(CLEAN, "text")

    def ocr(self, gray):  # noqa: ANN001
        self.ocr_calls += 1
        assert gray.ndim == 2 and gray.size > 0
        return _indra_page("الأمم المتحدة مجلس الأمن رسالة مؤرخة 18 كانون الثاني/يناير 2023", "ocr")


def _two_page_pdf(path: Path) -> Path:
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    for _ in range(2):
        doc.new_page(width=300, height=200).insert_text((20, 40), "page")
    doc.save(str(path))
    doc.close()
    return path


def test_engine_ocrs_a_page_whose_layer_is_broken(tmp_path):
    engine = IndraEngine(OCRSettings())
    fake = FakeConverter()
    engine._converter = fake
    content = engine.read(_two_page_pdf(tmp_path / "ar.pdf"), max_pages=10)
    first, second = content.pages
    assert fake.ocr_calls == 1
    assert first.source == "ocr" and "broken Arabic text layer" in first.note
    assert first.lines[0].text.startswith("الأمم")
    assert second.source == "text" and second.lines[0].text == CLEAN
    assert any("broken Arabic text layer" in w for w in content.warnings)


def test_engine_keeps_text_layer_in_text_mode(tmp_path):
    engine = IndraEngine(OCRSettings(mode="text"))
    fake = FakeConverter()
    engine._converter = fake
    content = engine.read(_two_page_pdf(tmp_path / "ar.pdf"), max_pages=10)
    assert fake.ocr_calls == 0  # mode "text" means: use the layer even when the checks fail
    assert content.pages[0].source == "text"


class FailingConverter(FakeConverter):
    def ocr(self, gray):  # noqa: ANN001
        self.ocr_calls += 1
        raise RuntimeError("onnx out of memory")


class EmptyConverter(FakeConverter):
    def ocr(self, gray):  # noqa: ANN001
        self.ocr_calls += 1
        return _indra_page("", "ocr")


@pytest.mark.parametrize("converter", [FailingConverter, EmptyConverter])
def test_a_failed_reread_keeps_the_layer_and_the_document(tmp_path, converter):
    engine = IndraEngine(OCRSettings())
    fake = converter()
    engine._converter = fake
    content = engine.read(_two_page_pdf(tmp_path / "ar.pdf"), max_pages=10)
    first = content.pages[0]
    assert fake.ocr_calls == 1
    assert first.source == "text" and first.lines[0].text == BROKEN  # kept, not emptied or lost
    assert "OCR failed" in first.note
    assert any("kept the text layer" in w for w in content.warnings)
