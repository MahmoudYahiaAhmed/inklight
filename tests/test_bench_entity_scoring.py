"""Evaluation scoring: exact transcription and entity identity are scored separately.

An Arabic answer "المندوب الدائم لتركيا" names Turkey even though the accepted word "تركيا" carries an attached
preposition; an OCR misreading ("ريغيير" for "ريفيير") is a different word and stays wrong under both scores.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))

from capability_diag import contains, contains_entity  # noqa: E402


def test_attached_particles_identify_the_same_entity():
    assert not contains("المثل الدائم لتركيا لدى الأمم المتحدة", ["تركيا"])  # exact transcription: no
    assert contains_entity("المثل الدائم لتركيا لدى الأمم المتحدة", ["تركيا"])  # same entity: yes
    assert contains_entity("وبالأمين العام", ["الأمين العام"])
    assert contains_entity("إلى الأمين العام", ["الأمين العام"])


def test_ocr_errors_are_not_forgiven_by_the_entity_score():
    assert not contains_entity("نيكولا دي ريغيير", ["دي ريفيير"])
    assert not contains_entity("المثل الدائم لتركيا", ["مصر"])


def test_english_scoring_is_unchanged():
    for answer, accept, expected in [
        ("the Permanent Mission of Ukraine", ["Ukraine"], True),
        ("Ukrainian", ["Ukraine"], False),
        ("Total 70.00", ["70.00"], True),
    ]:
        assert contains(answer, accept) is expected
        assert contains_entity(answer, accept) is expected


def test_a_particle_is_not_stripped_from_a_short_word():
    """ "لبنان" is Lebanon, not ل + "بنان": nothing shorter than three letters is left after a particle."""
    assert contains_entity("الممثل الدائم للبنان", ["لبنان"])
    assert not contains_entity("بنا", ["نا"])
