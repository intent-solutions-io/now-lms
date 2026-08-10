# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Default custom pages must be correctable after the site language changes.

``crear_paginas_estaticas_predeterminadas`` (``now_lms/db/initial_data.py``)
resolves its titles and bodies from ``Configuracion.lang`` and then writes each
row behind an existence check::

    existing_about = database.session.execute(
        database.select(CustomPage).filter(CustomPage.slug == "about-us")
    ).scalar_one_or_none()

    if not existing_about:
        ...

It runs once, from ``initial_setup``, which does not re-run on a populated
database. So the language of About Us and Privacy Policy is decided at first boot
and no supported path could change it afterwards: ``lmsctl settings lang_set`` and
the admin settings form both move ``Configuracion.lang`` and neither touches the
rows. A deployment seeded in the wrong language kept a permanently wrong footer,
with no error and no log line.

``sincronizar_paginas_predeterminadas`` is the correction path. The load-bearing
constraint is what it refuses to do: ``custom_pages`` has no language column and
no edited flag, so byte equality against a shipped default is the only available
proof that a page has never been edited. A page that fails that test is reported
and left alone, so an administrator's own words survive the repair.
"""

ES_TITLES = {"about-us": "Sobre Nosotros", "privacy-policy": "Política de Privacidad"}
EN_TITLES = {"about-us": "About Us", "privacy-policy": "Privacy Policy"}


def _sembrar(lang):
    """Seed the default pages as a fresh install in ``lang`` would."""
    from now_lms.db import Configuracion, CustomPage, database
    from now_lms.db.initial_data import crear_paginas_estaticas_predeterminadas

    for slug in EN_TITLES:
        fila = database.session.execute(database.select(CustomPage).filter(CustomPage.slug == slug)).scalar_one_or_none()
        if fila is not None:
            database.session.delete(fila)
    database.session.commit()

    config = database.session.execute(database.select(Configuracion)).scalars().first()
    config.lang = lang
    database.session.commit()
    crear_paginas_estaticas_predeterminadas()


def _estados():
    from now_lms.db.initial_data import sincronizar_paginas_predeterminadas

    return {r["slug"]: r for r in sincronizar_paginas_predeterminadas()}


def _titulos():
    from now_lms.db import CustomPage, database

    filas = database.session.execute(database.select(CustomPage).filter(CustomPage.slug.in_(list(EN_TITLES)))).scalars()
    return {f.slug: f.title for f in filas}


def test_pages_seeded_in_another_language_are_reported_and_not_written(app):
    """The report names the stale pages, names the language they are in, and writes nothing."""
    from now_lms.db import Configuracion, database

    with app.app_context():
        _sembrar("en")
        assert _titulos() == EN_TITLES

        config = database.session.execute(database.select(Configuracion)).scalars().first()
        config.lang = "es"
        database.session.commit()

        estados = _estados()
        for slug in EN_TITLES:
            assert estados[slug]["estado"] == "desactualizada", f"{slug} was not detected as stale"
            assert estados[slug]["idioma"] == "en", f"{slug} did not report the language it is actually in"

        # The report is read-only. This is the whole point of running it against
        # a live deployment before deciding anything.
        assert _titulos() == EN_TITLES, "reporting rewrote the pages"


def test_apply_rewrites_untouched_defaults_into_the_configured_language(app):
    """--apply moves an untouched default to the configured language."""
    from now_lms.db import Configuracion, database
    from now_lms.db.initial_data import sincronizar_paginas_predeterminadas

    with app.app_context():
        _sembrar("en")
        config = database.session.execute(database.select(Configuracion)).scalars().first()
        config.lang = "es"
        database.session.commit()

        sincronizar_paginas_predeterminadas(aplicar=True)

        assert _titulos() == ES_TITLES, "the stale pages were not corrected"
        assert all(r["estado"] == "al-dia" for r in _estados().values()), "pages still report as stale after apply"


def test_an_edited_page_is_never_overwritten(app):
    """One character of local editing is enough to make a page untouchable."""
    from now_lms.db import Configuracion, CustomPage, database
    from now_lms.db.initial_data import sincronizar_paginas_predeterminadas

    with app.app_context():
        _sembrar("en")

        fila = database.session.execute(
            database.select(CustomPage).filter(CustomPage.slug == "about-us")
        ).scalar_one_or_none()
        fila.title = "About Intent Solutions"
        fila.content = fila.content + "<p>Written by us.</p>"
        database.session.commit()
        titulo_editado, contenido_editado = fila.title, fila.content

        config = database.session.execute(database.select(Configuracion)).scalars().first()
        config.lang = "es"
        database.session.commit()

        estados = _estados()
        assert estados["about-us"]["estado"] == "personalizada", "an edited page was not detected as edited"
        assert estados["privacy-policy"]["estado"] == "desactualizada", "the untouched page should still be correctable"

        sincronizar_paginas_predeterminadas(aplicar=True)

        fila = database.session.execute(
            database.select(CustomPage).filter(CustomPage.slug == "about-us")
        ).scalar_one_or_none()
        assert fila.title == titulo_editado, "apply overwrote an administrator's title"
        assert fila.content == contenido_editado, "apply overwrote an administrator's content"
        # The page beside it was still repaired, so this is not a blanket refusal.
        assert _titulos()["privacy-policy"] == ES_TITLES["privacy-policy"]


def test_a_missing_page_is_reported_and_recreated(app):
    """A deleted default reports as missing and is restored by --apply."""
    from now_lms.db import CustomPage, database
    from now_lms.db.initial_data import sincronizar_paginas_predeterminadas

    with app.app_context():
        _sembrar("en")
        fila = database.session.execute(
            database.select(CustomPage).filter(CustomPage.slug == "privacy-policy")
        ).scalar_one_or_none()
        database.session.delete(fila)
        database.session.commit()

        assert _estados()["privacy-policy"]["estado"] == "faltante"

        sincronizar_paginas_predeterminadas(aplicar=True)
        assert _titulos()["privacy-policy"] == EN_TITLES["privacy-policy"]


def test_seeding_output_is_unchanged_by_the_refactor(app):
    """The extracted accessor still produces exactly what the seeder writes.

    ``paginas_predeterminadas`` was lifted out of the seeder so the repair path
    could read the same copy. This pins the two together: if the accessor and the
    rows a fresh install produces ever diverge, the repair would start "fixing"
    pages to something the seeder never wrote.
    """
    from now_lms.db.initial_data import paginas_predeterminadas

    with app.app_context():
        for lang, esperado in (("en", EN_TITLES), ("es", ES_TITLES)):
            _sembrar(lang)
            defaults = paginas_predeterminadas(lang)
            filas = _titulos()
            assert filas == esperado
            for slug, pagina in defaults.items():
                assert filas[slug] == pagina["title"], f"{slug} title drifted from the accessor in {lang}"

        # An unknown language falls back to English, as the original resolution did.
        assert paginas_predeterminadas("fr") == paginas_predeterminadas("en")
