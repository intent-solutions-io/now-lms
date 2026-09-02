# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Behavioural contracts for the exam sitting.

Every test here goes through a route, a template, or a real second connection.
None of them asserts on the text of the implementation, and none of them calls an
internal helper where the defect lives on the way in to that helper: calling
``_record_answer(["Verdadero"])`` directly skips ``_resolve_option_ids``, which is
exactly where the boolean defect is.

A race is two threads with their own sessions, not one function called twice.
"""

import json
import sys
import threading
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex

from now_lms.auth import proteger_passwd
from now_lms.db import (
    Answer,
    Curso,
    CursoSeccion,
    EstudianteCurso,
    Evaluation,
    EvaluationAttempt,
    Question,
    QuestionOption,
    Style,
    Usuario,
    database,
)
from now_lms.vistas import evaluations, exam_forms
from now_lms.vistas.evaluations import _now

STUDENT = "contract_student"
PASSWORD = "Contract-pass-1"


@pytest.fixture
def sitting(app):
    """A student enrolled on a timed, drawn, scaled evaluation with four questions.

    The theme is pinned because the templates under test are the ones that ship:
    ``get_evaluation_result_template()`` resolves through the active theme, and a
    fresh test database has none, so an unpinned test grades the stock template
    rather than the one a learner sees.
    """
    with app.app_context():
        style = database.session.execute(database.select(Style)).scalars().first()
        if style is None:
            style = Style()
            database.session.add(style)
        style.theme = "intent_learn"

        database.session.add(
            Usuario(
                usuario=STUDENT, acceso=proteger_passwd(PASSWORD), nombre="Contract",
                apellido="Student", correo_electronico="contract@example.com",
                tipo="student", activo=True, correo_electronico_verificado=True,
            )
        )
        database.session.add(
            Curso(
                codigo="CONTRACT1", nombre="Contract", descripcion="d", descripcion_corta="d",
                estado="open", publico=True, modalidad="self_paced", nivel=1, duracion=1,
                pagado=False, certificado=False, precio=0,
            )
        )
        database.session.commit()

        database.session.add(EstudianteCurso(curso="CONTRACT1", usuario=STUDENT, vigente=True))
        seccion = CursoSeccion(
            curso="CONTRACT1", nombre="S", descripcion="d", indice=1, estado=True
        )
        database.session.add(seccion)
        database.session.commit()

        evaluation = Evaluation(
            section_id=seccion.id, title="Contract exam", description="d", is_exam=True,
            passing_score=50.0, time_limit_minutes=120, draw_size=4, scaled_cut=720,
            max_attempts=None,
        )
        database.session.add(evaluation)
        database.session.commit()

        for index in range(4):
            question = Question(
                evaluation_id=evaluation.id, type="multiple",
                text=f"CONTRACT QUESTION {index}", order=index + 1,
            )
            database.session.add(question)
            database.session.commit()
            for position in range(4):
                database.session.add(
                    QuestionOption(
                        question_id=question.id,
                        text=f"CONTRACT OPTION {index}-{position}",
                        is_correct=(position == 0),
                    )
                )
            database.session.commit()

        yield {"evaluation_id": evaluation.id}


def _login(client):
    client.post(
        "/user/login", data={"usuario": STUDENT, "acceso": PASSWORD}, follow_redirects=True
    )
    return client


def _seed_attempt(evaluation_id, started_at=None):
    """An attempt with a drawn, frozen paper, stamped with the application's clock.

    ``_now()``, never ``datetime.now()``: the application stores naive UTC, so a
    fixture using local time makes a fresh attempt look hours old and silently
    exercises the expired branch instead of the open one.
    """
    evaluation = database.session.get(Evaluation, evaluation_id)
    attempt = EvaluationAttempt(
        evaluation_id=evaluation_id, user_id=STUDENT, started_at=started_at or _now()
    )
    attempt.form_json = exam_forms.dump_form(
        exam_forms.build_form(list(evaluation.questions), evaluation, None)
    )
    database.session.add(attempt)
    database.session.commit()
    return attempt


def _paper(attempt):
    return exam_forms.load_form(attempt.form_json)["items"]


def _key(question_id):
    """The correct option's id.

    NOT ``item["option_ids"][0]``: the paper shuffles the options, so the first one
    is whichever landed there. Answering with it makes a "perfect paper" fixture
    that is perfect only when the shuffle cooperates.
    """
    return [
        o.id for o in database.session.get(Question, question_id).options if o.is_correct
    ]


def _wrong(question_id):
    return next(
        o.id for o in database.session.get(Question, question_id).options if not o.is_correct
    )


# --------------------------------------------------------------- the result route


def test_an_open_attempt_does_not_expose_the_key_through_the_result_route(app, sitting):
    """``evaluation_result`` checks ownership and nothing else, so a candidate mid
    sitting can open their own attempt's result URL in a second tab and read the key
    to the paper in front of them. Ownership is the wrong question: it IS theirs."""
    with app.app_context():
        attempt_id = _seed_attempt(sitting["evaluation_id"]).id

    client = _login(app.test_client())
    response = client.get(f"/evaluation/attempt/{attempt_id}/result")

    assert response.status_code in (302, 403, 404), (
        f"an open attempt rendered its own result page ({response.status_code})"
    )
    assert b"CONTRACT OPTION" not in (response.data or b""), "the result page leaked the options"


def test_an_expired_attempt_is_closed_and_graded_before_its_result_renders(app, sitting):
    """An expired attempt reaching the result route ungraded renders a score of None
    over a sitting that was never closed, and leaves it open forever."""
    with app.app_context():
        evaluation = database.session.get(Evaluation, sitting["evaluation_id"])
        started = _now() - timedelta(minutes=evaluation.time_limit_minutes + 5)
        attempt_id = _seed_attempt(sitting["evaluation_id"], started).id

    client = _login(app.test_client())
    client.get(f"/evaluation/attempt/{attempt_id}/result", follow_redirects=True)

    with app.app_context():
        graded = database.session.get(EvaluationAttempt, attempt_id)
        assert graded.submitted_at is not None, "an expired attempt must be closed"
        assert graded.score is not None, "an expired attempt must carry a score"


# --------------------------------------------------------------- the transition


def test_two_tabs_of_one_sitting_do_not_become_two_attempts(app, sitting):
    """Both tabs render the same open attempt and both submit it, which is what a
    double click and a restored browser session both look like.

    On the unconditional path the second submit finds no open attempt, opens a fresh
    one, and the candidate has spent two attempts on one sitting.
    """
    with app.app_context():
        attempt_id = _seed_attempt(sitting["evaluation_id"]).id

    url = f"/evaluation/{sitting['evaluation_id']}/take"
    tab_a, tab_b = _login(app.test_client()), _login(app.test_client())
    tab_a.get(url)
    tab_b.get(url)
    tab_a.post(url, data={"attempt_id": attempt_id})
    tab_b.post(url, data={"attempt_id": attempt_id})

    with app.app_context():
        attempts = database.session.execute(
            database.select(EvaluationAttempt).filter_by(
                evaluation_id=sitting["evaluation_id"], user_id=STUDENT
            )
        ).scalars().all()
        assert len(attempts) == 1, f"one sitting became {len(attempts)} attempts"


def _pre_lock_boundary():
    """The point in the submit path before which no lock is held, on whichever
    architecture is on disk right now.

    On a design with a real row lock, that is ``_lock_open_attempt`` itself:
    pausing there means the loser is parked before its own ``FOR UPDATE`` SELECT
    even runs, so it holds nothing while it waits. On a design with no separate
    locking step — nothing takes a row lock ahead of the write — the earliest
    write-adjacent point is ``_save_question_answers``, and pausing there is
    equally lock-free because there is no lock anywhere in this path to hold.

    Resolved by name, not imported, for the same reason as ``_finalisation_boundary``:
    the fix may change which function owns this, and the contract is about WHERE
    the pause sits relative to any lock, not the exact function name.
    """
    for name in ("_lock_open_attempt", "_save_question_answers"):
        if hasattr(evaluations, name):
            return name
    raise AssertionError("no pre-lock boundary on the evaluations module")


def _finalisation_boundary():
    """The production function both a submit and the clock call to close a sitting.

    Resolved by name rather than imported, because the fix may rename it: what the
    contract requires is that ONE named function owns the transition, so a wrapper
    can be placed at exactly the point where the answers are flushed and the grade
    has not been written.
    """
    for name in ("_finalize_attempt", "_grade_attempt"):
        if hasattr(evaluations, name):
            return name
    raise AssertionError("no single finalisation entry point on the evaluations module")


def test_two_concurrent_submits_agree_on_the_answers_the_score_was_computed_from(app, sitting):
    """A controlled overlap pinned at the production boundary.

    Holding both requests AT the finalisation call cannot be done: both have written
    to the same attempt row by then, so the second blocks on the first's row lock
    (Postgres) or on the writer lock (SQLite) and the barrier deadlocks. The DB
    prevents that interleaving, so a test that waits for it only ever times out.

    The gate used to sit inside ``_save_question_answers``, which the submit path
    only reaches AFTER ``_lock_open_attempt`` has already taken the row's ``FOR
    UPDATE`` lock. On SQLite that lock is a no-op and the gate looked fine; on
    PostgreSQL and MySQL the paused loser was holding a real lock the winner's own
    ``_lock_open_attempt`` call then blocked on, so the winner could never reach the
    point that releases ``winner_done`` — measured at 61 seconds against a real
    PostgreSQL server for what should be a sub-second test, resolved only because
    the paused thread's own assertion timeout (60s) fired first, tore its request
    down, and let the transaction roll back and the lock go with it. That is a
    timeout racing an assertion, not the interleaving this test claims to build.

    The interleaving that IS reachable, and the one the defect lives in: both
    requests load the same open attempt and prepare DIFFERENT answers, the winner
    writes and finalises to completion, and only then does the loser ask for the
    lock, find the attempt already closed, and be turned away. The loser must not
    leave its answers standing behind the winner's grade.

    The gate now wraps ``_lock_open_attempt`` itself and pauses the loser BEFORE it
    calls through to the real lock-and-read, so the loser holds nothing — no row
    lock, nothing written — for the whole time it waits on the winner.
    """
    with app.app_context():
        attempt_id = _seed_attempt(sitting["evaluation_id"]).id
        items = _paper(database.session.get(EvaluationAttempt, attempt_id))
        right = {i["question_id"]: _key(i["question_id"])[0] for i in items}
        wrong = {i["question_id"]: _wrong(i["question_id"]) for i in items}

    url = f"/evaluation/{sitting['evaluation_id']}/take"
    pre_lock = _pre_lock_boundary()
    boundary = _finalisation_boundary()
    original_pre_lock = getattr(evaluations, pre_lock)
    original_final = getattr(evaluations, boundary)

    loser = {}
    loaded, finalised, errors = [], [], []
    winner_done = threading.Event()

    def _as_attempt_id(first_arg):
        # `_lock_open_attempt` takes the id itself; `_save_question_answers` takes
        # the attempt row. Either way this is the id the assertions key on.
        return first_arg if isinstance(first_arg, str) else first_arg.id

    def gate_the_loser(first_arg, *args, **kwargs):
        loaded.append(_as_attempt_id(first_arg))
        if threading.get_ident() == loser.get("id"):
            # Both requests are now at the pre-lock boundary; the loser has asked
            # for nothing yet — no SELECT ... FOR UPDATE issued, nothing written —
            # so it holds no lock of any kind while it waits for the winner to
            # finish and release the row.
            assert winner_done.wait(timeout=60), "the winning submit never finished"
        return original_pre_lock(first_arg, *args, **kwargs)

    def record_finalisation(attempt, *args, **kwargs):
        finalised.append((attempt.id, json.loads(attempt.answers_json or "{}")))
        return original_final(attempt, *args, **kwargs)

    setattr(evaluations, pre_lock, gate_the_loser)
    setattr(evaluations, boundary, record_finalisation)

    def submit(answers, is_loser):
        try:
            client = _login(app.test_client())
            client.get(url)
            if is_loser:
                loser["id"] = threading.get_ident()
            payload = {"attempt_id": attempt_id}
            payload.update({f"question_{qid}": oid for qid, oid in answers.items()})
            client.post(url, data=payload)
        except Exception as exc:  # noqa: BLE001 - a lost race is a result, not a test error
            errors.append(f"{type(exc).__name__}: {exc}")

    try:
        losing = threading.Thread(target=submit, args=(wrong, True))
        losing.start()
        # Let the loser reach the gate before the winner starts.
        for _ in range(600):
            if loser.get("id") and loaded:
                break
            threading.Event().wait(0.01)
        submit(right, False)
        winner_done.set()
        losing.join(timeout=90)
    finally:
        setattr(evaluations, pre_lock, original_pre_lock)
        setattr(evaluations, boundary, original_final)
        winner_done.set()

    assert len(loaded) == 2, f"both requests must load the sitting (got {loaded}, {errors})"
    assert loaded[0] == loaded[1] == attempt_id, "the requests worked on different attempts"
    assert len(finalised) >= 1, f"nothing reached {boundary} ({errors})"

    with app.app_context():
        attempts = database.session.execute(
            database.select(EvaluationAttempt).filter_by(
                evaluation_id=sitting["evaluation_id"], user_id=STUDENT
            )
        ).scalars().all()
        assert len(attempts) == 1, f"one sitting became {len(attempts)} attempts ({errors})"
        closed = attempts[0]
        assert closed.submitted_at is not None, f"never closed ({errors})"
        assert closed.score is not None, "closed but never graded"
        assert evaluations.calculate_score(closed) == pytest.approx(closed.score), (
            "the stored answers and the stored score disagree: the losing submit "
            f"left its answers standing behind the winner's grade ({closed.score} "
            f"stored, {evaluations.calculate_score(closed)} recomputed; {errors})"
        )


# --------------------------------------------------------------- the autosave


def test_two_overlapping_autosaves_from_different_threads_both_persist(app, sitting):
    """Two tabs answering two different questions at once, both through ``/answer``.

    No artificial gate is placed inside the read-modify-write: ``answers_json``
    lives on the SAME ``evaluation_attempt`` row that ``_lock_open_attempt`` locks
    before either request touches it, so on a real backend the database itself
    serialises the two requests — whichever's lock-acquiring SELECT executes first
    completes its full read-merge-write-commit before the second's own lock
    acquisition can even return. Gating INSIDE ``_record_answer`` (after the lock is
    already held) would pause one request while it holds that lock, which the other
    request's own lock attempt then blocks on — a self-inflicted deadlock that
    proves nothing about the production interleaving; see
    ``test_two_concurrent_submits_agree_on_the_answers_the_score_was_computed_from``
    for the same failure mode and its fix. Two real concurrent requests, timed only
    by the OS scheduler, are the actual contract: neither the winner nor the loser
    may lose the other's answer.
    """
    with app.app_context():
        attempt = _seed_attempt(sitting["evaluation_id"])
        attempt_id = attempt.id
        first, second = _paper(attempt)[0], _paper(attempt)[1]

    url = f"/evaluation/{sitting['evaluation_id']}/answer"
    take = f"/evaluation/{sitting['evaluation_id']}/take"
    errors = []

    def save(item):
        try:
            client = _login(app.test_client())
            client.get(take)
            client.post(url, data={
                "attempt_id": attempt_id,
                "question_id": item["question_id"],
                "option_id": item["option_ids"][0],
            })
        except Exception as exc:  # noqa: BLE001 - recorded so the assertion can report it
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(item,)) for item in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    with app.app_context():
        saved = evaluations._stored_selections(database.session.get(EvaluationAttempt, attempt_id))
        assert first["question_id"] in saved, f"the first tab's answer was lost ({errors})"
        assert second["question_id"] in saved, f"the second tab's answer was lost ({errors})"


def test_an_autosave_that_overlaps_the_submit_cannot_change_the_graded_answers(app, sitting):
    """The interleaving that matters: an autosave that is IN FLIGHT when the submit
    closes the attempt must not be able to change the graded answers afterwards.

    The autosave is paused at the same pre-lock boundary as
    ``test_two_concurrent_submits_agree_on_the_answers_the_score_was_computed_from``
    — before it calls ``_lock_open_attempt``, holding no lock of any kind — so the
    submit can acquire the row lock, write the fully-correct answers, grade, close
    and commit uncontended. Only then is the autosave released to make its own
    lock-acquiring call; by then the row is closed, so its own open-state check
    inside the SAME locked read must reject it. Pausing AFTER the lock is acquired
    (as an earlier version of this test did, gating ``_record_answer``) means the
    autosave is the one holding the lock while paused, and the submit's own
    ``_lock_open_attempt`` call then blocks on it — a self-inflicted deadlock, not
    the interleaving this test claims to build.
    """
    with app.app_context():
        attempt = _seed_attempt(sitting["evaluation_id"])
        attempt_id = attempt.id
        items = _paper(attempt)
        keys = {item["question_id"]: _key(item["question_id"]) for item in items}
        wrong_id = _wrong(items[0]["question_id"])

    answer_url = f"/evaluation/{sitting['evaluation_id']}/answer"
    take_url = f"/evaluation/{sitting['evaluation_id']}/take"

    client = _login(app.test_client())
    client.get(take_url)
    for item in items:
        client.post(answer_url, data={
            "attempt_id": attempt_id,
            "question_id": item["question_id"],
            "option_id": keys[item["question_id"]],
        })

    with app.app_context():
        stored = json.loads(database.session.get(EvaluationAttempt, attempt_id).answers_json)
        assert stored == keys, "fixture must start as a fully correct paper"

    pre_lock = _pre_lock_boundary()
    original_pre_lock = getattr(evaluations, pre_lock)
    autosave_thread = {}
    submit_done = threading.Event()

    def gate_the_autosave(first_arg, *args, **kwargs):
        if threading.get_ident() == autosave_thread.get("id"):
            # No lock held yet — the autosave has asked for nothing — so it can wait
            # here for as long as it takes the submit to finish and release the row.
            assert submit_done.wait(timeout=60), "the submit never finished"
        return original_pre_lock(first_arg, *args, **kwargs)

    setattr(evaluations, pre_lock, gate_the_autosave)
    errors = []
    responses = {}

    def late_autosave():
        try:
            autosave_thread["id"] = threading.get_ident()
            tab = _login(app.test_client())
            response = tab.post(answer_url, data={
                "attempt_id": attempt_id,
                "question_id": items[0]["question_id"],
                "option_id": wrong_id,
            })
            responses["status"] = response.status_code
        except Exception as exc:  # noqa: BLE001 - recorded so the assertion can report it
            errors.append(exc)

    try:
        thread = threading.Thread(target=late_autosave)
        thread.start()
        # Give the autosave a chance to reach the gate before the submit runs, same
        # as the concurrent-submit test's own synchronisation.
        for _ in range(600):
            if autosave_thread.get("id"):
                break
            threading.Event().wait(0.01)
        _login(app.test_client()).post(take_url, data={"attempt_id": attempt_id})
        submit_done.set()
        thread.join(timeout=90)
    finally:
        setattr(evaluations, pre_lock, original_pre_lock)
        submit_done.set()

    assert responses.get("status") == 409, (
        f"the late autosave should have been rejected as closed, got {responses} ({errors})"
    )

    with app.app_context():
        closed = database.session.get(EvaluationAttempt, attempt_id)
        assert closed.submitted_at is not None, "the submit did not close the attempt"
        stored_after = json.loads(closed.answers_json)
        assert stored_after == keys, (
            f"the late autosave changed a graded answer: {stored_after} != {keys} ({errors})"
        )
        assert evaluations.calculate_score(closed) == pytest.approx(closed.score), (
            "an autosave landed behind the grade: the stored score and the answers "
            f"it was computed from disagree ({closed.score} stored, "
            f"{evaluations.calculate_score(closed)} recomputed)"
        )


# --------------------------------------------------------------- the templates


def test_the_result_page_credits_a_deleted_question_the_way_the_score_did(app, sitting):
    """Renders the real result route after deleting a live Question.

    ``_graded_paper`` and ``calculate_score`` read the attempt's own answers, so they
    already survive this; the template does not. It looks each question's answer up
    in ``attempt.answers``, and those rows cascade away with the question, so the
    review reports Not answered for a question the score counted as correct.
    """
    with app.app_context():
        attempt = _seed_attempt(sitting["evaluation_id"])
        attempt_id = attempt.id
        items = _paper(attempt)
        keys = {item["question_id"]: _key(item["question_id"]) for item in items}

    answer_url = f"/evaluation/{sitting['evaluation_id']}/answer"
    take_url = f"/evaluation/{sitting['evaluation_id']}/take"
    client = _login(app.test_client())
    client.get(take_url)
    for item in items:
        client.post(answer_url, data={
            "attempt_id": attempt_id,
            "question_id": item["question_id"],
            "option_id": keys[item["question_id"]],
        })
    client.post(take_url, data={"attempt_id": attempt_id})

    with app.app_context():
        closed = database.session.get(EvaluationAttempt, attempt_id)
        assert closed.score == pytest.approx(100.0), "fixture must be a perfect paper"
        doomed = database.session.get(Question, items[0]["question_id"])
        doomed_text = doomed.text
        database.session.delete(doomed)
        database.session.commit()

    body = client.get(f"/evaluation/attempt/{attempt_id}/result").data.decode("utf8", "replace")

    assert doomed_text in body, "the frozen paper must still render the deleted question"
    block = body[body.index(doomed_text) - 3000 : body.index(doomed_text)]
    assert "Not answered" not in block, (
        "the score counted this answer, so the review must not report it unanswered"
    )


def _boolean_radio_values(rendered_html: str, question_id: str) -> dict[str, str]:
    """The ``value`` a real browser would post for each boolean radio, read off the
    actual rendered markup rather than assumed. Keyed by the tag's position (0, 1)
    since the caption text, not the value, is what a human reads."""
    marker = f'name="question_{question_id}"'
    values = {}
    cursor = 0
    index = 0
    while (found := rendered_html.find(marker, cursor)) != -1:
        tag = rendered_html[rendered_html.rfind("<input", 0, found) : rendered_html.find(">", found) + 1]
        vstart = tag.find('value="') + 7
        values[index] = tag[vstart : tag.find('"', vstart)]
        cursor = found + 1
        index += 1
    return values


def test_a_boolean_answer_saved_through_the_route_comes_back_checked(app, sitting):
    """The save path resolves Verdadero and Falso to a QuestionOption id, while the
    take template used to check the stored value against those literal words, so a
    boolean selection could never come back checked.

    Posting the word by hand, as this test used to, does not exercise that defect:
    once an option row exists the template renders ``value="{{ option.id }}"``
    (``take_evaluation.j2``), so a real browser posts a ULID, never the word. A test
    that hard-codes ``"Verdadero"`` as ``option_id`` is exercising the OTHER,
    intentionally-preserved path — a page rendered before an option row existed, or
    cached from before this change, that still has the word baked into its HTML.
    Both paths matter and both are exercised here, each with the value a browser on
    that page would actually send: the id for a freshly-rendered page, the literal
    word for one already open in a stale tab.
    """
    with app.app_context():
        evaluation = database.session.get(Evaluation, sitting["evaluation_id"])
        evaluation.draw_size = None
        evaluation.time_limit_minutes = None
        question = Question(
            evaluation_id=evaluation.id, type="boolean", text="BOOLEAN QUESTION", order=99
        )
        database.session.add(question)
        database.session.commit()
        for text in ("Verdadero", "Falso"):
            database.session.add(
                QuestionOption(
                    question_id=question.id, text=text, is_correct=(text == "Verdadero")
                )
            )
        database.session.commit()
        evaluation_id, question_id = evaluation.id, question.id
        true_option_id = database.session.execute(
            database.select(QuestionOption).filter_by(question_id=question_id, text="Verdadero")
        ).scalars().first().id
        false_option_id = database.session.execute(
            database.select(QuestionOption).filter_by(question_id=question_id, text="Falso")
        ).scalars().first().id

    take_url = f"/evaluation/{evaluation_id}/take"
    client = _login(app.test_client())
    initial = client.get(take_url).data.decode("utf8", "replace")
    marker = f'name="question_{question_id}"'
    assert marker in initial, "the boolean question did not render"

    # What a real browser on this freshly-rendered page would actually post: the
    # option ids read off the markup, not the words the fixture used to assume.
    rendered_values = set(_boolean_radio_values(initial, question_id).values())
    assert rendered_values == {true_option_id, false_option_id}, (
        f"the rendered radios do not post the option ids: {rendered_values}"
    )

    with app.app_context():
        attempt = database.session.execute(
            database.select(EvaluationAttempt).filter_by(
                evaluation_id=evaluation_id, user_id=STUDENT, submitted_at=None
            )
        ).scalars().first()
        attempt_id = attempt.id

    # The browser path: post the real rendered id.
    saved = client.post(f"/evaluation/{evaluation_id}/answer", data={
        "attempt_id": attempt_id, "question_id": question_id, "option_id": true_option_id,
    })
    assert saved.status_code == 204, f"the autosave was refused ({saved.status_code})"

    reloaded = client.get(take_url).data.decode("utf8", "replace")
    tags = {}
    cursor = 0
    while (found := reloaded.find(marker, cursor)) != -1:
        tag = reloaded[reloaded.rfind("<input", 0, found) : reloaded.find(">", found) + 1]
        for option_id in (true_option_id, false_option_id):
            if f'value="{option_id}"' in tag:
                tags[option_id] = tag
        cursor = found + 1

    assert set(tags) == {true_option_id, false_option_id}, (
        f"expected both radios, rendered {sorted(tags)}"
    )
    # Specifically the one that was chosen. "Some radio is checked" would pass if
    # the reload restored Falso.
    assert "checked" in tags[true_option_id], (
        f"the chosen answer came back unchecked: {tags[true_option_id]}"
    )
    assert "checked" not in tags[false_option_id], (
        "the answer that was not chosen came back checked"
    )

    # The legacy path: a stale tab, rendered before this change, still has the
    # literal word baked into its HTML and posts that instead of an id.
    switched = client.post(f"/evaluation/{evaluation_id}/answer", data={
        "attempt_id": attempt_id, "question_id": question_id, "option_id": "Falso",
    })
    assert switched.status_code == 204, f"the legacy-word autosave was refused ({switched.status_code})"

    reloaded_again = client.get(take_url).data.decode("utf8", "replace")
    tags_again = {}
    cursor = 0
    while (found := reloaded_again.find(marker, cursor)) != -1:
        tag = reloaded_again[reloaded_again.rfind("<input", 0, found) : reloaded_again.find(">", found) + 1]
        for option_id in (true_option_id, false_option_id):
            if f'value="{option_id}"' in tag:
                tags_again[option_id] = tag
        cursor = found + 1

    assert "checked" in tags_again[false_option_id], (
        f"the legacy-word answer did not switch the selection: {tags_again[false_option_id]}"
    )
    assert "checked" not in tags_again[true_option_id], (
        "the previous answer stayed checked after the legacy-word autosave replaced it"
    )


# --------------------------------------------------------------- the constraint


def test_the_model_index_alone_would_become_one_attempt_ever_on_mysql(app, sitting):
    """Why the model's own index cannot be handed to MySQL as-is.

    There is no MySQL on this machine, so the DDL the MySQL dialect actually emits
    for the model's own index is compiled and then RUN, and the resulting constraint
    is exercised with the sequence a returning candidate produces. This is a proxy,
    and it is named as one. Point ``DATABASE_URL`` at a MySQL server and
    ``test_one_open_attempt_per_candidate_and_a_second_sitting_after_finishing``
    below proves the corresponding claim against the real engine.

    A partial index declared only with ``sqlite_where`` and ``postgresql_where``
    still emits on MySQL, where MySQL silently drops the clauses it does not
    understand and keeps a plain unique over (evaluation_id, user_id): one attempt
    EVER, not one OPEN attempt. This is the defect this test proves EXISTS in the
    raw model index — which is exactly why the migration never creates this index
    on MySQL, and instead builds a database-generated discriminator column there
    (proven separately by ``test_the_migration_does_not_leave_mysql_without_the_
    open_attempt_rule``, which inspects what the migration actually emits).
    """
    index = next(
        i for i in EvaluationAttempt.__table__.indexes
        if i.name == "uq_evaluation_attempt_open_per_user"
    )
    mysql_ddl = str(CreateIndex(index).compile(dialect=mysql.dialect()))

    with app.app_context():
        # The same columns and the same uniqueness MySQL would be given, on a scratch
        # table so the suite's own schema is untouched.
        database.session.execute(database.text("DROP TABLE IF EXISTS mysql_shape"))
        database.session.execute(database.text(
            "CREATE TABLE mysql_shape (id INTEGER PRIMARY KEY, evaluation_id TEXT, "
            "user_id TEXT, submitted_at TEXT)"
        ))
        emitted = mysql_ddl.replace("evaluation_attempt", "mysql_shape").replace(
            "uq_evaluation_attempt_open_per_user", "mysql_shape_idx"
        )
        database.session.execute(database.text(emitted))

        database.session.execute(database.text(
            "INSERT INTO mysql_shape VALUES (1, 'e1', 'u1', '2026-01-01')"  # finished
        ))
        database.session.commit()

        try:
            database.session.execute(database.text(
                "INSERT INTO mysql_shape VALUES (2, 'e1', 'u1', NULL)"  # sitting again
            ))
            database.session.commit()
            second_sitting_allowed = True
        except IntegrityError:
            database.session.rollback()
            second_sitting_allowed = False

    assert not second_sitting_allowed, (
        "expected the raw model index to be UNSAFE on MySQL (one attempt ever), "
        "proving why the migration must not use it there — but the second sitting "
        f"was allowed, so this proxy no longer demonstrates the hazard: {mysql_ddl.strip()}"
    )


def test_one_open_attempt_per_candidate_and_a_second_sitting_after_finishing(app, sitting):
    """The semantics the index exists for, on whichever backend the suite is run
    against. Both halves have to hold: a second OPEN attempt is refused, and a
    second attempt after finishing the first is allowed."""
    with app.app_context():
        first_id = _seed_attempt(sitting["evaluation_id"]).id

        with pytest.raises(IntegrityError):
            database.session.add(
                EvaluationAttempt(
                    evaluation_id=sitting["evaluation_id"], user_id=STUDENT, started_at=_now()
                )
            )
            database.session.commit()
        database.session.rollback()

        first = database.session.get(EvaluationAttempt, first_id)
        first.submitted_at = _now()
        first.score = 50.0
        database.session.commit()

        again = EvaluationAttempt(
            evaluation_id=sitting["evaluation_id"], user_id=STUDENT, started_at=_now()
        )
        database.session.add(again)
        database.session.commit()
        assert again.id is not None, "a finished attempt must not block the next sitting"


# --------------------------------------------------------------- the seeder


def test_a_reset_does_not_delete_a_course_when_the_curriculum_cannot_be_built(app, tmp_path):
    """Through ``main()``, not around it.

    ``_require_content_dir`` only checks that ``banks/`` and ``lessons/`` exist, and
    ``main`` then wraps ``_build_specs()`` in ``except (FileNotFoundError, OSError):
    specs = None``. So a content directory that is present but incomplete — a partial
    clone, a checkout mid-pull, a bank renamed upstream — reaches ``--reset`` with
    nothing built, skips the preflight, and deletes the course it can no longer
    rebuild.

    The fixture curriculum is two empty directories. No bank and no answer key is
    written anywhere, here or in the repository: the point of the test is precisely
    that the banks are absent.
    """
    import scripts.seed_cca_courses as seed
    from now_lms.db import Curso, database

    content = tmp_path / "cca"
    (content / "banks").mkdir(parents=True)
    (content / "lessons").mkdir(parents=True)

    with app.app_context():
        database.session.add(
            Curso(
                codigo="CCA-A", nombre="Claude Foundations", descripcion="d",
                descripcion_corta="d", estado="open", publico=True, modalidad="self_paced",
                nivel=1, duracion=4, pagado=False, certificado=False, precio=0,
            )
        )
        database.session.commit()

    original = (seed.CONTENT_DIR, seed.BANKS_DIR, seed.LESSONS_DIR, list(sys.argv))
    seed.CONTENT_DIR, seed.BANKS_DIR, seed.LESSONS_DIR = (
        content, content / "banks", content / "lessons"
    )
    sys.argv = ["seed_cca_courses.py", "--reset=CCA-A"]
    try:
        with app.app_context():
            try:
                seed.main()
            except (SystemExit, FileNotFoundError, OSError, ValueError):
                pass  # refusing is the desired outcome; what matters is the course
    finally:
        seed.CONTENT_DIR, seed.BANKS_DIR, seed.LESSONS_DIR, sys.argv = (
            original[0], original[1], original[2], original[3]
        )

    with app.app_context():
        survived = database.session.execute(
            database.select(Curso).filter_by(codigo="CCA-A")
        ).scalars().first()
        assert survived is not None, (
            "--reset deleted the course while the curriculum it would be rebuilt "
            "from could not be loaded"
        )


def test_one_answer_per_attempt_and_question_on_a_fresh_install(app, sitting):
    """Two Answer rows for the same attempt and question, inserted against the
    schema ``create_all()` builds.

    A fresh install never runs the migrations: it creates the schema from the models
    and stamps the head. So a uniqueness rule that exists only in
    ``20260902_010000`` is absent on exactly the databases nobody migrated, and the
    read-then-insert in ``_record_answer`` is left with nothing to lose the race to.
    """
    with app.app_context():
        attempt = _seed_attempt(sitting["evaluation_id"])
        question_id = _paper(attempt)[0]["question_id"]

        database.session.add(
            Answer(attempt_id=attempt.id, question_id=question_id, selected_option_ids='["a"]')
        )
        database.session.commit()

        with pytest.raises(IntegrityError):
            database.session.add(
                Answer(
                    attempt_id=attempt.id, question_id=question_id, selected_option_ids='["b"]'
                )
            )
            database.session.commit()
        database.session.rollback()


def test_an_existing_undersized_pool_is_refused_rather_than_skipped(app, tmp_path):
    """A practice sitting that already exists, drawing 60 from a pool of one.

    ``_preflight`` validates the specs and the bank files on disk. Nothing validates
    the pools already in the database, and ``_seed_practice_sittings`` skips an
    existing sitting outright::

        if existing is not None:
            print(f"  [skip] {cert_key} practice sitting already exists")
            continue

    So on a seeded deployment an undersized sitting is never looked at again and goes
    on advertising a form it cannot fill, while the seed reports success. This is a
    different failure from the reset-before-build one: nothing is missing from disk
    and the seeder completes.

    ``_backfill_sitting_fields`` already refuses its own case, and does so by
    matching an evaluation's title against a built spec. The practice path has no
    such check.

    The fixture bank is obviously synthetic items written to a temporary directory,
    and it is deliberately HEALTHY — more than the draw needs — so that rejecting a
    thin source on disk cannot satisfy this test. No question bank or answer key is
    added to this repository.
    """
    import scripts.seed_cca_courses as seed
    from now_lms.db import (
        Curso,
        CursoRecurso,
        CursoSeccion,
        EstudianteCurso,
        Evaluation,
        EvaluationAttempt,
        Question,
        QuestionOption,
        database,
    )

    models = {
        "Curso": Curso, "CursoSeccion": CursoSeccion, "CursoRecurso": CursoRecurso,
        "Evaluation": Evaluation, "Question": Question, "QuestionOption": QuestionOption,
        "EstudianteCurso": EstudianteCurso, "EvaluationAttempt": EvaluationAttempt,
    }

    cert_key = "CCA-P"
    filename = "questions-architect-professional.json"
    _bank_key, cert_name = seed.BANK_CERTIFICATIONS[filename]
    sitting_spec = seed.SITTINGS[cert_key]
    title = f"Practice exam — {cert_name}"

    # A HEALTHY external source: enough valid items to fill the draw, so a fix that
    # merely rejects an undersized bank on disk cannot pass this. The one-question
    # pool already in the database has to be the only reason to refuse.
    blueprint = list(sitting_spec["blueprint"]) if sitting_spec.get("blueprint") else ["d1"]
    banks = tmp_path / "banks"
    banks.mkdir()
    (banks / filename).write_text(
        json.dumps({"questions": [
            {
                "id": f"SYNTHETIC-{n}",
                "question": f"SYNTHETIC CONTRACT ITEM {n}",
                "options": [f"option {n}-{p}" for p in range(4)],
                "answerIndex": 0,
                "domainKey": blueprint[n % len(blueprint)],
                "domainName": blueprint[n % len(blueprint)].replace("-", " ").title(),
                "rationale": "synthetic",
            }
            for n in range(sitting_spec["items"] + 5)
        ]}),
        encoding="utf-8",
    )

    with app.app_context():
        undersized = Evaluation(
            section_id=None, title=title, description="d", is_exam=True, passing_score=72.0,
            draw_size=sitting_spec["items"], time_limit_minutes=sitting_spec["minutes"],
            scaled_cut=sitting_spec["cut"], certification_key=cert_key,
        )
        database.session.add(undersized)
        database.session.commit()
        database.session.add(
            Question(
                evaluation_id=undersized.id, type="multiple", text="the only one", order=1
            )
        )
        database.session.commit()

        original = seed.BANKS_DIR
        seed.BANKS_DIR = banks
        try:
            with pytest.raises((SystemExit, ValueError)) as raised:
                seed._seed_practice_sittings(database, models)
        finally:
            seed.BANKS_DIR = original

        message = str(raised.value)
        assert cert_key in message or "Practice exam" in message, (
            f"the refusal must name the sitting or its certification, got: {message}"
        )
        # Observed against required, so an operator can act on it without going and
        # counting rows: 1 question stored, {items} needed by the draw.
        assert "1" in message and str(sitting_spec["items"]) in message, (
            "the refusal must report the pool it found and the draw it must fill, "
            f"got: {message}"
        )


def test_the_migration_does_not_leave_mysql_without_the_open_attempt_rule():
    """The migrated-database half of the MySQL problem.

    The model's index is the fresh-install path, and it compiles on MySQL to a
    global unique that forbids a second sitting. This is the other half: the
    migration guards its ``create_index`` with ``dialect in ("sqlite",
    "postgresql")``, so a database migrated on MySQL is left with NO one-open-attempt
    protection at all. Two open sittings there are simply allowed.

    Three shapes are rejected, because each of them would pass a looser check while
    leaving MySQL broken:

    * a unique over ``(evaluation_id, user_id)`` — blocks every second sitting;
    * a unique that includes the nullable ``submitted_at`` — MySQL treats each NULL
      as distinct, so two OPEN attempts still insert;
    * nothing at all, which is what the migration emits today.

    What is required is a discriminator the engine can actually key on: a column
    added for the purpose, a generated predicate, or a trigger.

    The operations the migration emits are recorded against a MySQL bind. Without a
    MySQL server this is a dialect proxy, not integration proof: what it shows is
    what the migration would ask MySQL to do, which is the thing that is currently
    empty.
    """
    import importlib.util

    path = (
        Path(__file__).resolve().parent.parent
        / "now_lms" / "migrations" / "20260902_010000_add_exam_form_columns.py"
    )
    spec = importlib.util.spec_from_file_location("exam_form_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    emitted = []

    class _Result:
        def scalar(self):
            return 0

    class _Bind:
        dialect = type("D", (), {"name": "mysql"})()

        def execute(self, statement, *a, **k):
            emitted.append(("execute", str(statement)))
            return _Result()

    class _Inspector:
        # Every table present, no index present: the state a database migrated up to
        # the previous revision is actually in.
        def get_table_names(self):
            return ["evaluation", "evaluation_attempt", "answer", "question"]

        def get_columns(self, table):
            return [{"name": "section_id", "nullable": True}]

        def get_indexes(self, table):
            return []

    class _Batch:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def alter_column(self, *a, **k):
            emitted.append(("alter_column", a, k))

    class _Op:
        def get_bind(self):
            return _Bind()

        def add_column(self, table, column):
            emitted.append(("add_column", table, column.name))

        def create_index(self, name, table, columns, **kwargs):
            emitted.append(("create_index", name, table, tuple(columns), kwargs))

        def execute(self, statement, *a, **k):
            emitted.append(("execute", str(statement)))

        def batch_alter_table(self, *a, **k):
            return _Batch()

    class _Sa:
        """Real SQLAlchemy, with the inspector pinned to the state above."""

        def __getattr__(self, name):
            import sqlalchemy

            return getattr(sqlalchemy, name)

        def inspect(self, bind):
            return _Inspector()

    original_op, original_sa = migration.op, migration.sa
    migration.op, migration.sa = _Op(), _Sa()
    try:
        migration.upgrade()
    finally:
        migration.op, migration.sa = original_op, original_sa

    added_columns = {op[2] for op in emitted if op[0] == "add_column" and op[1] == migration.ATTEMPT}
    attempt_ops = [op for op in emitted if migration.ATTEMPT in str(op)]
    unique_indexes = [
        op for op in attempt_ops
        if op[0] == "create_index" and op[2] == migration.ATTEMPT and op[4].get("unique")
    ]
    # A trigger or generated predicate is a legitimate MySQL answer too, and arrives
    # as raw SQL rather than as a create_index.
    raw_protection = [
        op for op in attempt_ops
        if op[0] == "execute"
        and any(word in op[1].upper() for word in ("TRIGGER", "GENERATED", "UNIQUE"))
    ]

    assert unique_indexes or raw_protection, (
        "migrating on MySQL emits nothing that stops a candidate holding two open "
        f"attempts at one evaluation. Operations touching {migration.ATTEMPT}: "
        f"{attempt_ops or 'none'}"
    )

    # Two shapes that look like protection and are not.
    for op in unique_indexes:
        columns = tuple(op[3])
        scoped = any("where" in str(key).lower() for key in op[4])
        assert not (columns == ("evaluation_id", "user_id") and not scoped), (
            "a unique index over (evaluation_id, user_id) with no open-attempt scope "
            "forbids every second sitting rather than every second OPEN sitting, so a "
            f"candidate who finishes one exam can never take another: {op}"
        )
        assert "submitted_at" not in columns, (
            "including a nullable submitted_at in the unique key is not protection on "
            "MySQL: it treats every NULL as distinct, so two open attempts still "
            f"insert cleanly. {op}"
        )

    # What is left has to actually discriminate: a column this migration adds for the
    # purpose (a key that is set while open and NULL once submitted), or a trigger or
    # generated predicate. A unique index over columns that already existed cannot
    # separate one open row from many completed ones.
    discriminating = [
        op for op in unique_indexes
        if set(op[3]) & added_columns or any("where" in str(key).lower() for key in op[4])
    ]
    assert discriminating or raw_protection, (
        "nothing emitted for MySQL distinguishes exactly one OPEN attempt while "
        "allowing unlimited completed ones. A MySQL-safe design needs a "
        "discriminator column, a generated predicate, or a trigger; columns added "
        f"by this migration: {sorted(added_columns) or 'none'}; unique indexes: "
        f"{unique_indexes or 'none'}"
    )
