# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Configuración de cache."""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------------------
from os import environ

# ---------------------------------------------------------------------------------------
# Third-party libraries
# ---------------------------------------------------------------------------------------
from flask_caching import Cache
from flask_login import current_user

# ---------------------------------------------------------------------------------------
# Local resources
# ---------------------------------------------------------------------------------------
from now_lms.logs import log

# < --------------------------------------------------------------------------------------------- >
# Configuracion de Cache


# For backward compatibility, we need to maintain CTYPE and CACHE_CONFIG
# The actual cache initialization will be handled by cache_utils.py
def _determine_cache_type() -> str:
    """Helper to determine which cache type is configured via environment variables."""
    if (environ.get("CACHE_REDIS_URL")) or (environ.get("REDIS_URL")):
        return "redis"
    if environ.get("CACHE_MEMCACHED_SERVERS"):
        return "memcached"
    if environ.get("NOW_LMS_MEMORY_CACHE", "0") == "1":
        return "filesystem"
    return "null"


def _get_cache_type_for_compatibility() -> str:
    """Determine cache type for backward compatibility with existing code."""
    cache_type = _determine_cache_type()

    match cache_type:
        case "redis":
            return "RedisCache"
        case "memcached":
            return "MemcachedCache"
        case "filesystem":
            return "FileSystemCache"
        case _:
            return "NullCache"


def _get_cache_config_for_compatibility() -> dict[str, object]:
    """Get basic cache config for backward compatibility."""
    config: dict[str, object] = {"CACHE_KEY_PREFIX": "now_lms:", "CACHE_DEFAULT_TIMEOUT": 300}

    cache_type = _determine_cache_type()

    match cache_type:
        case "redis":
            config["CACHE_TYPE"] = "RedisCache"
            config["CACHE_REDIS_URL"] = environ.get("CACHE_REDIS_URL") or environ.get("REDIS_URL")
        case "memcached":
            config["CACHE_TYPE"] = "MemcachedCache"
            config["CACHE_MEMCACHED_SERVERS"] = environ.get("CACHE_MEMCACHED_SERVERS")
        case "filesystem":
            config["CACHE_TYPE"] = "FileSystemCache"
            # Note: CACHE_DIR will be determined dynamically by cache_utils
        case _:
            config["CACHE_TYPE"] = "NullCache"

    return config


# Maintain backward compatibility
CTYPE = _get_cache_type_for_compatibility()
CACHE_CONFIG = _get_cache_config_for_compatibility()

if CTYPE != "NullCache":
    log.trace(f"Using {CTYPE} service for storage")
else:
    log.debug("No cache service configured.")

# Create cache instance (will be properly initialized via cache_utils.init_cache)
cache: Cache = Cache()


# ---------------------------------------------------------------------------------------
# Opciones de cache.
# ---------------------------------------------------------------------------------------
def no_guardar_en_cache_global() -> bool:
    """Si el usuario es anomino preferimos usar el sistema de cache.

    NOTE: this is not a substitute for a correct cache key, and is currently unused.
    As the comments below record, suppressing the WRITE still leaves an existing
    anonymous entry readable by an authenticated user. `cache_key_with_auth_state`
    is the mechanism that actually separates users; prefer it.
    """
    # Return True (don't cache) when user is authenticated
    # Return False (do cache) when user is anonymous
    # IMPORTANT: This only controls whether to WRITE to cache, not whether to READ from it
    # If an anonymous user's cached page exists, authenticated users will still see it
    # unless we use a different cache key per authentication state
    return current_user and current_user.is_authenticated


def cache_key_with_auth_state() -> str:
    """Generate a cache key scoped to the individual user.

    Separating "authenticated" from "anonymous" is not enough: every view using this
    key function renders per-user content (enrolment state, instructor controls, admin
    listings), so two authenticated users sharing one key means whichever request
    populates the cache decides what the next user sees. The key therefore carries the
    user's identity, not merely the fact that somebody is logged in.

    Anonymous requests continue to share a single "anon" key, which is what makes the
    cache worthwhile for public pages.
    """
    from flask import request

    # Include the user IDENTITY, not just the auth-or-anon flag. Pages cached
    # under these keys (course take/moderate, etc.) render per-user data —
    # evaluation attempts, certificates, enrollment state — so keying on a
    # shared "auth" bucket serves one member's cached page to every other
    # member the moment a real cache backend (Redis) is configured.
    # (Fork finding U10, merged upstream as 717a8f0 and released in 2.0.3.)
    #
    # Deliberately keyed on `usuario` (the username) rather than upstream's
    # `current_user.id`: both are unique per user and equally safe, but
    # invalidate_user_course_view_cache() rebuilds these keys from the username
    # it is handed at the enrollment call sites. Switching to `.id` here without
    # changing that helper would make every invalidation a silent no-op.
    if current_user and current_user.is_authenticated:
        scope = f"user:{current_user.usuario}"
    else:
        scope = "anon"

    # Build key from request path and the identity scope
    key = f"view/{request.path}/{scope}"

    # The query string belongs in the key ONLY where the view actually reads it.
    #
    # Every other route gets an unbounded family of keys that no invalidator can
    # reach: `cache.delete()` takes one exact key, and none of the supported
    # backends (Redis, Memcached, FileSystem) offers portable pattern deletion, so
    # `.../view/user:someone?anything` survives a course edit forever. It is also a
    # cache-busting vector, since any visitor can mint fresh entries by appending a
    # parameter the view ignores.
    #
    # RUTAS_CON_QUERY is the allow-list of paths whose output genuinely varies:
    # the catalogue and home pages read `page`, `nivel`, `tag` and `category`.
    # `/course/<code>/view` reads none, which is why the reported case
    # (`.../view/user:founding.member?tab=details`) was uninvalidatable.
    # Greptile, PR #78.
    if request.query_string and _varia_por_query(request.path):
        key += f"?{request.query_string.decode('utf-8')}"

    # For the query-varying routes the exact keys still cannot be enumerated, so
    # they carry a generation instead: bumping it makes every prior variant
    # unreachable in one write, whatever query produced it.
    if _varia_por_query(request.path):
        key += f"/g{_generacion_catalogo()}"

    return key


# Paths whose rendered output depends on the query string, so the key must carry it.
# Keep this list in step with the views: a path listed here that ignores its args
# just fragments the cache; a path missing from here that reads args serves the
# wrong page. Both are worse than the invalidation bug this exists to fix.
RUTAS_CON_QUERY = ("/course/explore", "/program/explore", "/")

GENERACION_CATALOGO = "cache_gen:catalogo"


def _varia_por_query(path: str) -> bool:
    """True when this path's output legitimately depends on its query string."""
    return path.rstrip("/") in tuple(r.rstrip("/") for r in RUTAS_CON_QUERY) or path == "/"


def _generacion_catalogo() -> int:
    """Current generation for the query-varying catalogue routes.

    Stored without expiry. If the backend evicts it the counter restarts at zero,
    which can briefly resurface a stale catalogue entry — strictly better than the
    present behaviour, where those entries are never invalidated at all.
    """
    try:
        return int(cache.get(GENERACION_CATALOGO) or 0)
    except (TypeError, ValueError):
        return 0


def bump_generacion_catalogo() -> None:
    """Retire every cached catalogue and home variant, for every user, in one write."""
    try:
        cache.set(GENERACION_CATALOGO, _generacion_catalogo() + 1, timeout=0)
    except Exception:  # noqa: BLE001 - a cache that cannot count must not break a write path
        log.warning("cache: could not bump the catalogue generation; entries will expire on TTL")


def cache_key_with_query_string() -> str:
    """Cache key for public pages whose output varies by query string only.

    Flask-Caching's default view key is ``"view/%s" % request.path`` with
    ``query_string=False``, so ``?tag=x`` collapses onto the unfiltered page and
    one filtered listing is served for another. Use this where the page is the
    same for every visitor but differs by its query parameters; use
    `cache_key_with_auth_state` when the output also depends on who is asking.
    """
    from flask import request

    key = f"view/{request.path}"
    if request.query_string:
        key += f"?{request.query_string.decode('utf-8')}"
    return key


def cache_incr(key: str, timeout: int = 60) -> int:
    """Incrementa un contador en cache de forma atómica.

    Para Redis usa INCR nativo; para otros backends (o si Redis no está
    disponible) realiza get + set manual.
    """
    backend = cache.cache
    client = getattr(backend, "_write_client", None)
    if client is not None:
        try:
            prefix = getattr(backend, "_get_prefix", lambda: "")()
            return client.incr(name=f"{prefix}{key}", amount=1)
        except Exception:
            pass
    current = cache.get(key)
    if current is None:
        current = 1
    else:
        current = int(current) + 1
    cache.set(key, current, timeout=timeout)
    return current


def invalidate_all_cache() -> bool:
    """Invalida toda la cache del sistema cuando cambia el tema."""
    try:
        if CTYPE != "NullCache":
            cache.clear()
            log.trace("Cache invalidated due to theme change")
        return True
    except Exception as e:
        log.error(f"Error invalidating cache: {e}")
        return False


def _obtiene_llaves_generales_cache() -> list[str]:
    """Retorna las llaves anónimas comunes de catálogo y página de inicio para invalidación.

    Las variantes ``/auth`` de esta lista quedaron obsoletas cuando
    `cache_key_with_auth_state()` empezó a cachear por identidad de usuario
    (``user:<usuario>``) en vez de por un balde compartido "auth" — ver
    `RUTAS_GENERALES` para el reemplazo correcto por-usuario.
    """
    return [
        # Con doble diagonal
        "view//course/explore/anon",
        "view//program/explore/anon",
        "view///anon",
        # Con diagonal simple
        "view/course/explore/anon",
        "view/program/explore/anon",
        "view//anon",
    ]


def _llave_vista_por_usuario(ruta: str, usuario: str) -> str:
    """Construye la misma llave que emite `cache_key_with_auth_state()` para un usuario autenticado.

    Único lugar que conoce ese formato aparte de la propia `cache_key_with_auth_state()`,
    para que un futuro cambio de formato de llave no pueda desincronizar los
    invalidadores de esa función otra vez (la falla que produjo este arreglo).
    """
    return f"view/{ruta}/user:{usuario}"


def _elimina_vistas_por_usuario(usuario: str, rutas: list[str]) -> None:
    """Borra, para un usuario, las entradas de cache por-usuario de las rutas dadas."""
    for ruta in rutas:
        cache.delete(_llave_vista_por_usuario(ruta, usuario))


def _obtiene_roster_curso(course_code: str) -> set[str]:
    """Usuarios cuya cache por-usuario de este curso debe invalidarse: estudiantes
    matriculados, docentes y moderadores asignados al curso."""
    from now_lms.db import DocenteCurso, EstudianteCurso, ModeradorCurso, database

    roster: set[str] = set()
    for modelo in (EstudianteCurso, DocenteCurso, ModeradorCurso):
        rows = database.session.execute(database.select(modelo).filter_by(curso=course_code)).scalars().all()
        roster.update(row.usuario for row in rows)
    return roster


RUTAS_GENERALES = ("/course/explore", "/program/explore", "/")
"""Rutas de inicio y catálogo que también cachean por identidad de usuario."""


def invalidar_cache_curso(course_code: str) -> None:
    """Invalidar cache para un curso específico y las vistas relacionadas.

    Cubre tanto la entrada anónima compartida como, para cada estudiante,
    docente o moderador del curso, su propia entrada por-usuario — las vistas
    de curso cachean con `cache_key_with_auth_state()`, que separa por
    identidad, no por un balde "auth" compartido (fork finding L1).
    """
    if CTYPE == "NullCache":
        return
    try:
        rutas_curso = [
            f"/course/{course_code}/view",
            f"/course/{course_code}/admin",
            f"/course/{course_code}/take",
            f"/course/{course_code}/moderate",
        ]
        keys_to_delete = [f"view/{ruta}/anon" for ruta in rutas_curso]
        keys_to_delete.extend(_obtiene_llaves_generales_cache())
        for key in keys_to_delete:
            cache.delete(key)

        # The catalogue and home pages vary by query string, so their exact keys
        # cannot be enumerated. Bumping the generation retires every variant for
        # every user in one write, which is what deleting a fixed list could not do.
        bump_generacion_catalogo()

        roster = _obtiene_roster_curso(course_code)
        for usuario in roster:
            _elimina_vistas_por_usuario(usuario, rutas_curso)
            _elimina_vistas_por_usuario(usuario, list(RUTAS_GENERALES))
        log.trace(f"Cache invalidated for course: {course_code} ({len(roster)} member(s))")
    except Exception as e:
        log.error(f"Error invalidating cache for course {course_code}: {e}")


def invalidar_cache_programa(program_code: str) -> None:
    """Invalidar cache para un programa específico y las vistas relacionadas."""
    if CTYPE == "NullCache":
        return
    try:
        keys_to_delete = [
            f"view//program/{program_code}/anon",
            f"view//program/{program_code}/auth",
            f"view/program/{program_code}/anon",
            f"view/program/{program_code}/auth",
        ]
        keys_to_delete.extend(_obtiene_llaves_generales_cache())
        for key in keys_to_delete:
            cache.delete(key)
        bump_generacion_catalogo()
        log.trace(f"Cache invalidated for program: {program_code}")
    except Exception as e:
        log.error(f"Error invalidating cache for program {program_code}: {e}")


def invalidate_user_course_view_cache(usuario: str, course_code: str) -> None:
    """Drop a member's cached renders of a course's take and view pages.

    Both routes cache per user under ``cache_key_with_auth_state``
    (``view/<path>/user:<usuario>``), and nothing cleared those entries when
    enrollment state changed — so the ordinary sequence "look at a course,
    then enroll" redirected the member straight into their own stale
    pre-enrollment render: a phantom Enroll button, suppressed lesson links,
    and a second enrollment attempt (fork issue #50). Call this after ANY
    commit that changes a member's enrollment state: self-enrollment, payment
    confirmation, admin enrollment, unenrollment, program fan-out, API and
    bulk enrollment.

    Deleting a key that does not exist is a no-op, so callers do not need to
    know whether the member ever warmed the cache.
    """
    _elimina_vistas_por_usuario(usuario, [f"/course/{course_code}/take", f"/course/{course_code}/view"])
