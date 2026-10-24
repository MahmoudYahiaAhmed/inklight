"""Rule-based answering reads Arabic words, sentences and question types (it used to keep only [a-z0-9])."""

import pytest

from inklight import DocumentAgent
from inklight.agent.answer import _stem, expected_kind, sentences, words

from .conftest import make_settings


def test_arabic_words_are_kept_and_normalised():
    assert words("ما هو الإجمالي؟") == ["الاجمالي"]
    assert "المستحق" in words("المبلغ المُستحق")  # harakat removed, as in the search index
    assert words("Total due 500") == ["total", "due", "500"]


def test_arabic_light_stem_matches_prefixed_forms():
    assert _stem("والعقد") == _stem("العقد") == _stem("عقد")
    assert _stem("بالقاهره") == _stem("القاهره")


def test_arabic_sentences_are_split():
    text = "تبدأ مدة العقد في الأول من شباط. وتنتهي في نهاية كانون الثاني. هل يجدد العقد؟ نعم يجدد."
    assert len(sentences(text)) == 4


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("متى اعتمد القرار؟", "date"),
        ("ما تاريخ الرسالة؟", "date"),
        ("كم الأجرة الشهرية؟", "money"),
        ("ما المبلغ الإجمالي؟", "money"),
        ("كم عدد الساعات؟", "number"),
        ("من وقّع الرسالة؟", "name"),
    ],
)
def test_arabic_question_kinds(question, kind):
    assert expected_kind(question) == kind


LEASE = (
    "عقد إيجار شقة سكنية.\n"
    "الطرف الأول (المؤجر): السيد كريم فؤاد الشامي.\n"
    "الطرف الثاني (المستأجر): السيدة نور الهدى عادل سليم.\n"
    "مدة هذا العقد سنتان تبدأ من ١ شباط/فبراير ٢٠٢٤.\n"
    "الأجرة الشهرية ثمانية آلاف جنيه مصري (8,000 ج.م) تدفع مقدماً في أول كل شهر.\n"
    "تختص محاكم الجيزة بنظر أي نزاع ينشأ عن هذا العقد."
)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("من المؤجر؟", "كريم فؤاد الشامي"),
        ("ما المحكمة المختصة بالنزاع؟", "محاكم الجيزة"),
        ("كم الأجرة الشهرية؟", "8,000"),
    ],
)
def test_rule_answers_arabic_questions_from_the_right_sentence(tmp_path, question, expected):
    path = tmp_path / "lease.txt"
    path.write_text(LEASE, encoding="utf-8")
    with DocumentAgent(make_settings(tmp_path / "home")) as agent:
        res = agent.ask(question, files=[path])
    assert expected in res.answer
    assert expected in res.sources[0].excerpt  # the cited passage holds the answer, in its original form


def test_arabic_sentence_answers_always_ask_for_a_check(tmp_path):
    path = tmp_path / "lease.txt"
    path.write_text(LEASE, encoding="utf-8")
    with DocumentAgent(make_settings(tmp_path / "home")) as agent:
        res = agent.ask("من المؤجر؟", files=[path])
    assert res.confidence < 0.3
    assert any("Low confidence" in w for w in res.warnings)
