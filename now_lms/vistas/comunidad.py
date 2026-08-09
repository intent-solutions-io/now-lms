# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Community Hub — ADR-8 (000-docs/015-AT-ADEC-community-hub-storage.md).

A private feed where cohort members publish Questions, Builds and Success
Stories, reply to each other, and like a post once. Post bodies and the reply
tree live in the native ``ForoMensaje``; three sidecar tables carry the metadata,
the reactions and the moderation trail that the platform has no representation
for. ``ForoMensaje`` is not modified.

Membership: every active, verified Intent Solutions member is in the Hub. There
is no per-member provisioning, and because there is exactly one Hub with everyone
in it, cross-cohort disclosure is prevented structurally rather than by
filtering — every query is scoped to one course code at the query level, never
hidden in a template.

The canonical Community course is only a container (``ForoMensaje.curso_id`` is
NOT NULL). It is kept at ``foro_habilitado = False`` deliberately: that shuts the
native forum route on it, so nobody can reach Hub posts through
``/course/<code>/forum`` and bypass the moderation filter, and it never trips the
validator forbidding ``foro_habilitado`` on a ``self_paced`` course.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------------------
import threading
from collections import deque
from datetime import timedelta
from time import time
from urllib.parse import urlparse

# ---------------------------------------------------------------------------------------
# Third-party libraries
# ---------------------------------------------------------------------------------------
from bleach import clean
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from markdown import markdown
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.wrappers import Response
from wtforms import HiddenField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length
from wtforms.validators import Optional as OptionalValidator

# ---------------------------------------------------------------------------------------
# Local resources
# ---------------------------------------------------------------------------------------
from now_lms.auth import email_verificado_requerido
from now_lms.config import DIRECTORIO_PLANTILLAS
from now_lms.db import (
    COMUNIDAD_TIPOS,
    ComunidadEventoModeracion,
    ComunidadPublicacion,
    ComunidadReaccion,
    ForoMensaje,
    Usuario,
    database,
    select,
    utc_now,
)
from now_lms.i18n import _, _l

comunidad = Blueprint("comunidad", __name__, template_folder=DIRECTORIO_PLANTILLAS)

# The canonical container course. Created by scripts/seed_community_course.py.
COMMUNITY_COURSE_CODE = "COMMUNITY"

FEED_TEMPLATE = "themes/intent_learn/pages/comunidad_feed.html"
POST_TEMPLATE = "themes/intent_learn/pages/comunidad_post.html"
MODERATION_TEMPLATE = "themes/intent_learn/pages/comunidad_moderacion.html"

TITULO_MAX = 160
CUERPO_MAX = 8000
MOTIVO_MAX = 500
POR_PAGINA = 20

TIPO_ETIQUETAS = {
    "question": _l("Question"),
    "build": _l("Build"),
    "success_story": _l("Success Story"),
}

ROLES_STAFF = ("admin", "instructor", "moderator")

# ---------------------------------------------------------------------------------------
# Trending contract (ADR-8 §9 of the plan). Constants live together so they are tunable
# in one place without a migration — the ranking is computed live, never stored.
# ---------------------------------------------------------------------------------------
VENTANA_ELEGIBILIDAD_DIAS = 30  # a post older than this cannot trend, however active
VENTANA_ENGAGEMENT_DIAS = 7  # only likes and replies inside this window count
PESO_RESPUESTA = 3  # a reply costs more than a like and is the durable artifact
PESO_LIKE = 2
MINIMO_MIEMBROS = 3  # fewer distinct engaged members and the post does not qualify
MINIMO_PARA_RANKEAR = 5  # fewer qualifying posts and Trending refuses to exist
GRAVEDAD = 1.5
DESPLAZAMIENTO_HORAS = 2

# ---------------------------------------------------------------------------------------
# Sanitiser. Deliberately NOT forum.py's: that allow-list permits <img src> with no scheme
# or host restriction, which makes any member post a tracking pixel that leaks every
# reader's IP, and it strips `rel`, so links cannot be hardened at render time.
# Media hosting is an explicit non-goal for V1, so images have no legitimate use here.
# ---------------------------------------------------------------------------------------
TAGS_PERMITIDOS = [
    "p", "br", "strong", "em", "u", "ol", "ul", "li",
    "h3", "h4", "h5", "h6", "blockquote", "code", "pre", "a",
]
ATRIBUTOS_PERMITIDOS = {"a": ["href", "title", "rel", "target"]}
PROTOCOLOS_PERMITIDOS = ["http", "https", "mailto"]


def markdown_seguro(texto: str) -> str:
    """Markdown to sanitised HTML, with every anchor hardened."""
    html = markdown(texto or "", extensions=["nl2br", "codehilite"])
    limpio = clean(html, tags=TAGS_PERMITIDOS, attributes=ATRIBUTOS_PERMITIDOS, protocols=PROTOCOLOS_PERMITIDOS)
    return limpio.replace("<a ", '<a rel="noopener noreferrer nofollow" target="_blank" ')


def enlace_valido(bruto: str | None) -> bool:
    """True when the build link is a plausible http(s) URL with a hostname."""
    if not bruto:
        return True
    try:
        partes = urlparse(bruto)
    except ValueError:
        return False
    return partes.scheme in ("http", "https") and bool(partes.netloc)


# ---------------------------------------------------------------------------------------
# Rate limiting. In-process sliding window keyed on the member, following
# vistas/request_access.py. The repo's `check_rate_limit` helper is deliberately NOT used:
# it is a silent no-op under NullCache, which is the production fallback.
# ---------------------------------------------------------------------------------------
_LIMITES = {"post": (10, 3600), "reply": (30, 3600), "report": (10, 3600), "like": (200, 3600)}
_LOCK = threading.Lock()
_CUBOS: dict[str, deque] = {}
_MAX_CUBOS = 10_000


def _limitado(accion: str, usuario: str) -> bool:
    """True when this member is over the limit for this action."""
    maximo, ventana = _LIMITES[accion]
    ahora = time()
    clave = f"{accion}:{usuario}"
    with _LOCK:
        cubo = _CUBOS.setdefault(clave, deque())
        while cubo and ahora - cubo[0] > ventana:
            cubo.popleft()
        if len(cubo) >= maximo:
            return True
        cubo.append(ahora)
        if len(_CUBOS) > _MAX_CUBOS:
            for clave_vieja in sorted(_CUBOS, key=lambda k: _CUBOS[k][-1] if _CUBOS[k] else 0)[:1000]:
                _CUBOS.pop(clave_vieja, None)
        return False


# ---------------------------------------------------------------------------------------
# Forms. Every mutating route goes through a FlaskForm and validate_on_submit(): this
# application does not install CSRFProtect, so csrf_token() is not a template global and a
# hand-rolled POST form would carry no CSRF protection at all.
# ---------------------------------------------------------------------------------------
class PublicacionForm(FlaskForm):
    """A new Hub post."""

    titulo = StringField(_l("Title"), validators=[DataRequired(), Length(max=TITULO_MAX)])
    tipo = SelectField(_l("Type"), choices=[(t, TIPO_ETIQUETAS[t]) for t in COMUNIDAD_TIPOS], validators=[DataRequired()])
    contenido = TextAreaField(_l("Your post"), validators=[DataRequired(), Length(max=CUERPO_MAX)])
    enlace_build = StringField(_l("Link (optional)"), validators=[OptionalValidator(), Length(max=500)])


class RespuestaForm(FlaskForm):
    """A reply to a Hub post."""

    contenido = TextAreaField(_l("Reply"), validators=[DataRequired(), Length(max=CUERPO_MAX)])


class AccionForm(FlaskForm):
    """Empty form whose only job is to carry a CSRF token on a state-changing POST."""


class ReporteForm(FlaskForm):
    """A member report. A reason is required or the report is not actionable."""

    motivo = StringField(_l("What is wrong with this post?"), validators=[DataRequired(), Length(max=MOTIVO_MAX)])


class ModeracionForm(FlaskForm):
    """A staff hide, which owes the author a reason."""

    motivo = StringField(_l("Reason"), validators=[DataRequired(), Length(max=MOTIVO_MAX)])
    destino = HiddenField()


# ---------------------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------------------
def es_miembro() -> bool:
    """Every active member with a real role is in the Hub.

    Deliberately checks ``activo`` and the role itself rather than relying on the
    fact that self-registration is closed: that gate lives in host ingress config
    outside this repository, and regenerating it silently reopens signup.
    """
    return bool(
        current_user.is_authenticated
        and current_user.activo
        and current_user.tipo in (*ROLES_STAFF, "student")
    )


def es_staff() -> bool:
    """Moderators, instructors and admins."""
    return bool(current_user.is_authenticated and current_user.tipo in ROLES_STAFF)


def _exigir_miembro() -> None:
    if not es_miembro():
        abort(404)


def _exigir_staff() -> None:
    if not es_staff():
        abort(403)


# ---------------------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------------------
def _publicaciones_base():
    """Visible Hub root posts, scoped at the query level. Never filtered in a template."""
    return (
        select(ComunidadPublicacion, ForoMensaje, Usuario)
        .join(ForoMensaje, ForoMensaje.id == ComunidadPublicacion.mensaje_id)
        .join(Usuario, Usuario.usuario == ForoMensaje.usuario_id)
        .filter(
            ForoMensaje.curso_id == COMMUNITY_COURSE_CODE,
            ForoMensaje.parent_id.is_(None),
            ComunidadPublicacion.estado_moderacion == "visible",
        )
    )


def _agregados(mensaje_ids: list[str], usuario: str) -> tuple[dict, dict, set]:
    """Like counts, reply counts and this member's likes — three queries, flat in post count."""
    if not mensaje_ids:
        return {}, {}, set()

    likes = dict(
        database.session.execute(
            select(ComunidadReaccion.mensaje_id, func.count(ComunidadReaccion.id))
            .filter(ComunidadReaccion.mensaje_id.in_(mensaje_ids))
            .group_by(ComunidadReaccion.mensaje_id)
        ).all()
    )
    respuestas = dict(
        database.session.execute(
            select(ForoMensaje.parent_id, func.count(ForoMensaje.id))
            .filter(ForoMensaje.parent_id.in_(mensaje_ids))
            .group_by(ForoMensaje.parent_id)
        ).all()
    )
    mios = set(
        database.session.execute(
            select(ComunidadReaccion.mensaje_id).filter(
                ComunidadReaccion.mensaje_id.in_(mensaje_ids), ComunidadReaccion.usuario == usuario
            )
        )
        .scalars()
        .all()
    )
    return likes, respuestas, mios


def _decorar(filas, usuario: str) -> list[dict]:
    """Attach counts to a page of posts without a query per row."""
    ids = [pub.mensaje_id for pub, _, _ in filas]
    likes, respuestas, mios = _agregados(ids, usuario)
    return [
        {
            "pub": pub,
            "mensaje": msg,
            "autor": autor,
            "likes": likes.get(pub.mensaje_id, 0),
            "respuestas": respuestas.get(pub.mensaje_id, 0),
            "me_gusta": pub.mensaje_id in mios,
            "es_propio": msg.usuario_id == usuario,
            "etiqueta": TIPO_ETIQUETAS.get(pub.tipo, pub.tipo),
        }
        for pub, msg, autor in filas
    ]


def calcular_trending(usuario: str) -> tuple[list[dict], bool]:
    """Rank visible root posts. Returns (posts, ranked).

    ``ranked`` is False when too few posts qualify, in which case the caller shows
    Latest with an honest banner rather than crowning a post with three likes.

    Each engaged member counts exactly once: a reply counts 3, a like counts 2,
    and doing both counts 3. That collapses double-dipping by construction and is
    what makes reply spam worth nothing — forty replies from one member is still
    one member.
    """
    ahora = utc_now().replace(tzinfo=None)
    corte_post = ahora - timedelta(days=VENTANA_ELEGIBILIDAD_DIAS)
    corte_engagement = ahora - timedelta(days=VENTANA_ENGAGEMENT_DIAS)

    filas = database.session.execute(
        _publicaciones_base().filter(
            ComunidadPublicacion.fijado.is_(False),
            ForoMensaje.fecha_creacion >= corte_post,
            Usuario.activo.is_(True),
        )
    ).all()
    if not filas:
        return [], False

    ids = [pub.mensaje_id for pub, _, _ in filas]
    autores = {pub.mensaje_id: msg.usuario_id for pub, msg, _ in filas}

    # Distinct likers in the window, excluding the author and inactive accounts.
    likers: dict[str, set] = {i: set() for i in ids}
    for mensaje_id, quien in database.session.execute(
        select(ComunidadReaccion.mensaje_id, ComunidadReaccion.usuario)
        .join(Usuario, Usuario.usuario == ComunidadReaccion.usuario)
        .filter(
            ComunidadReaccion.mensaje_id.in_(ids),
            ComunidadReaccion.timestamp >= corte_engagement,
            Usuario.activo.is_(True),
        )
    ).all():
        if quien != autores.get(mensaje_id):
            likers[mensaje_id].add(quien)

    # Distinct non-author repliers in the window.
    repliers: dict[str, set] = {i: set() for i in ids}
    for parent_id, quien in database.session.execute(
        select(ForoMensaje.parent_id, ForoMensaje.usuario_id)
        .join(Usuario, Usuario.usuario == ForoMensaje.usuario_id)
        .filter(
            ForoMensaje.parent_id.in_(ids),
            ForoMensaje.fecha_creacion >= corte_engagement,
            Usuario.activo.is_(True),
        )
    ).all():
        if quien != autores.get(parent_id):
            repliers[parent_id].add(quien)

    puntuados = []
    for pub, msg, _autor in filas:
        r, lk = repliers[pub.mensaje_id], likers[pub.mensaje_id]
        comprometidos = r | lk
        if len(comprometidos) < MINIMO_MIEMBROS:
            continue
        # Per-member weight, counted once. Replying outranks liking; doing both is not additive.
        bruto = sum(PESO_RESPUESTA if m in r else PESO_LIKE for m in comprometidos)
        horas = max(0.0, (ahora - msg.fecha_creacion).total_seconds() / 3600.0)
        puntaje = bruto / ((horas + DESPLAZAMIENTO_HORAS) ** GRAVEDAD)
        puntuados.append(((puntaje, len(comprometidos), msg.fecha_creacion, msg.id), (pub, msg, _autor)))

    if len(puntuados) < MINIMO_PARA_RANKEAR:
        return [], False

    # Total order, so pagination is stable and nothing is ever random.
    puntuados.sort(key=lambda par: par[0], reverse=True)
    return _decorar([fila for _, fila in puntuados], usuario), True


def _anclados(usuario: str) -> list[dict]:
    filas = database.session.execute(
        _publicaciones_base().filter(ComunidadPublicacion.fijado.is_(True)).order_by(ForoMensaje.fecha_creacion.desc())
    ).all()
    return _decorar(filas, usuario)


def posts_recientes(usuario: str, limite: int = 5) -> list[dict]:
    """The newest visible Hub posts, for the member dashboard.

    Lives here rather than in the dashboard so the Hub owns its own scoping and
    the dashboard never writes a query against Hub tables.
    """
    filas = database.session.execute(
        _publicaciones_base()
        .filter(ComunidadPublicacion.fijado.is_(False))
        .order_by(ForoMensaje.fecha_creacion.desc())
        .limit(limite)
    ).all()
    return _decorar(filas, usuario)


# ---------------------------------------------------------------------------------------
# Read routes
# ---------------------------------------------------------------------------------------
@comunidad.route("/community", methods=["GET"])
@login_required
def feed() -> str:
    """The Hub feed: Latest or Trending, filtered by type, searchable."""
    _exigir_miembro()
    usuario = current_user.usuario

    vista = request.args.get("view", "latest")
    if vista not in ("latest", "trending"):
        vista = "latest"
    tipo = request.args.get("tipo")
    if tipo not in COMUNIDAD_TIPOS:
        tipo = None
    consulta = (request.args.get("q") or "").strip()

    degradado = False
    if vista == "trending" and not tipo and not consulta:
        publicaciones, rankeado = calcular_trending(usuario)
        if not rankeado:
            degradado = True
    else:
        publicaciones, rankeado = [], False

    if not rankeado:
        seleccion = _publicaciones_base().filter(ComunidadPublicacion.fijado.is_(False))
        if tipo:
            seleccion = seleccion.filter(ComunidadPublicacion.tipo == tipo)
        if consulta:
            patron = f"%{consulta}%"
            seleccion = seleccion.filter(
                database.or_(ComunidadPublicacion.titulo.ilike(patron), ForoMensaje.contenido.ilike(patron))
            )
        filas = database.session.execute(
            seleccion.order_by(ForoMensaje.fecha_creacion.desc()).limit(POR_PAGINA)
        ).all()
        publicaciones = _decorar(filas, usuario)

    return render_template(
        FEED_TEMPLATE,
        publicaciones=publicaciones,
        anclados=_anclados(usuario) if not consulta and not tipo else [],
        vista=vista,
        degradado=degradado,
        tipo=tipo,
        consulta=consulta,
        tipos=[(t, TIPO_ETIQUETAS[t]) for t in COMUNIDAD_TIPOS],
        es_staff=es_staff(),
        accion_form=AccionForm(),
    )


@comunidad.route("/community/post/<mensaje_id>", methods=["GET"])
@login_required
def ver_publicacion(mensaje_id: str) -> str:
    """One post and its replies."""
    _exigir_miembro()
    usuario = current_user.usuario

    fila = database.session.execute(
        select(ComunidadPublicacion, ForoMensaje, Usuario)
        .join(ForoMensaje, ForoMensaje.id == ComunidadPublicacion.mensaje_id)
        .join(Usuario, Usuario.usuario == ForoMensaje.usuario_id)
        .filter(ComunidadPublicacion.mensaje_id == mensaje_id, ForoMensaje.curso_id == COMMUNITY_COURSE_CODE)
    ).first()
    # 404 rather than 403 on a hidden post: a 403 confirms it exists.
    if not fila:
        abort(404)
    pub, msg, _autor = fila
    if pub.estado_moderacion != "visible" and not (es_staff() or msg.usuario_id == usuario):
        abort(404)

    respuestas = database.session.execute(
        select(ForoMensaje, Usuario)
        .join(Usuario, Usuario.usuario == ForoMensaje.usuario_id)
        .filter(ForoMensaje.parent_id == mensaje_id)
        .order_by(ForoMensaje.fecha_creacion)
    ).all()

    decorado = _decorar([fila], usuario)[0]
    return render_template(
        POST_TEMPLATE,
        item=decorado,
        cuerpo=markdown_seguro(msg.contenido),
        respuestas=[
            {
                "mensaje": r,
                "autor": a,
                "cuerpo": markdown_seguro(r.contenido),
                "es_staff": a.tipo in ROLES_STAFF,
            }
            for r, a in respuestas
        ],
        cerrado=msg.estado == "cerrado",
        oculto=pub.estado_moderacion != "visible",
        respuesta_form=RespuestaForm(),
        reporte_form=ReporteForm(),
        moderacion_form=ModeracionForm(),
        accion_form=AccionForm(),
        es_staff=es_staff(),
    )


# ---------------------------------------------------------------------------------------
# Write routes
# ---------------------------------------------------------------------------------------
@comunidad.route("/community/new", methods=["GET", "POST"])
@login_required
@email_verificado_requerido
def nueva_publicacion() -> str | Response:
    """Compose a post."""
    _exigir_miembro()
    form = PublicacionForm()
    if form.validate_on_submit():
        if _limitado("post", current_user.usuario):
            flash(_("You have posted a lot in a short time. Try again shortly."), "warning")
            return redirect(url_for("comunidad.feed"))
        if not enlace_valido(form.enlace_build.data):
            flash(_("That link does not look like a web address."), "warning")
            return render_template(FEED_TEMPLATE + "#", form=form) if False else redirect(url_for("comunidad.nueva_publicacion"))

        mensaje = ForoMensaje(
            curso_id=COMMUNITY_COURSE_CODE,
            usuario_id=current_user.usuario,
            parent_id=None,
            contenido=form.contenido.data,
            estado="abierto",
        )
        database.session.add(mensaje)
        database.session.flush()
        database.session.add(
            ComunidadPublicacion(
                mensaje_id=mensaje.id,
                titulo=form.titulo.data,
                tipo=form.tipo.data,
                estado_moderacion="visible",
                fijado=False,
                enlace_build=(form.enlace_build.data or None),
                reportes_abiertos=0,
            )
        )
        database.session.commit()
        return redirect(url_for("comunidad.ver_publicacion", mensaje_id=mensaje.id))

    return render_template(
        "themes/intent_learn/pages/comunidad_nuevo.html", form=form, tipos=[(t, TIPO_ETIQUETAS[t]) for t in COMUNIDAD_TIPOS]
    )


@comunidad.route("/community/post/<mensaje_id>/reply", methods=["POST"])
@login_required
@email_verificado_requerido
def responder(mensaje_id: str) -> Response:
    """Reply to a post."""
    _exigir_miembro()
    _pub, raiz = _cargar_visible(mensaje_id)
    if raiz.estado == "cerrado":
        flash(_("Replies are closed on this thread."), "warning")
        return redirect(url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))

    form = RespuestaForm()
    if form.validate_on_submit():
        if _limitado("reply", current_user.usuario):
            flash(_("You have replied a lot in a short time. Try again shortly."), "warning")
        else:
            database.session.add(
                ForoMensaje(
                    curso_id=COMMUNITY_COURSE_CODE,
                    usuario_id=current_user.usuario,
                    parent_id=mensaje_id,
                    contenido=form.contenido.data,
                    estado="abierto",
                )
            )
            database.session.commit()
    return redirect(url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))


@comunidad.route("/community/post/<mensaje_id>/like", methods=["POST"])
@login_required
@email_verificado_requerido
def dar_like(mensaje_id: str) -> Response:
    """Idempotent like. Never a toggle.

    Two endpoints rather than one toggle because a toggle under a double-click
    flips twice and lands wherever the race left it, while two idempotent
    endpoints always converge on the state the member asked for. The database
    unique constraint is the arbiter — there is no read-then-write window.
    """
    _exigir_miembro()
    _pub, raiz = _cargar_visible(mensaje_id)
    if raiz.usuario_id == current_user.usuario:
        abort(403)  # a member cannot like their own post
    if not AccionForm().validate_on_submit():
        abort(400)
    if _limitado("like", current_user.usuario):
        return redirect(request.referrer or url_for("comunidad.feed"))

    try:
        with database.session.begin_nested():
            database.session.add(ComunidadReaccion(mensaje_id=mensaje_id, usuario=current_user.usuario))
    except IntegrityError:
        # Already liked. The constraint absorbed a concurrent duplicate; this is success.
        pass
    database.session.commit()
    return redirect(request.referrer or url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))


@comunidad.route("/community/post/<mensaje_id>/unlike", methods=["POST"])
@login_required
@email_verificado_requerido
def quitar_like(mensaje_id: str) -> Response:
    """Idempotent unlike. Deleting zero rows is success."""
    _exigir_miembro()
    if not AccionForm().validate_on_submit():
        abort(400)
    database.session.execute(
        database.delete(ComunidadReaccion).where(
            ComunidadReaccion.mensaje_id == mensaje_id, ComunidadReaccion.usuario == current_user.usuario
        )
    )
    database.session.commit()
    return redirect(request.referrer or url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))


@comunidad.route("/community/post/<mensaje_id>/report", methods=["POST"])
@login_required
@email_verificado_requerido
def reportar(mensaje_id: str) -> Response:
    """Report a post. Reporting never hides anything — only a staff action does."""
    _exigir_miembro()
    pub, _raiz = _cargar_visible(mensaje_id)
    form = ReporteForm()
    if form.validate_on_submit() and not _limitado("report", current_user.usuario):
        database.session.add(
            ComunidadEventoModeracion(
                mensaje_id=mensaje_id, tipo="report", actor=current_user.usuario, motivo=form.motivo.data
            )
        )
        pub.reportes_abiertos = (pub.reportes_abiertos or 0) + 1
        database.session.commit()
        flash(_("Thank you. A moderator will look at this."), "info")
    return redirect(url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))


# ---------------------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------------------
def _cargar_visible(mensaje_id: str) -> tuple[ComunidadPublicacion, ForoMensaje]:
    """Load a Hub post, 404 when it is not one."""
    fila = database.session.execute(
        select(ComunidadPublicacion, ForoMensaje)
        .join(ForoMensaje, ForoMensaje.id == ComunidadPublicacion.mensaje_id)
        .filter(ComunidadPublicacion.mensaje_id == mensaje_id, ForoMensaje.curso_id == COMMUNITY_COURSE_CODE)
    ).first()
    if not fila:
        abort(404)
    return fila[0], fila[1]


def _registrar(mensaje_id: str, tipo: str, motivo: str | None = None) -> None:
    database.session.add(
        ComunidadEventoModeracion(mensaje_id=mensaje_id, tipo=tipo, actor=current_user.usuario, motivo=motivo)
    )


@comunidad.route("/community/post/<mensaje_id>/hide", methods=["POST"])
@login_required
def ocultar(mensaje_id: str) -> Response:
    """Hide a post. Reversible, reasoned, and recorded. Nothing is deleted."""
    _exigir_staff()
    pub, _raiz = _cargar_visible(mensaje_id)
    form = ModeracionForm()
    if form.validate_on_submit():
        pub.estado_moderacion = "oculto"
        _registrar(mensaje_id, "hide", form.motivo.data)
        database.session.commit()
        flash(_("Post hidden."), "info")
    else:
        flash(_("A reason is required to hide a post."), "warning")
    return redirect(url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))


@comunidad.route("/community/post/<mensaje_id>/restore", methods=["POST"])
@login_required
def restaurar(mensaje_id: str) -> Response:
    """Reverse a hide and clear the report queue counter."""
    _exigir_staff()
    pub, _raiz = _cargar_visible(mensaje_id)
    if AccionForm().validate_on_submit():
        pub.estado_moderacion = "visible"
        pub.reportes_abiertos = 0
        _registrar(mensaje_id, "restore")
        database.session.commit()
    return redirect(url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))


@comunidad.route("/community/post/<mensaje_id>/lock", methods=["POST"])
@login_required
def cerrar(mensaje_id: str) -> Response:
    """Close replies, reusing the platform's own ForoMensaje.estado rather than a new field."""
    _exigir_staff()
    _pub, raiz = _cargar_visible(mensaje_id)
    if AccionForm().validate_on_submit():
        raiz.estado = "cerrado"
        _registrar(mensaje_id, "lock")
        database.session.commit()
    return redirect(url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))


@comunidad.route("/community/post/<mensaje_id>/unlock", methods=["POST"])
@login_required
def abrir(mensaje_id: str) -> Response:
    """Reopen replies."""
    _exigir_staff()
    _pub, raiz = _cargar_visible(mensaje_id)
    if AccionForm().validate_on_submit():
        raiz.estado = "abierto"
        _registrar(mensaje_id, "unlock")
        database.session.commit()
    return redirect(url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))


@comunidad.route("/community/post/<mensaje_id>/pin", methods=["POST"])
@login_required
def fijar(mensaje_id: str) -> Response:
    """Pin a post above the feed. Admins only."""
    if not (current_user.is_authenticated and current_user.tipo == "admin"):
        abort(403)
    pub, _raiz = _cargar_visible(mensaje_id)
    if AccionForm().validate_on_submit():
        pub.fijado = not pub.fijado
        _registrar(mensaje_id, "pin" if pub.fijado else "unpin")
        database.session.commit()
    return redirect(url_for("comunidad.ver_publicacion", mensaje_id=mensaje_id))


@comunidad.route("/community/moderation", methods=["GET"])
@login_required
def moderacion() -> str:
    """Open reports and the recent moderation trail."""
    _exigir_staff()
    reportados = database.session.execute(
        select(ComunidadPublicacion, ForoMensaje, Usuario)
        .join(ForoMensaje, ForoMensaje.id == ComunidadPublicacion.mensaje_id)
        .join(Usuario, Usuario.usuario == ForoMensaje.usuario_id)
        .filter(ForoMensaje.curso_id == COMMUNITY_COURSE_CODE, ComunidadPublicacion.reportes_abiertos > 0)
        .order_by(ComunidadPublicacion.reportes_abiertos.desc())
    ).all()
    eventos = database.session.execute(
        select(ComunidadEventoModeracion).order_by(ComunidadEventoModeracion.ocurrido_en.desc()).limit(50)
    ).scalars().all()
    return render_template(
        MODERATION_TEMPLATE,
        reportados=_decorar(reportados, current_user.usuario),
        eventos=eventos,
        accion_form=AccionForm(),
    )
