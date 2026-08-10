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
from now_lms.db import Question, Usuario, database
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


def _member(usuario="drill-member"):
    """A real enrolled member: the gathering now delegates access to
    `can_user_access_evaluation`, which needs a user, not a username."""
    existing = database.session.execute(database.select(Usuario).filter_by(usuario=usuario)).scalars().first()
    if existing is not None:
        return existing
    user = Usuario(
        usuario=usuario,
        acceso=b"x",
        nombre="Drill",
        apellido="Member",
        correo_electronico=f"{usuario}@example.invalid",
        tipo="student",
        activo=True,
    )
    database.session.add(user)
    database.session.commit()
    return user


def _enroll(user, code):
    from now_lms.db import EstudianteCurso

    database.session.add(EstudianteCurso(usuario=user.usuario, curso=code, vigente=True))
    database.session.commit()


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


def test_a_scored_exams_questions_never_reach_the_drill(cca_db):
    """The answer key must not be readable before the exam is sat.

    This surface reveals the correct option and the rationale on click. An earlier cut
    gathered from every evaluation in the course, so a member could open the drill,
    read the mock exam's answers, and then sit it. Practice quizzes are different:
    they have unlimited attempts and show their own answers after a submission, so
    drawing from those discloses nothing the member could not already get.
    """
    section = [_question("Section-quiz item.", "d-alpha")]
    mock = [_question("Exam-only item.", "d-alpha"), _question("Exam-only other domain.", "d-beta")]
    member = _member()
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P1", section, mock))
    _enroll(member, "CCA-P1")

    domains, by_key = _course_questions_by_domain("CCA-P1", member)
    texts = {question.text for question in by_key.get("d-alpha", [])}
    assert texts == {"Section-quiz item."}, "only the practice-quiz item may be drilled"
    assert "Exam-only item." not in texts
    assert "d-beta" not in by_key, "a domain that exists only inside the exam must not appear"
    assert {row["key"] for row in domains} == {"d-alpha"}


def test_an_unpaid_enrollment_reaches_nothing(cca_db):
    """Existence of an EstudianteCurso row is a weaker gate than the platform's.

    `can_user_access_evaluation` also checks that a paid course has actually been paid
    for. Delegating to it is what stops an unpaid enrollment reading paid questions,
    their correct answers and their explanations.
    """
    from now_lms.db import Curso

    section = [_question("Paid item.", "d-alpha")]
    member = _member("unpaid-member")
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P4", section, None))
    _enroll(member, "CCA-P4")

    curso = database.session.execute(database.select(Curso).filter_by(codigo="CCA-P4")).scalars().one()
    curso.pagado = True
    database.session.commit()

    domains, by_key = _course_questions_by_domain("CCA-P4", member)
    assert domains == [], "an unpaid enrollment must not gather paid questions"
    assert by_key == {}


def test_standing_follows_the_item_not_the_row(cca_db):
    """Answering the mock copy must still count for the surviving section-quiz row.

    De-duplication keeps one physical row per item. Keying the member's latest answer
    by question id meant an answer recorded against the other copy never matched, and
    the card reported "not attempted" for a question they had answered.
    """
    import json

    from now_lms.db import Answer, Evaluation, EvaluationAttempt

    repeated = _question("Answered in the mock only.", "d-alpha")
    member = _member("standing-member")
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P5", [repeated], [repeated]))
    _enroll(member, "CCA-P5")

    exam = [
        evaluation
        for evaluation in database.session.execute(database.select(Evaluation)).scalars()
        if evaluation.is_exam and evaluation.title.endswith("Practice test course")
    ][-1]
    exam_question = exam.questions[0]
    correct = sorted(option.id for option in exam_question.options if option.is_correct)

    attempt = EvaluationAttempt(evaluation_id=exam.id, user_id=member.usuario)
    database.session.add(attempt)
    database.session.flush()
    database.session.add(
        Answer(attempt_id=attempt.id, question_id=exam_question.id, selected_option_ids=json.dumps(correct))
    )
    database.session.commit()

    domains, _by_key = _course_questions_by_domain("CCA-P5", member)
    row = next(entry for entry in domains if entry["key"] == "d-alpha")
    assert row["seen"] == 1, "the answer was given in the exam copy and must still count"
    assert row["correct"] == 1


def test_the_same_item_seeded_twice_appears_once(cca_db):
    """The defect this de-duplication exists for.

    A course's mock exam re-imports the whole bank its section quizzes already cover,
    so the identical question exists as two rows. Measured on the real curriculum,
    CCA-A held 132 labelled rows for 96 distinct questions. Without this, a drill
    repeats items inside one sitting and counts the same question twice in its own
    denominator.
    """
    repeated = _question("This item is in both the quiz and the mock.", "d-alpha")
    member = _member()
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P2", [repeated], [repeated]))
    _enroll(member, "CCA-P2")

    rows = [
        question
        for question in database.session.execute(database.select(Question)).scalars()
        if question.text == "This item is in both the quiz and the mock."
    ]
    assert len(rows) == 2, "the fixture must actually produce the duplicate this guards against"

    _domains, by_key = _course_questions_by_domain("CCA-P2", member)
    gathered = by_key["d-alpha"]
    assert len(gathered) == 1, "the drill must not show the same question twice"
    assert gathered[0].text == "This item is in both the quiz and the mock."


def test_the_domain_total_counts_distinct_questions(cca_db):
    """The count on a domain card has to agree with what the drill will show."""
    repeated = _question("Repeated item.", "d-alpha")
    unique = _question("Unique item.", "d-alpha")
    member = _member()
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P3", [repeated, unique], [repeated]))
    _enroll(member, "CCA-P3")

    domains, by_key = _course_questions_by_domain("CCA-P3", member)
    row = next(entry for entry in domains if entry["key"] == "d-alpha")
    assert row["total"] == 2
    assert row["total"] == len(by_key["d-alpha"]), "the card's count and the drill's length must match"


def test_a_course_with_no_labelled_questions_returns_nothing(cca_db):
    """An unlabelled course must render an empty chooser, not raise."""
    domains, by_key = _course_questions_by_domain("CCA-DOES-NOT-EXIST", _member())
    assert domains == []
    assert by_key == {}


def test_a_limited_attempt_evaluation_is_not_drillable_even_without_the_exam_flag(cca_db):
    """`is_exam` is not sufficient, and relying on it was the second disclosure path.

    `is_exam` and `max_attempts` are independent fields on the instructor form, so an
    instructor can create a scored, limited-attempt evaluation without ticking "is an
    exam". Admitting it into a drill hands out its answer key just the same. A finite
    attempt limit is what makes an evaluation scored in practice.
    """
    from now_lms.db import Evaluation

    section = [_question("Quiz item.", "d-alpha")]
    member = _member("limited-member")
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P6", section, None))
    _enroll(member, "CCA-P6")

    # Turn this course's seeded quizzes into scored ones WITHOUT marking them exams.
    # Scoped by section rather than found by question text: once other tests have
    # seeded courses, a text lookup picks up whatever else is in the table.
    from now_lms.db import CursoSeccion

    section_ids = [
        section.id
        for section in database.session.execute(database.select(CursoSeccion).filter_by(curso="CCA-P6")).scalars()
    ]
    quizzes = list(
        database.session.execute(
            database.select(Evaluation).filter(Evaluation.section_id.in_(section_ids))
        ).scalars()
    )
    assert quizzes, "the fixture must have seeded at least one evaluation"
    for quiz in quizzes:
        assert quiz.is_exam is False, "the fixture must be an unmarked evaluation"
        quiz.max_attempts = 2
    database.session.commit()

    domains, by_key = _course_questions_by_domain("CCA-P6", member)
    assert domains == [], "a limited-attempt evaluation must not be drillable"
    assert by_key == {}


def test_an_inactive_enrollment_reaches_nothing(cca_db):
    """`can_user_access_evaluation` never checks `vigente`.

    It verifies the enrollment row exists and that a paid course was paid for, so a
    withdrawn or suspended learner keeps access through it. Practice adds the check
    rather than widening that shared helper, which other routes depend on.
    """
    from now_lms.db import EstudianteCurso

    section = [_question("Item behind an inactive enrollment.", "d-alpha")]
    member = _member("inactive-member")
    _seed_tests.seed._create_course(database, MODELS, _spec("CCA-P7", section, None))
    database.session.add(EstudianteCurso(usuario=member.usuario, curso="CCA-P7", vigente=False))
    database.session.commit()

    domains, by_key = _course_questions_by_domain("CCA-P7", member)
    assert domains == [], "an inactive enrollment must not gather anything"
    assert by_key == {}
