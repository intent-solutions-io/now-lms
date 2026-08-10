# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Practice gathers a domain's questions from across a course, without repeats.

A domain's items are scattered on purpose: some sit in that domain's own section
quiz, the rest inside a full-length exam that spans every domain at once. Gathering
them is the point of the feature — and the reason it has to de-duplicate, because a
course's mock exam re-imports the same bank its section quizzes already cover.
"""

from pathlib import Path

import pytest

from now_lms import lms_app
from now_lms.db import Question, database
from now_lms.themes import get_practice_template
from now_lms.vistas.evaluations import _course_questions_by_domain

from tests import test_cca_seed as _seed_tests

MODELS = _seed_tests.MODELS
cca_db = _seed_tests.cca_db

PLATFORM_TEMPLATE = "evaluations/practice.html"


@pytest.fixture
def app_context():
    with lms_app.app_context():
        yield


def _override_path(theme: str) -> Path:
    from now_lms.config import DIRECTORIO_PLANTILLAS

    return Path(DIRECTORIO_PLANTILLAS) / "themes" / theme / "overrides" / "practice.j2"


def test_the_platform_ships_a_default_and_intent_overrides_it(app_context, monkeypatch):
    monkeypatch.setattr("now_lms.themes.get_current_theme", lambda: "now_lms")
    assert get_practice_template() == PLATFORM_TEMPLATE

    monkeypatch.setattr("now_lms.themes.get_current_theme", lambda: "intent_learn")
    assert _override_path("intent_learn").exists()
    assert get_practice_template() == "themes/intent_learn/overrides/practice.j2"


def _question(text, domain_key, domain_name="A domain"):
    return {
        "text": text,
        "options": ["alpha", "beta", "gamma", "delta"],
        "answerIndex": 0,
        "rationale": "alpha is correct.",
        "source": "Synthetic fixture",
        "domainKey": domain_key,
        "domainName": domain_name,
    }


def _spec(code, section_questions, mock_questions):
    return {
        "codigo": code,
        "nombre": "Practice test course",
        "nivel": 1,
        "duracion": 1,
        "descripcion_corta": "short",
        "descripcion": "long",
        "sections": [
            {"nombre": "Section", "descripcion": "d", "lesson": "# Lesson\n\nbody", "questions": section_questions}
        ],
        "mock_questions": mock_questions,
    }


def test_a_domain_gathers_items_from_every_evaluation_in_the_course(cca_db):
    """Section quiz and mock exam both contribute; the union is what a drill needs."""
    section = [_question("Section-only item.", "d-alpha")]
    mock = [_question("Mock-only item.", "d-alpha"), _question("Another domain.", "d-beta")]
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P1", section, mock))

    domains, by_key = _course_questions_by_domain("CCA-P1", "nobody")
    texts = {question.text for question in by_key["d-alpha"]}
    assert texts == {"Section-only item.", "Mock-only item."}, "a drill must see both sources"
    assert {row["key"] for row in domains} == {"d-alpha", "d-beta"}


def test_the_same_item_seeded_twice_appears_once(cca_db):
    """The defect this de-duplication exists for.

    A course's mock exam re-imports the whole bank its section quizzes already cover,
    so the identical question exists as two rows. Measured on the real curriculum,
    CCA-A held 132 labelled rows for 96 distinct questions. Without this, a drill
    repeats items inside one sitting and counts the same question twice in its own
    denominator.
    """
    repeated = _question("This item is in both the quiz and the mock.", "d-alpha")
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P2", [repeated], [repeated]))

    rows = [
        question
        for question in database.session.execute(database.select(Question)).scalars()
        if question.text == "This item is in both the quiz and the mock."
    ]
    assert len(rows) == 2, "the fixture must actually produce the duplicate this guards against"

    _domains, by_key = _course_questions_by_domain("CCA-P2", "nobody")
    gathered = by_key["d-alpha"]
    assert len(gathered) == 1, "the drill must not show the same question twice"
    assert gathered[0].text == "This item is in both the quiz and the mock."


def test_the_domain_total_counts_distinct_questions(cca_db):
    """The count on a domain card has to agree with what the drill will show."""
    repeated = _question("Repeated item.", "d-alpha")
    unique = _question("Unique item.", "d-alpha")
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P3", [repeated, unique], [repeated]))

    domains, by_key = _course_questions_by_domain("CCA-P3", "nobody")
    row = next(entry for entry in domains if entry["key"] == "d-alpha")
    assert row["total"] == 2
    assert row["total"] == len(by_key["d-alpha"]), "the card's count and the drill's length must match"


def test_a_course_with_no_labelled_questions_returns_nothing(cca_db):
    """An unlabelled course must render an empty chooser, not raise."""
    domains, by_key = _course_questions_by_domain("CCA-DOES-NOT-EXIST", "nobody")
    assert domains == []
    assert by_key == {}
