# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""The practice route, exercised through the URL rather than the helper.

Every guard on domain practice was previously tested by calling the private gatherer
directly. That proves the gatherer and nothing about the route: the decorators, the
403, the 404 on an unknown domain and the rendered page were all unverified. A local
audit called this out, and it is the kind of gap where a decorator gets dropped in a
refactor and no test notices.
"""

import pytest

from now_lms.auth import proteger_passwd
from now_lms.db import Curso, CursoSeccion, EstudianteCurso, Evaluation, Question, QuestionOption, Usuario, database

COURSE = "PRT-1"
PASSWORD = "practice-route-pass"


def _user(usuario, tipo="student"):
    existing = database.session.execute(database.select(Usuario).filter_by(usuario=usuario)).scalars().first()
    if existing is not None:
        return existing
    user = Usuario(
        usuario=usuario,
        acceso=proteger_passwd(PASSWORD),
        nombre="Route",
        apellido="Tester",
        correo_electronico=f"{usuario}@example.invalid",
        tipo=tipo,
        activo=True,
        correo_electronico_verificado=True,
    )
    database.session.add(user)
    database.session.commit()
    return user


@pytest.fixture
def seeded_course(app):
    """One course, one section, one evaluation, two questions in two domains."""
    with app.app_context():
        if database.session.execute(database.select(Curso).filter_by(codigo=COURSE)).scalars().first() is None:
            database.session.add(
                Curso(
                    nombre="Practice route course",
                    codigo=COURSE,
                    descripcion_corta="short",
                    descripcion="long",
                    estado="open",
                    publico=False,
                    modalidad="self_paced",
                    nivel=1,
                    duracion=1,
                    pagado=False,
                    auditable=False,
                    certificado=False,
                )
            )
            database.session.commit()

            seccion = CursoSeccion(curso=COURSE, nombre="Section", descripcion="d", indice=1, estado=True)
            database.session.add(seccion)
            database.session.commit()

            evaluation = Evaluation(
                section_id=seccion.id,
                title="Practice quiz",
                description="d",
                is_exam=False,
                passing_score=72.0,
                max_attempts=None,
            )
            database.session.add(evaluation)
            database.session.commit()

            for index, (text, key, name) in enumerate(
                [
                    ("Alpha domain question.", "d-alpha", "Alpha Domain"),
                    ("Beta domain question.", "d-beta", "Beta Domain"),
                ],
                start=1,
            ):
                question = Question(
                    evaluation_id=evaluation.id,
                    type="multiple",
                    text=text,
                    explanation="Because of the documented behaviour.",
                    order=index,
                    domain_key=key,
                    domain_name=name,
                )
                database.session.add(question)
                database.session.commit()
                database.session.add(QuestionOption(question_id=question.id, text="right", is_correct=True))
                database.session.add(QuestionOption(question_id=question.id, text="wrong", is_correct=False))
                database.session.commit()
        yield


def _login(client, usuario):
    return client.post("/user/login", data={"usuario": usuario, "acceso": PASSWORD}, follow_redirects=False)


def _enroll(app, usuario, vigente=True):
    with app.app_context():
        _user(usuario)
        existing = (
            database.session.execute(
                database.select(EstudianteCurso).filter_by(curso=COURSE, usuario=usuario)
            )
            .scalars()
            .first()
        )
        if existing is None:
            database.session.add(EstudianteCurso(curso=COURSE, usuario=usuario, vigente=vigente))
            database.session.commit()


def test_an_enrolled_member_sees_the_domain_chooser(app, client, seeded_course):
    _enroll(app, "route-enrolled")
    _login(client, "route-enrolled")

    response = client.get(f"/course/{COURSE}/practice")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Alpha Domain" in body
    assert "Beta Domain" in body


def test_a_domain_page_shows_only_that_domain(app, client, seeded_course):
    """The rendered page, not just the gatherer's return value."""
    _enroll(app, "route-drill")
    _login(client, "route-drill")

    response = client.get(f"/course/{COURSE}/practice?domain=d-alpha")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Alpha domain question." in body
    assert "Beta domain question." not in body, "a drill must not leak another domain's items"


def test_a_member_who_is_not_enrolled_is_refused(app, client, seeded_course):
    with app.app_context():
        _user("route-outsider")
    _login(client, "route-outsider")

    assert client.get(f"/course/{COURSE}/practice").status_code == 403


def test_an_inactive_enrollment_is_refused(app, client, seeded_course):
    """`can_user_access_evaluation` never checks `vigente`; the route must."""
    _enroll(app, "route-withdrawn", vigente=False)
    _login(client, "route-withdrawn")

    assert client.get(f"/course/{COURSE}/practice").status_code == 403


def test_an_unknown_domain_is_a_404_not_an_empty_page(app, client, seeded_course):
    _enroll(app, "route-404")
    _login(client, "route-404")

    assert client.get(f"/course/{COURSE}/practice?domain=does-not-exist").status_code == 404


def test_an_anonymous_visitor_is_sent_to_login(client, seeded_course):
    response = client.get(f"/course/{COURSE}/practice", follow_redirects=False)
    assert response.status_code in (302, 401), "the route is behind login_required"
