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
from datetime import UTC, datetime, timedelta

# ---------------------------------------------------------------------------------------
# Third-party libraries
# ---------------------------------------------------------------------------------------
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload
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
from now_lms.themes import (
    get_evaluation_result_template,
    get_practice_template,
    get_take_evaluation_template,
)
from now_lms.vistas import exam_forms

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


def _now() -> datetime:
    """The clock every deadline in this module is measured against.

    UTC, but naive, to match what is actually stored. `utc_now()` returns an AWARE
    datetime while `EvaluationAttempt.started_at` is a plain DateTime column, so a
    value read back from the database is naive and comparing the two raises. Using
    the local clock instead would be worse: a deadline computed from a UTC
    `started_at` and compared against local time is wrong by the server's offset,
    which silently shortens or lengthens every sitting on a non-UTC host.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _back_from_evaluation(eval_obj) -> str:
    """Where to send someone leaving an evaluation.

    Back to the course for coursework, back to the practice area for a sitting that
    belongs to no course. Written once because the reopen flow has three of these and
    every one of them would raise on a section-less evaluation.
    """
    if eval_obj.section_id:
        section = database.session.get(CursoSeccion, eval_obj.section_id)
        if section:
            return url_for(ROUTE_COURSE_TOMAR_CURSO, course_code=section.curso)
    return url_for("evaluation.practice", certification_key=eval_obj.certification_key)


def can_user_access_evaluation(evaluation_obj, user) -> bool:
    """Check if user can access evaluation based on course payment status.

    An evaluation with no section is a practice sitting rather than coursework. It
    is open to any signed-in member, because it gates nothing: no enrolment, no
    completion, no certificate. The course checks below exist to stop someone
    sitting an assessment for a course they have not paid for, and there is no
    course here to have paid for.
    """
    if evaluation_obj.section_id is None:
        return True

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
        return _now() <= evaluation_obj.available_until
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


def _selection_is_correct(question, selected_ids) -> bool:
    """Is this selection right, judged against the options as given.

    `question` is the paper's own copy when the attempt has one, so an instructor
    moving the key after the paper was drawn cannot regrade work already done. It
    is the live row only for a legacy attempt that has no stored paper.
    """
    if not selected_ids:
        return False
    correct_ids = {option.id for option in question.options if option.is_correct}
    if not correct_ids:
        return False
    return set(selected_ids) == correct_ids


def _answer_is_correct(answer) -> bool:
    """Legacy path: judge a stored Answer row against the live question.

    Kept for attempts with no stored paper, which is every attempt taken before
    the exam form existed. Anything with a paper is graded by
    `_selection_is_correct` against the frozen options instead: reading the live
    rows here is what let an instructor's edit change a finished score.
    """
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


def _graded_paper(attempt, evaluation_obj) -> list:
    """Every question on this attempt's paper with whether it was answered right.

    One list, built once, used by the percentage score, the scaled score, the
    per-domain diagnostic and the review. Each question appears exactly once
    however many Answer rows exist for it, which is what stopped a duplicate row
    scoring a one-question paper at 200 percent.
    """
    form = exam_forms.load_form(attempt.form_json)
    paper = exam_forms.form_questions(form, evaluation_obj)
    selections = _stored_selections(attempt)
    if form:
        return [(q, _selection_is_correct(q, selections.get(q.id, []))) for q in paper]
    # No paper: grade the legacy way, one row per question.
    by_question = {a.question_id: a for a in attempt.answers}
    return [
        (q, bool(by_question.get(q.id) and _answer_is_correct(by_question[q.id])))
        for q in paper
    ]


def calculate_score(attempt) -> float:
    """Calculate the score for an evaluation attempt.

    The denominator is the number of questions on THIS attempt's paper, not the
    number in the evaluation. Once an evaluation carries a `draw_size` the two
    differ: a 53-question paper drawn from a 106-question pool would otherwise
    score a perfect sitting at 50 percent, and an evaluation drawn but not scaled
    would fail a candidate who answered everything correctly.
    """
    graded = _graded_paper(attempt, attempt.evaluation)
    if not graded:
        return 0.0
    return (sum(1 for _question, correct in graded if correct) / len(graded)) * 100


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


def _save_question_answers(attempt, evaluation_obj, questions=None) -> None:
    """Process and save answers for the questions this attempt was actually given.

    ``questions`` is the attempt's drawn paper. It defaults to the evaluation's
    stored questions so an untimed, undrawn evaluation behaves exactly as before.
    Grading anything other than the paper the candidate saw would score them on
    questions that were never on screen.
    """
    for question in questions if questions is not None else evaluation_obj.questions:
        answer_key = f"question_{question.id}"
        if answer_key not in request.form:
            continue
        selected_values = request.form.getlist(answer_key)
        selected_option_ids = _resolve_option_ids(question, selected_values)
        _record_answer(attempt, question.id, selected_option_ids)


def _stored_selections(attempt) -> dict:
    """What this attempt has answered, as {question_id: [option_id, ...]}.

    Read from the attempt's own `answers_json` when it has one. Falling back to the
    `Answer` rows covers attempts written before that column existed, and those rows
    are cascade-deleted when a question is deleted, which is precisely why the
    authoritative copy lives on the attempt.
    """
    raw = getattr(attempt, "answers_json", None)
    if raw:
        try:
            stored = json.loads(raw)
            if isinstance(stored, dict):
                return {k: list(v) for k, v in stored.items() if isinstance(v, list)}
        except (ValueError, TypeError):
            pass

    selections = {}
    for answer in attempt.answers:
        try:
            selections[answer.question_id] = json.loads(answer.selected_option_ids or "[]")
        except (ValueError, TypeError):
            selections[answer.question_id] = []
    return selections


def _record_answer(attempt, question_id: str, selected_option_ids: list) -> None:
    """Record one answer on the attempt, and mirror it to an `Answer` row.

    The attempt's `answers_json` is authoritative: it is a single value on a single
    row, so two concurrent autosaves cannot leave two answers for one question the
    way a read-then-insert against `Answer` could, and it survives the deletion of
    the question it answers.

    The mirror row is best-effort. It keeps anything that reports off `Answer`
    working, and a failure to write it (a question deleted mid-sitting violates the
    FK on PostgreSQL) must not cost the candidate their answer.
    """
    selections = _stored_selections(attempt)
    selections[question_id] = list(selected_option_ids)
    attempt.answers_json = json.dumps(selections)

    payload = json.dumps(selected_option_ids)
    existing = database.session.execute(
        database.select(Answer).filter_by(attempt_id=attempt.id, question_id=question_id)
    ).scalars().first()
    if existing is not None:
        existing.selected_option_ids = payload
        return
    try:
        with database.session.begin_nested():
            database.session.add(
                Answer(attempt_id=attempt.id, question_id=question_id, selected_option_ids=payload)
            )
    except (IntegrityError, SQLAlchemyError):
        # Lost a race to the unique constraint, or the question is gone. The answer
        # is already safe on the attempt.
        pass


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


def _open_attempt(evaluation_id: str, usuario: str):
    """The candidate's sitting that is started but not yet submitted, if any.

    OLDEST first, not newest. If two ever exist the earlier one is the real sitting
    and its clock is the one that has been running; picking the newest would hand a
    candidate a fresh deadline by opening a second tab.
    """
    return database.session.execute(
        database.select(EvaluationAttempt)
        .filter_by(evaluation_id=evaluation_id, user_id=usuario, submitted_at=None)
        .order_by(EvaluationAttempt.started_at.asc())
    ).scalars().first()


def _start_attempt(eval_obj):
    """Open a sitting and draw its paper, at most once per candidate.

    The attempt is created HERE, at the start, rather than at submit as this view
    used to. A timed sitting needs a server-side ``started_at`` to measure the
    deadline from, and a drawn sitting needs its paper fixed before the first
    question is rendered. Creating the row at submit could do neither.

    Two GETs racing (a double-click, or two tabs) both saw no open attempt and both
    created one, leaving the candidate two live papers and a POST that could be
    graded against whichever the query happened to return. The unique partial index
    added in the same migration makes a second open row impossible at the database;
    losing that race is not an error, it means the sitting already started, so the
    loser reads the winner's attempt back and renders the same paper.
    """
    attempt = EvaluationAttempt(
        evaluation_id=eval_obj.id, user_id=current_user.usuario, started_at=_now()
    )
    weights = None
    if eval_obj.blueprint_json:
        try:
            weights = json.loads(eval_obj.blueprint_json)
        except (ValueError, TypeError):
            # A malformed blueprint draws unweighted rather than refusing to start a
            # sitting the candidate is entitled to.
            weights = None
    if eval_obj.draw_size or eval_obj.time_limit_minutes:
        attempt.form_json = exam_forms.dump_form(
            exam_forms.build_form(list(eval_obj.questions), eval_obj, weights)
        )
    database.session.add(attempt)
    try:
        database.session.commit()
    except IntegrityError:
        # The other tab won. Its paper is the sitting.
        database.session.rollback()
        existing = _open_attempt(eval_obj.id, current_user.usuario)
        if existing is not None:
            return existing
        raise
    return attempt


def _deadline(attempt, eval_obj):
    """When this sitting closes, or None if it is untimed."""
    if not eval_obj.time_limit_minutes or not attempt.started_at:
        return None
    return attempt.started_at + timedelta(minutes=eval_obj.time_limit_minutes)


def _grade_attempt(attempt, eval_obj, questions) -> None:
    """Score a sitting and close it. Shared by a submit and by the clock."""
    attempt.submitted_at = _now()
    attempt.score = calculate_score(attempt)
    attempt.passed = attempt.score >= eval_obj.passing_score
    if eval_obj.scaled_cut:
        graded = _graded_paper(attempt, eval_obj)
        total = len(graded) or len(questions)
        raw = sum(1 for _question, correct in graded if correct)
        attempt.scaled_score = exam_forms.scale_score(raw, total)
        # The scaled score is the reported result when there is one, so the
        # pass/fail must agree with the number on screen rather than with a
        # percentage the candidate is never shown.
        attempt.passed = attempt.scaled_score >= eval_obj.scaled_cut
    database.session.commit()


@evaluation.route("/evaluation/<evaluation_id>/take", methods=["GET", "POST"])
@login_required
@perfil_requerido("student")
def take_evaluation(evaluation_id: int) -> str | Response:
    """Take an evaluation, timed and drawn where the evaluation says so."""
    eval_obj = database.session.get(Evaluation, evaluation_id)
    if not eval_obj:
        abort(404)

    if not can_user_access_evaluation(eval_obj, current_user):
        flash(_("No tiene acceso a esta evaluación."), "warning")
        abort(403)

    attempt = _open_attempt(eval_obj.id, current_user.usuario)

    # A sitting whose clock ran out while the candidate was away is scored as it
    # stands, on the way in. Leaving it open would hand back the time they spent
    # elsewhere, and silently discarding it would lose answers they gave.
    if attempt is not None:
        deadline = _deadline(attempt, eval_obj)
        if deadline and _now() >= deadline:
            attempt.was_late = True
            _grade_attempt(attempt, eval_obj, exam_forms.form_questions(
                exam_forms.load_form(attempt.form_json), eval_obj))
            flash(_("Time ran out, so the sitting was submitted for you."), "warning")
            return redirect(url_for("evaluation.evaluation_result", attempt_id=attempt.id))

    # Availability is checked whether or not a sitting is already open. Gating it on
    # "no open attempt" let an open legacy attempt outlive its `available_until`,
    # which is a change in behaviour for every evaluation that predates this work.
    if not is_evaluation_available(eval_obj):
        flash(_("Esta evaluación no está disponible."), "warning")
        return redirect(_back_from_evaluation(eval_obj))

    if attempt is None and not can_user_attempt_evaluation(eval_obj, current_user):
        flash(_("No puede realizar más intentos en esta evaluación."), "warning")
        section = database.session.get(CursoSeccion, eval_obj.section_id) if eval_obj.section_id else None
        if section is None:
            # A practice sitting has no course to send them back to.
            return redirect(url_for("evaluation.practice", certification_key=eval_obj.certification_key))
        return redirect(url_for(ROUTE_COURSE_TOMAR_CURSO, course_code=section.curso))

    if attempt is None:
        attempt = _start_attempt(eval_obj)

    questions = exam_forms.form_questions(exam_forms.load_form(attempt.form_json), eval_obj)

    if request.method == "POST":
        # The form carries the id of the attempt it was rendered for. Without it a
        # submit is just "the newest open attempt", so a stale tab could be graded
        # against a paper it never showed.
        submitted_for = request.form.get("attempt_id")
        if submitted_for and submitted_for != attempt.id:
            flash(_("That page belonged to an earlier sitting. This is the current one."), "warning")
            return redirect(url_for("evaluation.take_evaluation", evaluation_id=eval_obj.id))
        _save_question_answers(attempt, eval_obj, questions)
        database.session.flush()
        deadline = _deadline(attempt, eval_obj)
        attempt.was_late = bool(deadline and _now() > deadline)
        _grade_attempt(attempt, eval_obj, questions)

        if attempt.passed and eval_obj.section_id:
            # Practice earns no certificate: it is rehearsal, and nothing about it
            # is a completion signal for a course.
            _try_issue_certificate(database.session.get(CursoSeccion, eval_obj.section_id))

        flash(EVALUATION_SUBMITTED, "success")
        return redirect(url_for("evaluation.evaluation_result", attempt_id=attempt.id))

    deadline = _deadline(attempt, eval_obj)
    return render_template(
        get_take_evaluation_template(),
        evaluation=eval_obj,
        questions=questions,
        attempt=attempt,
        selections=_stored_selections(attempt),
        # Seconds rather than a timestamp: the browser's clock may be wrong, and
        # only the server's view of the deadline is authoritative anyway.
        seconds_remaining=int((deadline - _now()).total_seconds()) if deadline else None,
        scaled_cut=eval_obj.scaled_cut,
    )


@evaluation.route("/evaluation/<evaluation_id>/answer", methods=["POST"])
@login_required
@perfil_requerido("student")
def save_answer(evaluation_id: str) -> Response:
    """Persist one answer mid-sitting. Called as the candidate selects.

    Deliberately forgiving toward the candidate: it fires on every click and must
    never interrupt a sitting. Strict about WHICH sitting: the request names its
    attempt, and anything that is not that attempt, still open, and theirs is
    refused rather than written somewhere else.
    """
    eval_obj = database.session.get(Evaluation, evaluation_id)
    if not eval_obj or not can_user_access_evaluation(eval_obj, current_user):
        return Response(status=403)

    # The tab names the attempt it belongs to. Choosing "whichever attempt is open"
    # meant a stale tab from a finished sitting could overwrite the next one.
    attempt_id = request.form.get("attempt_id")
    if not attempt_id:
        return Response(status=400)

    attempt = database.session.get(EvaluationAttempt, attempt_id)
    if (
        attempt is None
        or attempt.user_id != current_user.usuario
        or attempt.evaluation_id != eval_obj.id
        or attempt.submitted_at is not None
    ):
        # A submitted attempt is closed: a late autosave must not change an answer
        # behind a score that has already been calculated.
        return Response(status=409)

    deadline = _deadline(attempt, eval_obj)
    if deadline and _now() >= deadline:
        # Past the deadline nothing more is accepted; the next GET grades it.
        return Response(status=409)

    question_id = request.form.get("question_id")
    paper = exam_forms.form_questions(exam_forms.load_form(attempt.form_json), eval_obj)
    question = next((q for q in paper if q.id == question_id), None)
    if question is None:
        return Response(status=400)

    selected = _resolve_option_ids(question, request.form.getlist("option_id"))
    _record_answer(attempt, question_id, selected)
    database.session.commit()
    return Response(status=204)


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

    eval_obj = attempt.evaluation
    paper = exam_forms.form_questions(exam_forms.load_form(attempt.form_json), eval_obj)

    # Per-domain scoring answers the only question a failed sitting raises: what do I
    # go and study. It reads from the answers actually given, so a blank counts against
    # its domain exactly as a wrong answer does.
    graded = _graded_paper(attempt, eval_obj)
    domains = exam_forms.domain_breakdown(graded)

    scaled = None
    if eval_obj.scaled_cut and attempt.scaled_score is not None:
        total = len(paper)
        scaled = {
            "score": attempt.scaled_score,
            "cut": eval_obj.scaled_cut,
            "minimum": exam_forms.SCALE_MIN,
            "maximum": exam_forms.SCALE_MAX,
            "raw": sum(1 for _question, correct in graded if correct),
            "total": total,
            "raw_needed": exam_forms.raw_needed(eval_obj.scaled_cut, total),
            # Where the marker and the cut sit on the rail, as percentages of its width.
            "at_percent": round(
                (attempt.scaled_score - exam_forms.SCALE_MIN)
                / (exam_forms.SCALE_MAX - exam_forms.SCALE_MIN) * 100, 2),
            "cut_percent": round(
                (eval_obj.scaled_cut - exam_forms.SCALE_MIN)
                / (exam_forms.SCALE_MAX - exam_forms.SCALE_MIN) * 100, 2),
        }

    return render_template(
        get_evaluation_result_template(),
        attempt=attempt,
        paper=paper,
        domains=domains,
        scaled=scaled,
        # A domain below this is called thin and is what the report tells them to work.
        thin_threshold=0.70,
    )


def _certification_practice(usuario: str, certification_key: str | None = None):
    """Every labelled question, grouped by certification and then by domain.

    Practice is its own area of the product, not a feature of a course (Max,
    2026-08-09: "practice tests are their own domain ... outside of courses"). Keying
    it by course was actively wrong: CCA-F alone carries questions for two credentials,
    so a member drilling "their" domains saw 12 of them — the 5 for Architect
    Foundations mashed together with the 7 for Architect Professional.

    De-duplicated by question text for the same reason the course view was: the same
    bank item is seeded into a section quiz and again into that course's mock exam.
    """
    query = database.select(Question).filter(Question.certification_key.isnot(None))
    if certification_key:
        query = query.filter(Question.certification_key == certification_key)
    rows = list(
        database.session.execute(
            query.options(selectinload(Question.options)).order_by(Question.order, Question.id)
        ).scalars()
    )

    seen: set = set()
    questions = []
    for question in rows:
        identity = (question.certification_key, question.text)
        if identity in seen:
            continue
        seen.add(identity)
        questions.append(question)

    latest = _latest_answers(usuario)

    certifications: dict = {}
    for question in questions:
        cert = certifications.setdefault(
            question.certification_key,
            {
                "key": question.certification_key,
                "name": question.certification_name or question.certification_key,
                "domains": {},
                "total": 0,
            },
        )
        cert["total"] += 1
        domain = cert["domains"].setdefault(
            question.domain_key or "unlabelled",
            {
                "key": question.domain_key or "unlabelled",
                "name": question.domain_name or question.domain_key or "Unlabelled",
                "questions": [],
                "seen": 0,
                "correct": 0,
            },
        )
        domain["questions"].append(question)
        chosen = latest.get(question.text)
        if chosen is not None:
            domain["seen"] += 1
            if chosen == sorted(option.text for option in question.options if option.is_correct):
                domain["correct"] += 1
    return certifications


def _latest_answers(usuario: str) -> dict:
    """The member's most recent answer to each question, keyed by question TEXT.

    Text rather than id because the same bank item exists as several rows, and each
    copy owns its own QuestionOption rows — so comparing ids across copies could only
    ever say "wrong". Values are sorted option TEXT for the same reason.
    """
    latest: dict = {}
    attempts = list(
        database.session.execute(
            database.select(EvaluationAttempt)
            .options(
                selectinload(EvaluationAttempt.answers)
                .selectinload(Answer.question)
                .selectinload(Question.options)
            )
            .filter_by(user_id=usuario)
            .order_by(EvaluationAttempt.started_at)
        ).scalars()
    )
    for attempt in attempts:
        for answer in attempt.answers:
            if not answer.selected_option_ids or answer.question is None:
                continue
            chosen = set(json.loads(answer.selected_option_ids))
            latest[answer.question.text] = sorted(
                option.text for option in answer.question.options if option.id in chosen
            )
    return latest


def _certification_sittings(usuario: str) -> dict:
    """The full-length mock for each certification, with this member's history.

    The practice area is keyed by certification but an Evaluation belongs to a
    course section, so the link between them is the questions: a mock is the drawn
    evaluation whose questions carry that certification. Found by lookup rather
    than stored, because a course can carry more than one credential and the
    certification already lives on the question.
    """
    sittings: dict = {}
    # Every timed exam-shaped evaluation, not only the drawn mocks: an authored
    # full-length paper (Purcell's associate set, Rick's three architect sets) is a
    # sitting a candidate can take, and the landing has to list it as one.
    # Course-free sittings only. A course's own mock is coursework: it sits inside
    # the course, counts toward it, and can issue a certificate. Listing both here
    # showed a credential twice and made the menu look padded.
    exams = database.session.execute(
        database.select(Evaluation)
        .filter(Evaluation.section_id.is_(None))
        .filter(database.or_(Evaluation.draw_size.isnot(None), Evaluation.scaled_cut.isnot(None)))
    ).scalars().all()

    for evaluation_obj in exams:
        key = evaluation_obj.certification_key
        if not key:
            # Fall back to the pool's own labelling for a sitting seeded before the
            # column existed. A pool spanning two credentials speaks for neither.
            keys = {q.certification_key for q in evaluation_obj.questions if q.certification_key}
            if len(keys) != 1:
                continue
            key = keys.pop()
        blueprint = {}
        if evaluation_obj.blueprint_json:
            try:
                blueprint = json.loads(evaluation_obj.blueprint_json)
            except (ValueError, TypeError):
                blueprint = {}

        names = {
            question.domain_key: question.domain_name
            for question in evaluation_obj.questions
            if question.domain_key
        }
        targets = exam_forms.domain_targets(
            {d: w for d, w in blueprint.items() if d in names}, evaluation_obj.draw_size or 0
        )
        heaviest = max(blueprint.values()) if blueprint else 1

        attempts = database.session.execute(
            database.select(EvaluationAttempt)
            .filter_by(evaluation_id=evaluation_obj.id, user_id=usuario)
            .filter(EvaluationAttempt.submitted_at.isnot(None))
        ).scalars().all()
        scored = [a for a in attempts if a.scaled_score is not None]
        best = max((a.scaled_score for a in scored), default=None)

        entry = {
            "evaluation": evaluation_obj,
            "title": evaluation_obj.title,
            # A drawn mock composes a new paper per attempt; an authored form is the
            # paper its author wrote and is served whole.
            "drawn": bool(evaluation_obj.draw_size),
            # NOT "items": Jinja resolves `sit.items` to dict.items, the bound method,
            # so every place the paper length was printed came out blank.
            "length": evaluation_obj.draw_size,
            "minutes": evaluation_obj.time_limit_minutes,
            "cut": evaluation_obj.scaled_cut,
            "pool": len(evaluation_obj.questions),
            "raw_needed": exam_forms.raw_needed(evaluation_obj.scaled_cut, evaluation_obj.draw_size)
            if evaluation_obj.scaled_cut and evaluation_obj.draw_size else None,
            "blueprint": [
                {
                    "key": domain,
                    "name": names.get(domain, domain),
                    "weight": weight,
                    "draw": targets.get(domain, 0),
                    # Bar width relative to the heaviest domain, so the table reads
                    # as a shape rather than five near-identical bars.
                    "bar": round(weight / heaviest * 100),
                }
                for domain, weight in sorted(blueprint.items(), key=lambda kv: -kv[1])
            ],
            "attempts": len(attempts),
            "best": best,
            "cleared": bool(best is not None and evaluation_obj.scaled_cut and best >= evaluation_obj.scaled_cut),
            "open_attempt": _open_attempt(evaluation_obj.id, usuario),
        }
        if entry["drawn"]:
            entry["length"] = evaluation_obj.draw_size
        else:
            # An authored form's length is its own question count, not a draw size.
            entry["length"] = len(evaluation_obj.questions)
            entry["raw_needed"] = (
                exam_forms.raw_needed(evaluation_obj.scaled_cut, entry["length"])
                if evaluation_obj.scaled_cut else None
            )

        # One sitting per credential. The grouping this used to do existed to list
        # several papers per certification; the fixed extra papers were removed on
        # 2026-09-02 because the per-attempt draw makes a better one every time.
        # A drawn sitting always wins over an authored one if both somehow exist.
        if key not in sittings or (entry["drawn"] and not sittings[key]["drawn"]):
            sittings[key] = entry
    return sittings


@evaluation.route("/practice")
@evaluation.route("/practice/<certification_key>")
@evaluation.route("/practice/<certification_key>/<domain_key>")
@login_required
@perfil_requerido("student")
def practice(certification_key: str | None = None, domain_key: str | None = None) -> str | Response:
    """Practice by certification, then by domain. Outside courses entirely.

    Records nothing: a drill is rehearsal, and the exam surface stays the only place a
    score is earned. No course enrollment is required — practice is its own area, open
    to any signed-in member.
    """
    certifications = _certification_practice(current_user.usuario)

    selected_cert = None
    if certification_key:
        selected_cert = certifications.get(certification_key)
        if selected_cert is None:
            abort(404)
    # With no certification named this is the MENU: every certification and every
    # sitting it offers, side by side. Defaulting to one of them hid the other three
    # behind a click and made a four-credential product look like a one-exam app.

    selected_domain = None
    if domain_key:
        selected_domain = selected_cert["domains"].get(domain_key)
        if selected_domain is None:
            abort(404)

    return render_template(
        get_practice_template(),
        certifications=sorted(certifications.values(), key=lambda c: c["name"]),
        selected_cert=selected_cert,
        selected_domain=selected_domain,
        domains=sorted(selected_cert["domains"].values(), key=lambda d: d["name"]) if selected_cert else [],
        questions=selected_domain["questions"] if selected_domain else [],
        sittings=_certification_sittings(current_user.usuario),
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
        return redirect(_back_from_evaluation(eval_obj))

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
        return redirect(_back_from_evaluation(eval_obj))

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
            return redirect(_back_from_evaluation(eval_obj))

        reopen_request = EvaluationReopenRequest(
            user_id=current_user.usuario, evaluation_id=evaluation_id, justification_text=form.justification_text.data
        )

        database.session.add(reopen_request)
        database.session.commit()

        flash(REOPEN_REQUEST_SUBMITTED, "success")
        return redirect(_back_from_evaluation(eval_obj))

    return render_template("evaluations/request_reopen.html", evaluation=eval_obj, form=form)


# Instructor routes will be added to the instructor profile blueprint
