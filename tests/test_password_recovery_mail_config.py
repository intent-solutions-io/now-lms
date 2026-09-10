# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.
"""Regression coverage for password recovery with environment SMTP settings."""

import pytest

from now_lms.auth import proteger_passwd
from now_lms.db import MailConfig, Usuario
from now_lms.vistas import users as users_module

MAIL_ENV_KEYS = (
    "MAIL_SERVER",
    "MAIL_PORT",
    "MAIL_USERNAME",
    "MAIL_PASSWORD",
    "MAIL_DEFAULT_SENDER",
    "MAIL_DEFAULT_SENDER_NAME",
    "MAIL_USE_TLS",
    "MAIL_USE_SSL",
)


def _clear_mail_environment(monkeypatch) -> None:
    for key in MAIL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _configure_mail_environment(monkeypatch) -> None:
    _clear_mail_environment(monkeypatch)
    monkeypatch.setenv("MAIL_SERVER", "smtp.example.invalid")
    monkeypatch.setenv("MAIL_PORT", "465")
    monkeypatch.setenv("MAIL_USERNAME", "postmaster@example.invalid")
    monkeypatch.setenv("MAIL_PASSWORD", "test-password")
    monkeypatch.setenv("MAIL_DEFAULT_SENDER", "learn@example.invalid")
    monkeypatch.setenv("MAIL_USE_TLS", "False")
    monkeypatch.setenv("MAIL_USE_SSL", "True")


def _verified_user(db_session) -> Usuario:
    user = Usuario(
        usuario="recovery-member",
        acceso=proteger_passwd("password"),
        nombre="Recovery",
        correo_electronico="recovery@example.com",
        correo_electronico_verificado=True,
        tipo="student",
        activo=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_login_shows_recovery_when_environment_mail_is_configured(app, client, monkeypatch):
    """An empty MailConfig row must not hide an environment-configured recovery flow."""
    _configure_mail_environment(monkeypatch)

    response = client.get("/user/login")

    assert response.status_code == 200
    assert b"/user/forgot_password" in response.data


def test_verified_user_receives_recovery_message_with_environment_mail(app, db_session, monkeypatch):
    """The database row is optional when deployment SMTP is configured."""
    user = _verified_user(db_session)
    sent_to = []
    _configure_mail_environment(monkeypatch)
    monkeypatch.setattr("now_lms.auth.send_password_reset_email", lambda recipient: sent_to.append(recipient) or True)

    with app.test_request_context():
        users_module._send_password_reset_message(user)

    assert sent_to == [user]


@pytest.mark.parametrize("database_mail_verified", (False, True))
def test_environment_mail_overrides_database_configuration(app, client, db_session, monkeypatch, database_mail_verified):
    """The effective environment configuration takes precedence over database fallback."""
    _configure_mail_environment(monkeypatch)
    db_session.add(MailConfig(email_verificado=database_mail_verified))
    db_session.commit()

    response = client.get("/user/login")

    assert response.status_code == 200
    assert b"/user/forgot_password" in response.data


def test_unverified_database_mail_configuration_keeps_recovery_disabled(app, client, db_session, monkeypatch):
    """Database fallback retains the administrator verification gate."""
    _clear_mail_environment(monkeypatch)
    user = _verified_user(db_session)
    db_session.add(MailConfig(email_verificado=False))
    db_session.commit()
    sent_to = []
    monkeypatch.setattr("now_lms.auth.send_password_reset_email", lambda recipient: sent_to.append(recipient) or True)

    response = client.get("/user/login")
    with app.test_request_context():
        users_module._send_password_reset_message(user)

    assert response.status_code == 200
    assert b"/user/forgot_password" not in response.data
    assert sent_to == []


def test_partial_environment_mail_configuration_keeps_recovery_disabled(app, client, monkeypatch):
    """A partial environment configuration must not advertise an unusable recovery path."""
    _clear_mail_environment(monkeypatch)
    monkeypatch.setenv("MAIL_SERVER", "smtp.example.invalid")
    monkeypatch.setenv("MAIL_PORT", "465")

    response = client.get("/user/login")

    assert response.status_code == 200
    assert b"/user/forgot_password" not in response.data


def test_absent_mail_configuration_keeps_recovery_disabled(app, client, db_session, monkeypatch):
    """Without an environment or verified database configuration, no mail is sent."""
    _clear_mail_environment(monkeypatch)
    user = _verified_user(db_session)
    sent_to = []
    monkeypatch.setattr("now_lms.auth.send_password_reset_email", lambda recipient: sent_to.append(recipient) or True)

    response = client.get("/user/login")
    with app.test_request_context():
        users_module._send_password_reset_message(user)

    assert response.status_code == 200
    assert b"/user/forgot_password" not in response.data
    assert sent_to == []
