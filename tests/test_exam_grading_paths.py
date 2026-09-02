# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""End-to-end regressions for grading and answer persistence.

These exercise the real scoring functions against real rows, because the previous
tests asserted the shape of a stored form and a form snapshot cannot show that
`calculate_score` never read it. Every case here failed before the fix.
"""

import json

import pytest

from now_lms.db import (
    Answer,
    Curso,
    CursoSeccion,
    Evaluation,
    EvaluationAttempt,
    Question,
    QuestionOption,
    database,
)
from now_lms.vistas import exam_forms
from now_lms.vistas.evaluations import (
    _graded_paper,
    _record_answer,
    _stored_selections,
    calculate_score,
)


@pytest.fixture
def sitting(app):
    """One course, one evaluation, two questions, and an attempt with a drawn paper."""
    with app.app_context():
        curso = Curso(
            codigo="GRADE-1", nombre="Grading", descripcion="d", descripcion_corta="d",
            estado="open", publico=False, modalidad="self_paced", nivel=1, duracion=1,
            pagado=False, certificado=False, precio=0,
        )
        database.session.add(curso)
        seccion = CursoSeccion(curso="GRADE-1", nombre="S", descripcion="d", indice=1, estado=True)
        database.session.add(seccion)
        database.session.commit()

        evaluation = Evaluation(
            section_id=seccion.id, title="Graded", description="d",
            is_exam=True, passing_score=50.0, scaled_cut=720,
        )
        database.session.add(evaluation)
        database.session.commit()

        questions = []
        for index in range(2):
            question = Question(
                evaluation_id=evaluation.id, type="multiple", text=f"q{index}", order=index + 1
            )
            database.session.add(question)
            database.session.commit()
            for position in range(4):
                database.session.add(
                    QuestionOption(
                        question_id=question.id, text=f"opt {position}", is_correct=(position == 0)
                    )
                )
            database.session.commit()
            questions.append(question)

        attempt = EvaluationAttempt(evaluation_id=evaluation.id, user_id="lms-admin")
        attempt.form_json = exam_forms.dump_form(
            exam_forms.build_form(list(evaluation.questions), evaluation, None)
        )
        database.session.add(attempt)
        database.session.commit()
        yield evaluation, questions, attempt


def _answer_correctly(attempt, questions):
    for question in questions:
        correct = [o.id for o in question.options if o.is_correct]
        _record_answer(attempt, question.id, correct)
    database.session.commit()


def test_a_perfect_paper_scores_one_hundred(app, sitting):
    _evaluation, questions, attempt = sitting
    with app.app_context():
        attempt = database.session.get(EvaluationAttempt, attempt.id)
        _answer_correctly(attempt, [database.session.get(Question, q.id) for q in questions])
        assert calculate_score(attempt) == pytest.approx(100.0)


def test_moving_the_live_key_after_the_draw_does_not_regrade_the_attempt(app, sitting):
    """The defect: the frozen key was stored and then ignored. A direct probe scored
    a frozen-correct answer 100 before the instructor moved the live key and 0 after."""
    _evaluation, questions, attempt = sitting
    with app.app_context():
        attempt = database.session.get(EvaluationAttempt, attempt.id)
        live_questions = [database.session.get(Question, q.id) for q in questions]
        _answer_correctly(attempt, live_questions)
        before = calculate_score(attempt)

        # the instructor moves every key to a different option
        for question in live_questions:
            for position, option in enumerate(question.options):
                option.is_correct = position == 3
        database.session.commit()

        assert calculate_score(attempt) == pytest.approx(before), (
            "a finished attempt must be graded against the key it was shown"
        )


def test_deleting_a_question_leaves_the_paper_and_the_answer_intact(app, sitting):
    """Answer rows cascade on question deletion; the frozen paper still renders it."""
    evaluation, questions, attempt = sitting
    evaluation_id = evaluation.id
    with app.app_context():
        attempt = database.session.get(EvaluationAttempt, attempt.id)
        live_questions = [database.session.get(Question, q.id) for q in questions]
        _answer_correctly(attempt, live_questions)
        before = calculate_score(attempt)

        database.session.delete(database.session.get(Question, questions[1].id))
        database.session.commit()

        attempt = database.session.get(EvaluationAttempt, attempt.id)
        graded = _graded_paper(attempt, database.session.get(Evaluation, evaluation_id))
        assert len(graded) == 2, "the paper still has both questions"
        assert calculate_score(attempt) == pytest.approx(before), (
            "the deleted question's answer survives on the attempt"
        )
        assert len(_stored_selections(attempt)) == 2


def test_recording_the_same_answer_twice_does_not_double_count_it(app, sitting):
    """Two concurrent autosaves inserted two Answer rows and a one-question paper
    scored 200 percent."""
    _evaluation, questions, attempt = sitting
    with app.app_context():
        attempt = database.session.get(EvaluationAttempt, attempt.id)
        live = [database.session.get(Question, q.id) for q in questions]
        correct = [o.id for o in live[0].options if o.is_correct]
        for _ in range(3):
            _record_answer(attempt, live[0].id, correct)
        database.session.commit()

        rows = database.session.execute(
            database.select(Answer).filter_by(attempt_id=attempt.id, question_id=live[0].id)
        ).scalars().all()
        assert len(rows) == 1, "one answer per question per attempt"
        assert calculate_score(attempt) == pytest.approx(50.0), "one of two right is 50, not 150"


def test_an_answer_changed_before_submit_replaces_rather_than_adds(app, sitting):
    _evaluation, questions, attempt = sitting
    with app.app_context():
        attempt = database.session.get(EvaluationAttempt, attempt.id)
        live = [database.session.get(Question, q.id) for q in questions]
        wrong = [o.id for o in live[0].options if not o.is_correct][:1]
        right = [o.id for o in live[0].options if o.is_correct]

        _record_answer(attempt, live[0].id, wrong)
        database.session.commit()
        assert calculate_score(attempt) == pytest.approx(0.0)

        _record_answer(attempt, live[0].id, right)
        database.session.commit()
        assert calculate_score(attempt) == pytest.approx(50.0)
        assert _stored_selections(attempt)[live[0].id] == right


def test_selections_survive_a_reload_of_the_attempt(app, sitting):
    """Answers were written only at submit, so a refresh lost every selection."""
    _evaluation, questions, attempt = sitting
    attempt_id = attempt.id
    question_id = questions[0].id

    with app.app_context():
        live_attempt = database.session.get(EvaluationAttempt, attempt_id)
        question = database.session.get(Question, question_id)
        chosen = [o.id for o in question.options if o.is_correct]
        _record_answer(live_attempt, question_id, chosen)
        database.session.commit()

    # A separate context is a separate session: this is the refresh, the crash and
    # the other device, all of which used to come back with nothing selected.
    with app.app_context():
        reloaded = database.session.get(EvaluationAttempt, attempt_id)
        assert _stored_selections(reloaded)[question_id] == chosen


def test_a_legacy_attempt_with_no_paper_still_grades_the_old_way(app, sitting):
    """Every attempt taken before the exam form existed has form_json NULL."""
    _evaluation, questions, attempt = sitting
    with app.app_context():
        attempt = database.session.get(EvaluationAttempt, attempt.id)
        attempt.form_json = None
        attempt.answers_json = None
        live = [database.session.get(Question, q.id) for q in questions]
        for question in live:
            database.session.add(
                Answer(
                    attempt_id=attempt.id,
                    question_id=question.id,
                    selected_option_ids=json.dumps([o.id for o in question.options if o.is_correct]),
                )
            )
        database.session.commit()
        assert calculate_score(attempt) == pytest.approx(100.0)
