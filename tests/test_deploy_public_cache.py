# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.
"""Reproduce stale public responses across releases without touching member state."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from flask import Flask
from flask_login import LoginManager

from now_lms.cache import cache, cache_key_with_auth_state

SPEC = spec_from_file_location("refresh_public_cache", Path(__file__).parents[1] / "scripts/refresh_public_cache.py")
refresh_module = module_from_spec(SPEC)
SPEC.loader.exec_module(refresh_module)


@pytest.fixture()
def public_app():
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test-only", CACHE_TYPE="SimpleCache", RELEASE="old")
    login = LoginManager(app)
    login.user_loader(lambda _id: None)
    cache.init_app(app)

    @cache.cached(timeout=300, key_prefix=cache_key_with_auth_state)
    def public_page():
        return app.config["RELEASE"]

    for index, path in enumerate(refresh_module.PUBLIC_PATHS):
        app.add_url_rule(path, f"public_{index}", public_page)
    return app


def test_deployment_retires_stale_public_responses_and_preserves_other_state(public_app):
    client = public_app.test_client()
    for path in refresh_module.PUBLIC_PATHS:
        assert client.get(path).data == b"old"
    # This is the production failure: a new renderer alone does not replace
    # previously cached responses on ordinary URLs.
    public_app.config["RELEASE"] = "new"
    for path in refresh_module.PUBLIC_PATHS:
        assert client.get(path).data == b"old"

    with public_app.app_context():
        preserved = ("session:member", "view///user:member/g0", "view//course/private/view/anon/g0")
        for key in preserved:
            cache.set(key, "keep")
    # Query variants intentionally remain outside the bounded plain-URL refresh.
    assert client.get("/?page=2").data == b"new"
    public_app.config["RELEASE"] = "latest"

    refresh_module.refresh_public_cache(public_app)

    for path in refresh_module.PUBLIC_PATHS:
        assert client.get(path).data == b"latest"
    assert client.get("/?page=2").data == b"new"
    with public_app.app_context():
        for key in preserved:
            assert cache.get(key) == "keep"


def test_refresh_refuses_authenticated_context(public_app):
    from flask_login import UserMixin

    public_app.login_manager.request_loader(lambda _request: UserMixin())
    with pytest.raises(RuntimeError, match="anonymous context"):
        refresh_module.refresh_public_cache(public_app)


def test_public_theme_renders_the_image_release_fragment():
    from types import SimpleNamespace

    from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

    marker = '<meta name="intent-learn-release" content="fixture-release" />'
    templates = Path(__file__).parents[1] / "now_lms/templates"
    env = Environment(loader=ChoiceLoader([
        DictLoader({"themes/intent_learn/release.j2": marker}),
        FileSystemLoader(templates),
    ]))
    env.globals.update(
        _=lambda text: text,
        config=lambda: SimpleNamespace(titulo_html="Fixture"),
        url_for=lambda *args, **kwargs: "/static/fixture",
        adsense_meta=lambda: "",
        adsense_code=lambda: "",
    )
    assert marker in env.get_template("themes/intent_learn/header.j2").module.headertags()
