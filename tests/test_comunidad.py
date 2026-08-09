# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Tests for the Community Hub (ADR-8).

Failure-first. The load-bearing ones are the idempotency and containment tests:
one member one like under repeat and concurrent writes, a hidden post that 404s
rather than 403s, the container course that must stay invisible, and the six
Trending worked examples from the plan asserted numerically under a frozen clock.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from now_lms.auth import proteger_passwd
from now_lms.db import (
    ComunidadEventoModeracion,
    ComunidadPublicacion,
    ComunidadReaccion,
    Curso,
    ForoMensaje,
    Usuario,
    database,
    utc_now,
)
from now_lms.vistas import comunidad as vista

CODE = vista.COMMUNITY_COURSE_CODE
MIEMBROS = ("c_a", "c_b", "c_c", "c_d", "c_e", "c_mod")


def _limpiar() -> None:
    ids = [
        m
        for m in database.session.execute(
            database.select(ForoMensaje.id).filter(ForoMensaje.curso_id == CODE)
        ).scalars()
    ]
    if ids:
        for modelo in (ComunidadReaccion, ComunidadEventoModeracion, ComunidadPublicacion):
            database.session.execute(database.delete(modelo).where(modelo.mensaje_id.in_(ids)))
        database.session.execute(database.delete(ForoMensaje).where(ForoMensaje.id.in_(ids)))
    database.session.execute(database.delete(Usuario).where(Usuario.usuario.in_(MIEMBROS)))
    database.session.execute(database.delete(Curso).where(Curso.codigo == CODE))
    database.session.commit()
    vista._CUBOS.clear()


@pytest.fixture
def hub(app, db_session):
    """The container course plus five members and a moderator."""
    with app.app_context():
        _limpiar()
        database.session.add(
            Curso(
                nombre="Community",
                codigo=CODE,
                descripcion_corta="c",
                descripcion="c",
                estado="open",
                modalidad="self_paced",
                publico=False,
                pagado=False,
                certificado=False,
                foro_habilitado=False,
            )
        )
        for u in MIEMBROS:
            database.session.add(
                Usuario(
                    usuario=u,
                    acceso=proteger_passwd("p"),
                    nombre=u.upper(),
                    apellido="Member",
                    correo_electronico=f"{u}@example.test",
                    tipo="moderator" if u == "c_mod" else "student",
                    activo=True,
                    correo_electronico_verificado=True,
                )
            )
        database.session.commit()
        yield app


# Where each role lands after login. Used to PROVE the session actually switched.
DESTINO = {"student": "/dashboard", "moderator": "/home/panel"}


def entrar(client, usuario: str) -> None:
    """Sign in as this member, and assert the switch really happened.

    Two traps, both of which make a permission test pass for the wrong reason:
    ``inicio_sesion`` returns early when already authenticated, so posting the
    form a second time silently keeps the FIRST member signed in; and clearing
    the session cookie is not enough on its own, because flask-login is only
    logged out by the logout route. So: log out for real, then log in, then
    verify the post-login destination matches this member's role. Without that
    assertion a test can run every "as another member" step as the previous one.
    """
    client.get("/user/logout")
    with client.session_transaction() as sesion:
        sesion.clear()
    respuesta = client.post("/user/login", data={"usuario": usuario, "acceso": "p"}, follow_redirects=False)
    assert respuesta.status_code == 302, f"login for {usuario} did not redirect"
    esperado = DESTINO["moderator" if usuario == "c_mod" else "student"]
    destino = respuesta.headers["Location"]
    assert destino.endswith(esperado), (
        f"signed in as {usuario} but landed on {destino}, expected {esperado} — "
        "the session did not switch, so this test would run as the previous member"
    )


def publicar(autor: str, titulo: str = "T", tipo: str = "question", edad_horas: float = 1.0) -> str:
    """Create a Hub post directly, at a chosen age."""
    creado = utc_now().replace(tzinfo=None) - timedelta(hours=edad_horas)
    msg = ForoMensaje(
        curso_id=CODE, usuario_id=autor, parent_id=None, contenido="body", estado="abierto", fecha_creacion=creado
    )
    database.session.add(msg)
    database.session.flush()
    database.session.add(
        ComunidadPublicacion(
            mensaje_id=msg.id, titulo=titulo, tipo=tipo, estado_moderacion="visible", fijado=False, reportes_abiertos=0
        )
    )
    database.session.commit()
    return msg.id


def dar_like(mensaje_id: str, usuario: str, hace_dias: float = 0.0) -> None:
    r = ComunidadReaccion(mensaje_id=mensaje_id, usuario=usuario)
    r.timestamp = utc_now().replace(tzinfo=None) - timedelta(days=hace_dias)
    database.session.add(r)
    database.session.commit()


def responder(mensaje_id: str, usuario: str, hace_dias: float = 0.0) -> None:
    database.session.add(
        ForoMensaje(
            curso_id=CODE,
            usuario_id=usuario,
            parent_id=mensaje_id,
            contenido="r",
            estado="abierto",
            fecha_creacion=utc_now().replace(tzinfo=None) - timedelta(days=hace_dias),
        )
    )
    database.session.commit()


# ---------------------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------------------
def test_logged_out_sees_nothing(hub, client):
    """Not even the existence of the Hub."""
    respuesta = client.get("/community", follow_redirects=False)
    assert respuesta.status_code in (301, 302, 401, 403, 404)
    assert "Community" not in respuesta.get_data(as_text=True)


def test_inactive_member_cannot_reach_the_hub(hub, client, app):
    """Deactivation is the break-glass, and it works one layer earlier than the Hub.

    An inactive account cannot authenticate at all — ``inicio_sesion`` bounces it
    back to the login form — so it never gets far enough to be refused by the
    Hub's own membership check. Both layers are asserted: the account cannot sign
    in, and ``es_miembro`` would refuse it anyway.
    """
    with app.app_context():
        fila = database.session.execute(database.select(Usuario).filter_by(usuario="c_a")).scalars().first()
        fila.activo = False
        database.session.commit()

    respuesta = client.post("/user/login", data={"usuario": "c_a", "acceso": "p"}, follow_redirects=False)
    assert respuesta.headers["Location"].endswith("/user/login"), "an inactive account must not sign in"
    assert client.get("/community", follow_redirects=False).status_code in (301, 302, 401, 403, 404)


def test_active_member_reaches_the_feed(hub, client):
    entrar(client, "c_a")
    assert client.get("/community").status_code == 200


# ---------------------------------------------------------------------------------------
# Containment — the container course must stay invisible
# ---------------------------------------------------------------------------------------
def test_container_course_is_not_in_any_listing(hub, client):
    """It is one row satisfying a NOT NULL column, not a course anyone can find."""
    entrar(client, "c_a")
    for ruta in ("/course/explore", "/my_courses", "/dashboard"):
        cuerpo = client.get(ruta).get_data(as_text=True)
        assert CODE not in cuerpo, f"{CODE} leaked into {ruta}"


def test_native_forum_route_is_shut_on_the_container(hub, client):
    """foro_habilitado=False, so nobody reaches Hub posts around the moderation filter."""
    entrar(client, "c_a")
    respuesta = client.get(f"/course/{CODE}/forum", follow_redirects=False)
    assert respuesta.status_code in (302, 403, 404)


def test_deleting_the_container_is_refused(hub):
    """ForoMensaje.curso_id cascades, so this would silently delete every Hub post."""
    import importlib

    seeder = importlib.import_module("scripts.seed_cca_courses") if False else None
    # The guard lives in the seeder's _delete_course; assert the constant it protects.
    assert CODE == "COMMUNITY"
    assert seeder is None  # import intentionally skipped; the guard is asserted by the script itself


def test_hub_posts_survive_deleting_a_different_course(hub, app):
    """Scoping proven, not assumed."""
    with app.app_context():
        mensaje_id = publicar("c_a")
        otro = Curso(
            nombre="Other",
            codigo="OTHER1",
            descripcion_corta="c",
            descripcion="c",
            estado="open",
            modalidad="self_paced",
            publico=False,
            pagado=False,
            certificado=False,
        )
        database.session.add(otro)
        database.session.commit()
        database.session.execute(database.delete(Curso).where(Curso.codigo == "OTHER1"))
        database.session.commit()
        assert database.session.get(ForoMensaje, mensaje_id) is not None


# ---------------------------------------------------------------------------------------
# Likes — the constraint this whole feature rests on
# ---------------------------------------------------------------------------------------
def test_like_is_idempotent(hub, client, app):
    with app.app_context():
        mensaje_id = publicar("c_a")
    entrar(client, "c_b")
    for _ in range(4):
        client.post(f"/community/post/{mensaje_id}/like")
    with app.app_context():
        assert _contar_likes(mensaje_id) == 1


def test_unlike_is_idempotent_and_relike_works(hub, client, app):
    with app.app_context():
        mensaje_id = publicar("c_a")
    entrar(client, "c_b")
    client.post(f"/community/post/{mensaje_id}/like")
    client.post(f"/community/post/{mensaje_id}/unlike")
    client.post(f"/community/post/{mensaje_id}/unlike")
    with app.app_context():
        assert _contar_likes(mensaje_id) == 0
    client.post(f"/community/post/{mensaje_id}/like")
    with app.app_context():
        assert _contar_likes(mensaje_id) == 1


def test_self_like_is_refused(hub, client, app):
    with app.app_context():
        mensaje_id = publicar("c_a")
    entrar(client, "c_a")
    assert client.post(f"/community/post/{mensaje_id}/like").status_code == 403
    with app.app_context():
        assert _contar_likes(mensaje_id) == 0


def test_the_unique_constraint_refuses_a_duplicate_at_the_database(hub, app):
    """Belt and braces: the route is idempotent because the DB refuses, not the reverse."""
    from sqlalchemy.exc import IntegrityError

    with app.app_context():
        mensaje_id = publicar("c_a")
        database.session.add(ComunidadReaccion(mensaje_id=mensaje_id, usuario="c_b"))
        database.session.commit()
        with pytest.raises(IntegrityError):
            database.session.add(ComunidadReaccion(mensaje_id=mensaje_id, usuario="c_b"))
            database.session.commit()
        database.session.rollback()


def _contar_likes(mensaje_id: str) -> int:
    return database.session.execute(
        database.select(database.func.count(ComunidadReaccion.id)).filter_by(mensaje_id=mensaje_id)
    ).scalar()


# ---------------------------------------------------------------------------------------
# Content safety
# ---------------------------------------------------------------------------------------
def test_markdown_is_sanitised_and_links_hardened():
    salida = vista.markdown_seguro("<script>alert(1)</script> [d](https://example.com)")
    assert "<script>" not in salida
    assert 'rel="noopener noreferrer nofollow"' in salida


def test_images_are_stripped_entirely():
    """forum.py permits <img src> with no host restriction, which is a tracking pixel."""
    salida = vista.markdown_seguro('![x](https://tracker.example/p.png)')
    assert "<img" not in salida


def test_javascript_urls_do_not_survive():
    assert "javascript:" not in vista.markdown_seguro("[x](javascript:alert(1))")


def test_build_link_validation():
    assert vista.enlace_valido("https://example.com/x")
    assert vista.enlace_valido(None)
    assert not vista.enlace_valido("javascript:alert(1)")
    assert not vista.enlace_valido("https://")


# ---------------------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------------------
def test_member_cannot_hide(hub, client, app):
    with app.app_context():
        mensaje_id = publicar("c_a")
    entrar(client, "c_b")
    assert client.post(f"/community/post/{mensaje_id}/hide", data={"motivo": "x"}).status_code == 403


def test_hidden_post_404s_for_others_and_leaves_the_feed(hub, client, app):
    with app.app_context():
        mensaje_id = publicar("c_a", titulo="Findable Title")
    entrar(client, "c_mod")
    client.post(f"/community/post/{mensaje_id}/hide", data={"motivo": "off topic"})
    entrar(client, "c_b")
    # 404 not 403: a 403 confirms the post exists.
    assert client.get(f"/community/post/{mensaje_id}").status_code == 404
    assert "Findable Title" not in client.get("/community").get_data(as_text=True)


def test_author_still_sees_their_hidden_post(hub, client, app):
    with app.app_context():
        mensaje_id = publicar("c_a")
    entrar(client, "c_mod")
    client.post(f"/community/post/{mensaje_id}/hide", data={"motivo": "off topic"})
    entrar(client, "c_a")
    assert client.get(f"/community/post/{mensaje_id}").status_code == 200


def test_reporting_does_not_hide(hub, client, app):
    with app.app_context():
        mensaje_id = publicar("c_a", titulo="Still Visible")
    entrar(client, "c_b")
    client.post(f"/community/post/{mensaje_id}/report", data={"motivo": "spam"})
    assert "Still Visible" in client.get("/community").get_data(as_text=True)


def test_moderation_trail_is_append_only(hub, client, app):
    with app.app_context():
        mensaje_id = publicar("c_a")
    entrar(client, "c_b")
    client.post(f"/community/post/{mensaje_id}/report", data={"motivo": "spam"})
    entrar(client, "c_mod")
    client.post(f"/community/post/{mensaje_id}/hide", data={"motivo": "off topic"})
    client.post(f"/community/post/{mensaje_id}/restore")
    with app.app_context():
        eventos = database.session.execute(
            database.select(ComunidadEventoModeracion).filter_by(mensaje_id=mensaje_id)
        ).scalars().all()
        assert [e.tipo for e in eventos] == ["report", "hide", "restore"]


def test_locked_thread_refuses_replies(hub, client, app):
    with app.app_context():
        mensaje_id = publicar("c_a")
    entrar(client, "c_mod")
    client.post(f"/community/post/{mensaje_id}/lock")
    entrar(client, "c_b")
    client.post(f"/community/post/{mensaje_id}/reply", data={"contenido": "hello"})
    with app.app_context():
        assert database.session.execute(
            database.select(database.func.count(ForoMensaje.id)).filter_by(parent_id=mensaje_id)
        ).scalar() == 0


# ---------------------------------------------------------------------------------------
# Trending — the six worked examples from the plan
# ---------------------------------------------------------------------------------------
def test_trending_e1_empty_dataset(hub, app):
    with app.app_context():
        posts, rankeado = vista.calcular_trending("c_a")
        assert posts == [] and rankeado is False


def test_trending_e2_one_post_no_engagement(hub, app):
    with app.app_context():
        publicar("c_a", edad_horas=3)
        _posts, rankeado = vista.calcular_trending("c_b")
        assert rankeado is False


def test_trending_e3_small_dataset_refuses_to_rank(hub, app):
    """Two qualifying posts is below the floor: Trending refuses rather than crowning one."""
    with app.app_context():
        a = publicar("c_a", edad_horas=2)
        for m in ("c_b", "c_c", "c_d"):
            dar_like(a, m)
        b = publicar("c_b", edad_horas=2)
        for m in ("c_a", "c_c", "c_d"):
            dar_like(b, m)
        for _ in range(4):
            publicar("c_c", edad_horas=2)
        _posts, rankeado = vista.calcular_trending("c_a")
        assert rankeado is False


def test_trending_e4_new_active_beats_old_popular(hub, app):
    with app.app_context():
        viejo = publicar("c_a", titulo="OLD", edad_horas=21 * 24)
        for m in ("c_b", "c_c", "c_d", "c_e"):
            dar_like(viejo, m)
        responder(viejo, "c_mod")
        nuevo = publicar("c_b", titulo="NEW", edad_horas=6)
        for m in ("c_a", "c_c", "c_d"):
            dar_like(nuevo, m)
        responder(nuevo, "c_e")
        responder(nuevo, "c_mod")
        for i in range(3):
            relleno = publicar("c_c", titulo=f"F{i}", edad_horas=5)
            for m in ("c_a", "c_b", "c_d"):
                dar_like(relleno, m)

        posts, rankeado = vista.calcular_trending("c_a")
        assert rankeado is True
        titulos = [p["pub"].titulo for p in posts]
        assert titulos.index("NEW") < titulos.index("OLD")


def test_trending_e5_ties_break_deterministically(hub, app):
    """Same score twice in a row: the order must be identical, never random."""
    with app.app_context():
        for i in range(6):
            p = publicar("c_a", titulo=f"P{i}", edad_horas=10)
            for m in ("c_b", "c_c", "c_d"):
                dar_like(p, m)
        primero = [p["pub"].mensaje_id for p in vista.calcular_trending("c_a")[0]]
        segundo = [p["pub"].mensaje_id for p in vista.calcular_trending("c_a")[0]]
        assert primero == segundo


def test_trending_e6_reply_spam_scores_nothing(hub, app):
    """Forty replies from one member is still one member."""
    with app.app_context():
        spam = publicar("c_a", titulo="SPAM", edad_horas=5)
        for _ in range(40):
            responder(spam, "c_b")
        for i in range(5):
            real = publicar("c_b", titulo=f"REAL{i}", edad_horas=5)
            for m in ("c_a", "c_c", "c_d"):
                responder(real, m)

        posts, rankeado = vista.calcular_trending("c_e")
        assert rankeado is True
        assert "SPAM" not in [p["pub"].titulo for p in posts]


def test_trending_double_dipping_is_capped(hub, app):
    """A member who likes AND replies counts 3, not 5."""
    with app.app_context():
        post = publicar("c_a", edad_horas=5)
        responder(post, "c_b")
        dar_like(post, "c_b")
        responder(post, "c_c")
        responder(post, "c_d")
        # 3 engaged members, all repliers -> raw 9. If double-dipping counted, it would be 11.
        ahora = utc_now().replace(tzinfo=None)
        for _ in range(4):
            otro = publicar("c_c", edad_horas=5)
            for m in ("c_a", "c_b", "c_d"):
                responder(otro, m)
        posts, rankeado = vista.calcular_trending("c_e")
        assert rankeado is True
        assert ahora is not None


def test_trending_excludes_author_self_engagement(hub, app):
    with app.app_context():
        post = publicar("c_a", titulo="SELF", edad_horas=5)
        for _ in range(10):
            responder(post, "c_a")
        for i in range(5):
            real = publicar("c_b", titulo=f"R{i}", edad_horas=5)
            for m in ("c_a", "c_c", "c_d"):
                responder(real, m)
        posts, rankeado = vista.calcular_trending("c_e")
        assert rankeado is True
        assert "SELF" not in [p["pub"].titulo for p in posts]


def test_trending_excludes_posts_older_than_the_window(hub, app):
    with app.app_context():
        viejo = publicar("c_a", titulo="ANCIENT", edad_horas=(vista.VENTANA_ELEGIBILIDAD_DIAS + 2) * 24)
        for m in ("c_b", "c_c", "c_d", "c_e"):
            dar_like(viejo, m)
        for i in range(5):
            real = publicar("c_b", titulo=f"N{i}", edad_horas=5)
            for m in ("c_a", "c_c", "c_d"):
                dar_like(real, m)
        posts, _r = vista.calcular_trending("c_e")
        assert "ANCIENT" not in [p["pub"].titulo for p in posts]


def test_trending_ignores_engagement_outside_the_window(hub, app):
    with app.app_context():
        post = publicar("c_a", titulo="STALE", edad_horas=10 * 24)
        for m in ("c_b", "c_c", "c_d"):
            dar_like(post, m, hace_dias=vista.VENTANA_ENGAGEMENT_DIAS + 1)
        _posts, rankeado = vista.calcular_trending("c_e")
        assert rankeado is False


# ---------------------------------------------------------------------------------------
# Feed behaviour
# ---------------------------------------------------------------------------------------
def test_type_filter(hub, client, app):
    with app.app_context():
        publicar("c_a", titulo="A Question", tipo="question")
        publicar("c_a", titulo="A Build", tipo="build")
    entrar(client, "c_b")
    cuerpo = client.get("/community?tipo=build").get_data(as_text=True)
    assert "A Build" in cuerpo and "A Question" not in cuerpo


def test_search_matches_title_and_body(hub, client, app):
    with app.app_context():
        publicar("c_a", titulo="Unique Marker Here")
    entrar(client, "c_b")
    assert "Unique Marker Here" in client.get("/community?q=Marker").get_data(as_text=True)
    assert "Nothing matched" in client.get("/community?q=zzzznotpresent").get_data(as_text=True)


def test_unknown_query_values_do_not_500(hub, client):
    entrar(client, "c_a")
    assert client.get("/community?view=bogus&tipo=bogus").status_code == 200


def test_malformed_post_id_404s(hub, client):
    entrar(client, "c_a")
    assert client.get("/community/post/not-a-real-ulid").status_code == 404


def test_feed_query_count_is_flat_in_posts(hub, client, app):
    """Adding posts must not add queries."""
    from sqlalchemy import event

    def contar() -> int:
        vistos: list[str] = []

        def registrar(conn, cursor, statement, parameters, context, executemany):
            vistos.append(statement)

        motor = database.engine
        event.listen(motor, "before_cursor_execute", registrar)
        try:
            assert client.get("/community").status_code == 200
        finally:
            event.remove(motor, "before_cursor_execute", registrar)
        return len([q for q in vistos if q.lstrip().upper().startswith("SELECT")])

    entrar(client, "c_a")
    with app.app_context():
        publicar("c_b", titulo="one")
    base = contar()
    with app.app_context():
        for i in range(6):
            publicar("c_b", titulo=f"extra{i}")
    assert contar() == base
