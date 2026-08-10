# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""
NOW Learning Management System.

Evaluations management.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------------------
import json
from datetime import datetime

# ---------------------------------------------------------------------------------------
# Third-party libraries
# ---------------------------------------------------------------------------------------
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.wrappers import Response

# ---------------------------------------------------------------------------------------
# Local resources
# ---------------------------------------------------------------------------------------
from now_lms.auth import perfil_requerido
from now_lms.db import (
    Answer,
    Curso,
    CursoSeccion,
    EstudianteCurso,
    Evaluation,
    EvaluationAttempt,
    EvaluationReopenRequest,
    Question,
    QuestionOption,
    database,
)
from now_lms.forms import EvaluationReopenRequestForm
from now_lms.i18n import _
from now_lms.themes import get_evaluation_result_template, get_practice_template

# ---------------------------------------------------------------------------------------
# Blueprint definition
# ---------------------------------------------------------------------------------------

# <--------------------------------------------------------------------------> #
# Route constants
ROUTE_COURSE_TOMAR_CURSO = "course.tomar_curso"
EVALUATION_CREATED = _("Evaluación creada correctamente.")
EVALUATION_UPDATED = _("Evaluación actualizada correctamente.")
EVALUATION_DELETED = _("Evaluación eliminada correctamente.")
QUESTION_ADDED = _("Pregunta agregada correctamente.")
QUESTION_UPDATED = _("Pregunta actualizada correctamente.")
QUESTION_DELETED = _("Pregunta eliminada correctamente.")
EVALUATION_SUBMITTED = _("Evaluación enviada correctamente.")
REOPEN_REQUEST_SUBMITTED = _("Solicitud de reabrir evaluación enviada.")
REOPEN_REQUEST_APPROVED = _("Solicitud aprobada. El estudiante puede realizar un nuevo intento.")
REOPEN_REQUEST_REJECTED = _("Solicitud rechazada.")
NO_AUTHORIZED_MSG = _("No se encuentra autorizado a acceder al recurso solicitado.")

# <--------------------------------------------------------------------------> #
# Blueprint for evaluation management
evaluation = Blueprint("evaluation", __name__)


def can_user_access_evaluation(evaluation_obj, user) -> bool:
    """Check if user can access evaluation based on course payment status."""
    # Get the course from the section
    section = database.session.get(CursoSeccion, evaluation_obj.section_id)
    if not section:
        return False

    course_code = section.curso

    # Check if user is enrolled in the course
    inscription = (
        database.session.execute(database.select(EstudianteCurso).filter_by(curso=course_code, usuario=user.usuario))
        .scalars()
        .first()
    )
    if not inscription:
        return False

    # Check if course is paid and user has paid

    course = database.session.execute(database.select(Curso).filter_by(codigo=course_code)).scalars().first()
    if course and course.pagado:
        # Check if user has paid for the course
        enrollment = (
            database.session.execute(database.select(EstudianteCurso).filter_by(curso=course_code, usuario=user.usuario))
            .scalars()
            .first()
        )

        if not enrollment or not enrollment.pago:
            return False  # User hasn't paid for paid course

    return True


def is_evaluation_available(evaluation_obj) -> bool:
    """Check if evaluation is currently available."""
    if evaluation_obj.available_until:
        return datetime.now() <= evaluation_obj.available_until
    return True


def get_user_attempts_count(evaluation_id: int, user_id: str) -> int:
    """Get the number of attempts a user has made for an evaluation."""
    result = database.session.execute(
        database.select(func.count(EvaluationAttempt.id)).filter_by(evaluation_id=evaluation_id, user_id=user_id)
    ).scalar()
    return result or 0


def can_user_attempt_evaluation(evaluation_obj, user) -> bool:
    """Check if user can attempt the evaluation."""
    if not can_user_access_evaluation(evaluation_obj, user):
        return False

    if not is_evaluation_available(evaluation_obj):
        return False

    if evaluation_obj.max_attempts:
        attempts_count = get_user_attempts_count(evaluation_obj.id, user.usuario)
        if attempts_count >= evaluation_obj.max_attempts:
            return False

    return True


def _answer_is_correct(answer) -> bool:
    """Determine whether a submitted answer is correct."""
    if not answer.selected_option_ids:
        return False
    selected_ids = json.loads(answer.selected_option_ids)
    if answer.question.type == "boolean":
        if len(selected_ids) != 1:
            return False
        option = database.session.get(QuestionOption, selected_ids[0])
        return bool(option and option.is_correct)
    if answer.question.type == "multiple":
        correct_ids = {option.id for option in answer.question.options if option.is_correct}
        return set(selected_ids) == correct_ids
    return False


def calculate_score(attempt) -> float:
    """Calculate the score for an evaluation attempt."""
    total_questions = len(attempt.evaluation.questions)
    if total_questions == 0:
        return 0.0

    correct_answers = sum(_answer_is_correct(answer) for answer in attempt.answers)

    return (correct_answers / total_questions) * 100


def _resolve_option_ids(question, selected_values: list[str]) -> list[str]:
    """Resolve form values to option IDs based on question type."""
    option_ids: list[str] = []
    for value in selected_values:
        if question.type != "boolean":
            option_ids.append(value)
            continue
        option = (
            database.session.execute(database.select(QuestionOption).filter_by(question_id=question.id, text=value))
            .scalars()
            .first()
        )
        if option:
            option_ids.append(option.id)
    return option_ids


def _save_question_answers(attempt, evaluation_obj) -> None:
    """Process and save answers for all questions in an evaluation attempt."""
    for question in evaluation_obj.questions:
        answer_key = f"question_{question.id}"
        if answer_key not in request.form:
            continue
        selected_values = request.form.getlist(answer_key)
        selected_option_ids = _resolve_option_ids(question, selected_values)
        answer = Answer(
            attempt_id=attempt.id,
            question_id=question.id,
            selected_option_ids=json.dumps(selected_option_ids),
        )
        database.session.add(answer)


def _try_issue_certificate(section) -> None:
    """Attempt to issue a certificate if the user is eligible."""
    if not section:
        return
    from now_lms.vistas.courses import _emitir_certificado
    from now_lms.vistas.evaluation_helpers import can_user_receive_certificate

    can_receive, _reason = can_user_receive_certificate(section.curso, current_user.usuario)
    if not can_receive:
        return
    curso = database.session.execute(database.select(Curso).filter(Curso.codigo == section.curso)).scalars().first()
    if curso and curso.certificado and curso.plantilla_certificado:
        _emitir_certificado(section.curso, current_user.usuario, curso.plantilla_certificado)


@evaluation.route("/evaluation/<evaluation_id>/take", methods=["GET", "POST"])
@login_required
@perfil_requerido("student")
def take_evaluation(evaluation_id: int) -> str | Response:
    """Take an evaluation."""
    eval_obj = database.session.get(Evaluation, evaluation_id)
    if not eval_obj:
        abort(404)

    if not can_user_access_evaluation(eval_obj, current_user):
        flash(_("No tiene acceso a esta evaluación."), "warning")
        abort(403)

    if not can_user_attempt_evaluation(eval_obj, current_user):
        flash(_("No puede realizar más intentos en esta evaluación."), "warning")
        section = database.session.get(CursoSeccion, eval_obj.section_id)
        return redirect(url_for(ROUTE_COURSE_TOMAR_CURSO, course_code=section.curso))

    if request.method == "POST":
        attempt = EvaluationAttempt(evaluation_id=evaluation_id, user_id=current_user.usuario, started_at=datetime.now())
        database.session.add(attempt)
        database.session.flush()

        _save_question_answers(attempt, eval_obj)

        attempt.submitted_at = datetime.now()
        attempt.score = calculate_score(attempt)
        attempt.passed = attempt.score >= eval_obj.passing_score

        database.session.commit()

        if attempt.passed:
            section = database.session.get(CursoSeccion, eval_obj.section_id)
            _try_issue_certificate(section)

        flash(EVALUATION_SUBMITTED, "success")
        return redirect(url_for("evaluation.evaluation_result", attempt_id=attempt.id))

    return render_template("evaluations/take_evaluation.html", evaluation=eval_obj)


@evaluation.route("/evaluation/attempt/<attempt_id>/result", methods=["GET"])
@login_required
@perfil_requerido("student")
def evaluation_result(attempt_id: int) -> str:
    """Show evaluation attempt result."""
    attempt = database.session.get(EvaluationAttempt, attempt_id)
    if not attempt:
        abort(404)

    # Check if user owns this attempt
    if attempt.user_id != current_user.usuario:
        abort(403)

    return render_template(get_evaluation_result_template(), attempt=attempt)


def _is_safe_to_drill(evaluation_obj) -> bool:
    """Whether an evaluation's questions may be shown with their answers.

    `is_exam` is NOT sufficient. It and `max_attempts` are independent fields on the
    instructor form, so a scored, limited-attempt evaluation can exist without anybody
    ticking "is an exam" — and admitting it into a drill hands out its answer key just
    the same. A finite attempt limit is what makes an evaluation scored in practice, so
    that is the test.

    What remains drillable is the unlimited-attempt practice quiz, which already shows
    its own answers after any submission. Drilling it discloses nothing new.
    """
    if evaluation_obj.is_exam or evaluation_obj.max_attempts is not None:
        return False
    # An instructor who sets `available_until` has closed the quiz. The normal attempt
    # path honours that through `is_evaluation_available`; practice must too, or a
    # closed quiz keeps handing out its answers and explanations indefinitely.
    return is_evaluation_available(evaluation_obj)


def _active_enrollment(course_code: str, usuario: str):
    """An enrollment that is actually current.

    `can_user_access_evaluation` checks that an EstudianteCurso row exists and that a
    paid course was paid for, but never checks `vigente` — so a withdrawn or suspended
    learner keeps access through it. Rather than widen that shared helper, which other
    routes depend on, practice adds the check it needs.
    """
    return (
        database.session.execute(
            database.select(EstudianteCurso).filter_by(curso=course_code, usuario=usuario, vigente=True)
        )
        .scalars()
        .first()
    )


def _course_questions_by_domain(course_code: str, user) -> tuple[list[dict], dict]:
    """Every labelled question in a course, grouped by domain, with the member's standing.

    Reads across the course's evaluations rather than a single one, because a domain's
    items are scattered: some sit in that domain's section quiz, others inside a
    full-length exam that spans every domain at once. Grouping by `domain_key` is the
    only thing that gathers them.

    Standing is computed from the member's MOST RECENT answer to each question, across
    every attempt they have made in this course. Their latest thinking is what a
    "where do I stand" readout should reflect; averaging over old attempts would let a
    first-run guess drag down a domain they have since learned.

    Returns (domains, questions_by_key). Questions carry no ordering guarantee beyond
    the order they were seeded in, which is the bank's own order.
    """
    active_enrollment = _active_enrollment(course_code, user.usuario) is not None

    section_ids = [
        row.id
        for row in database.session.execute(database.select(CursoSeccion).filter_by(curso=course_code)).scalars()
    ]
    if not section_ids:
        return [], {}

    evaluations = list(
        database.session.execute(
            database.select(Evaluation).filter(Evaluation.section_id.in_(section_ids))
        ).scalars()
    )

    # Practice NEVER draws from a scored exam. Those questions are the answer key to an
    # attempt the member has not made yet, and this surface reveals the correct option
    # and the rationale on click — so including them let anyone read the mock exam's
    # answers, then sit it. Unlimited-attempt practice quizzes already show their own
    # answers after a submission, so drawing from those discloses nothing new.
    #
    # Access is delegated to `can_user_access_evaluation` per evaluation rather than
    # re-checked here. An `EstudianteCurso` row merely existing is a weaker gate than
    # the platform's: it ignores `pagado`/`pago` and inactive enrollments, so an unpaid
    # enrollment could reach paid questions.
    practice_ids = [
        evaluation.id
        for evaluation in evaluations
        if _is_safe_to_drill(evaluation) and can_user_access_evaluation(evaluation, user) and active_enrollment
    ]
    evaluation_ids = practice_ids
    if not evaluation_ids:
        return [], {}

    questions = list(
        database.session.execute(
            database.select(Question)
            .filter(Question.evaluation_id.in_(evaluation_ids))
            .filter(Question.domain_key.isnot(None))
            .order_by(Question.order)
        ).scalars()
    )

    # Latest answer per question for this member, newest attempt last so it wins.
    #
    # Keyed by question TEXT, not id. The same bank item exists as several rows, and
    # de-duplication below keeps only one of them — so an answer recorded against the
    # mock-exam copy would never match the surviving section-quiz row, and the card
    # would report "not attempted" for a question the member has answered. Standing is
    # about the item, not the row.
    #
    # Attempts are read across EVERY evaluation in the course, including exams: the
    # exam is where most items get answered, and reading a member's own history is not
    # the disclosure the exam filter above guards against.
    all_evaluation_ids = [evaluation.id for evaluation in evaluations]
    latest: dict[str, list] = {}
    attempts = list(
        database.session.execute(
            database.select(EvaluationAttempt)
            .filter(EvaluationAttempt.evaluation_id.in_(all_evaluation_ids))
            .filter_by(user_id=user.usuario)
            .order_by(EvaluationAttempt.started_at)
        ).scalars()
    )
    for attempt in attempts:
        for answer in attempt.answers:
            if not answer.selected_option_ids or answer.question is None:
                continue
            chosen = set(json.loads(answer.selected_option_ids))
            # Stored as option TEXT, not option id. Each duplicated question row owns
            # its own QuestionOption rows, so the ids of the mock-exam copy never match
            # the section-quiz copy's — comparing ids across copies can only ever say
            # "wrong". Text is the identity the seeder copies verbatim from the bank.
            latest[answer.question.text] = sorted(
                option.text for option in answer.question.options if option.id in chosen
            )

    # The same bank item is seeded more than once on purpose: a course's mock exam
    # re-imports the whole bank that its section quizzes already cover, so CCA-A holds
    # 132 labelled rows for 96 distinct questions. Left alone a drill repeats items
    # within a single sitting, and a repeated question would also be counted twice in
    # the denominator below. Identity is the question text, which is what the seeder
    # copies verbatim from the bank; the first row wins so section order is preserved.
    seen_text: set = set()
    deduped = []
    for question in questions:
        if question.text in seen_text:
            continue
        seen_text.add(question.text)
        deduped.append(question)
    questions = deduped

    by_key: dict[str, list] = {}
    stats: dict[str, dict] = {}
    for question in questions:
        by_key.setdefault(question.domain_key, []).append(question)
        row = stats.setdefault(
            question.domain_key,
            {"key": question.domain_key, "name": question.domain_name or question.domain_key,
             "total": 0, "seen": 0, "correct": 0},
        )
        row["total"] += 1
        selected = latest.get(question.text)
        if selected is not None:
            row["seen"] += 1
            correct_texts = sorted(option.text for option in question.options if option.is_correct)
            if selected == correct_texts:
                row["correct"] += 1

    domains = sorted(stats.values(), key=lambda row: row["name"])
    return domains, by_key


@evaluation.route("/course/<course_code>/practice")
@login_required
@perfil_requerido("student")
def practice_by_domain(course_code: str) -> str | Response:
    """Practice one domain of a course, or choose which domain to practice.

    Deliberately NOT an attempt. A drill is rehearsal: it records nothing, so a member
    can work the same weak domain repeatedly without polluting the exam history their
    result pages are built from. Grading and feedback happen in the page.
    """
    if _active_enrollment(course_code, current_user.usuario) is None:
        abort(403)

    domains, by_key = _course_questions_by_domain(course_code, current_user)
    selected_key = request.args.get("domain") or None
    if selected_key and selected_key not in by_key:
        abort(404)

    return render_template(
        get_practice_template(),
        course_code=course_code,
        domains=domains,
        selected_key=selected_key,
        selected_name=next((row["name"] for row in domains if row["key"] == selected_key), None),
        questions=by_key.get(selected_key, []),
    )


@evaluation.route("/evaluation/<evaluation_id>/request-reopen", methods=["GET", "POST"])
@login_required
@perfil_requerido("student")
def request_reopen(evaluation_id: int) -> str | Response:
    """Request to reopen an evaluation."""
    eval_obj = database.session.get(Evaluation, evaluation_id)
    if not eval_obj:
        abort(404)

    # Check if user can access this evaluation
    if not can_user_access_evaluation(eval_obj, current_user):
        abort(403)

    # Check if user has exhausted attempts and not passed
    attempts_count = get_user_attempts_count(evaluation_id, current_user.usuario)
    if not eval_obj.max_attempts or attempts_count < eval_obj.max_attempts:
        flash(_("Aún tiene intentos disponibles."), "info")
        section = database.session.get(CursoSeccion, eval_obj.section_id)
        return redirect(url_for(ROUTE_COURSE_TOMAR_CURSO, course_code=section.curso))

    # Check if user has passed any attempt
    passed_attempt = (
        database.session.execute(
            database.select(EvaluationAttempt).filter_by(
                evaluation_id=evaluation_id, user_id=current_user.usuario, passed=True
            )
        )
        .scalars()
        .first()
    )

    if passed_attempt:
        flash(_("Ya ha aprobado esta evaluación."), "info")
        section = database.session.get(CursoSeccion, eval_obj.section_id)
        return redirect(url_for(ROUTE_COURSE_TOMAR_CURSO, course_code=section.curso))

    form = EvaluationReopenRequestForm()

    if form.validate_on_submit():
        # Check if there's already a pending request
        existing_request = (
            database.session.execute(
                database.select(EvaluationReopenRequest).filter_by(
                    user_id=current_user.usuario, evaluation_id=evaluation_id, status="pending"
                )
            )
            .scalars()
            .first()
        )

        if existing_request:
            flash(_("Ya tiene una solicitud pendiente para esta evaluación."), "warning")
            section = database.session.get(CursoSeccion, eval_obj.section_id)
            return redirect(url_for(ROUTE_COURSE_TOMAR_CURSO, course_code=section.curso))

        reopen_request = EvaluationReopenRequest(
            user_id=current_user.usuario, evaluation_id=evaluation_id, justification_text=form.justification_text.data
        )

        database.session.add(reopen_request)
        database.session.commit()

        flash(REOPEN_REQUEST_SUBMITTED, "success")
        section = database.session.get(CursoSeccion, eval_obj.section_id)
        return redirect(url_for(ROUTE_COURSE_TOMAR_CURSO, course_code=section.curso))

    return render_template("evaluations/request_reopen.html", evaluation=eval_obj, form=form)


# Instructor routes will be added to the instructor profile blueprint
