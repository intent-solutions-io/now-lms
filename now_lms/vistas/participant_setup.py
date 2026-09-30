# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.
"""Private participant setup page: ``/setup/<token>``.

Fork-local blueprint. One mobile-first page, reached only through a single-person
expiring link, where an admitted applicant reads a short explanation, confirms their
legal name, mailing address and phone, reads the full agreement and accepts it with
an unchecked box and an explicit button. Save-and-resume keeps a server-side draft.

Security posture: the token is the only credential and is stored hashed; the case
is always resolved server-side from it (never from anything the browser sends);
CSRF via Flask-WTF; a per-IP POST limit; a strict nonce CSP with no analytics or
third-party script; ``no-store`` and ``no-referrer`` so the link does not leak into
caches or referrers. Nothing here logs personal data or tokens.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------------------
import secrets
import threading
from collections import deque
from time import time

# ---------------------------------------------------------------------------------------
# Third-party libraries
# ---------------------------------------------------------------------------------------
from flask import Blueprint, abort, current_app, make_response, redirect, render_template, request, send_file, url_for
from flask_wtf import FlaskForm
from werkzeug.wrappers import Response
from wtforms import BooleanField, HiddenField, StringField

# ---------------------------------------------------------------------------------------
# Local resources
# ---------------------------------------------------------------------------------------
from now_lms import setup_service as service
from now_lms.config import DIRECTORIO_PLANTILLAS
from now_lms.i18n import _
from now_lms.logs import log
from now_lms.setup_validation import (
    address_rule,
    address_rules_for_client,
    clean_text,
    country_choices,
    validate_address,
    validate_names,
    validate_phone,
)

participant_setup = Blueprint("participant_setup", __name__, template_folder=DIRECTORIO_PLANTILLAS)

TEMPLATE = "themes/intent_learn/pages/participant_setup.html"
PRIVACY_URL = "https://intentsolutions.io/privacy/"

DRAFT_FIELDS = (
    "legal_given_names",
    "legal_family_names",
    "single_name",
    "country_code",
    "address_line1",
    "address_line2",
    "locality",
    "region",
    "postal_code",
    "phone",
    "whatsapp_permission",
)
DRAFT_TEXT_MAX = 250

# In-process sliding-window limit for POSTs and unknown-token GETs, per client IP.
# Same reasoning as vistas/request_access.py: the repo's check_rate_limit helper is a
# no-op under NullCache (production), waitress is single-process, Caddy is the outer wall.
_RATE_LIMIT_EVENTS = 20
_RATE_LIMIT_WINDOW = 900  # seconds
_RATE_MAX_BUCKETS = 10_000
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[str, deque] = {}


class SetupForm(FlaskForm):
    """CSRF carrier and field names. Validation lives in now_lms.setup_validation."""

    legal_given_names = StringField()
    legal_family_names = StringField()
    single_name = BooleanField()
    country_code = StringField()
    address_line1 = StringField()
    address_line2 = StringField()
    locality = StringField()
    region = StringField()
    postal_code = StringField()
    phone = StringField()
    whatsapp_permission = BooleanField()
    agree = BooleanField()
    agreement_sha256 = HiddenField()
    action = HiddenField()


def _rate_limited(ip: str) -> bool:
    """True when this IP exceeded the window. Memory is hard-capped."""
    now = time()
    with _RATE_LOCK:
        bucket = _RATE_BUCKETS.setdefault(ip, deque())
        while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT_EVENTS:
            return True
        bucket.append(now)
        if len(_RATE_BUCKETS) > _RATE_MAX_BUCKETS:
            oldest = sorted(_RATE_BUCKETS.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)
            for key, _bucket in oldest[: len(_RATE_BUCKETS) - _RATE_MAX_BUCKETS]:
                if key != ip:
                    del _RATE_BUCKETS[key]
        return False


def _private(response: Response, nonce: str | None = None) -> Response:
    """Headers for a page whose URL is a credential."""
    script_src = f"'nonce-{nonce}'" if nonce else "'none'"
    style_src = f"'nonce-{nonce}'" if nonce else "'none'"
    response.headers["Content-Security-Policy"] = (
        f"default-src 'none'; script-src {script_src}; style-src {style_src}; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def _render(state: str, status: int = 200, **context) -> Response:
    nonce = secrets.token_urlsafe(16)
    html = render_template(
        TEMPLATE,
        state=state,
        nonce=nonce,
        privacy_url=PRIVACY_URL,
        help_email=service.setting("SETUP_HELP_EMAIL"),
        **context,
    )
    return _private(make_response(html, status), nonce)


def _message_state(lookup: service.TokenLookup) -> Response:
    """Render the right explanation for a token that cannot be used for setup."""
    if lookup.state == "used":
        acceptance = service.acceptance_for(lookup.case) if lookup.case else None
        return _render("completed", 200, acceptance=acceptance)
    if lookup.state == "expired":
        return _render("expired", 410)
    return _render("invalid", 404)


def _form_values(source) -> dict:
    """Pull the draftable fields from a form or dict, bounded and cleaned."""
    values: dict[str, str | bool] = {}
    for name in DRAFT_FIELDS:
        raw = source.get(name)
        if name in ("single_name", "whatsapp_permission"):
            values[name] = raw in (True, "y", "on", "1", "true")
        else:
            values[name] = clean_text(raw)[:DRAFT_TEXT_MAX]
    return values


def _page(lookup, agreement, values, errors=None, notice=None, status=200) -> Response:
    country = values.get("country_code") or ""
    return _render(
        "form",
        status,
        case=lookup.case,
        token=lookup.presented,
        agreement=agreement,
        values=values,
        errors=errors or {},
        notice=notice,
        form=SetupForm(formdata=None),
        countries=country_choices(current_app.config.get("BABEL_DEFAULT_LOCALE", "en") or "en"),
        rule=address_rule(country) if country else None,
        address_rules=address_rules_for_client(),
        assent_text=service.ASSENT_TEXT,
        accept_label=service.ACCEPT_BUTTON_LABEL,
        expires_at=lookup.token.expires_at,
    )


def _initial_values(case) -> dict:
    """Draft first; otherwise only unambiguous known values (never a split name)."""
    draft = service.load_draft(case)
    if draft:
        return _form_values(draft)
    return _form_values({"phone": case.known_phone or ""})


def _validate_for_acceptance(values: dict) -> tuple[dict, dict]:
    names = validate_names(values["legal_given_names"], values["legal_family_names"], values["single_name"])
    address = validate_address(
        values["country_code"],
        values["address_line1"],
        values["address_line2"],
        values["locality"],
        values["region"],
        values["postal_code"],
    )
    phone = validate_phone(values["phone"], values["country_code"])
    errors = {**names.errors, **address.errors, **phone.errors}
    clean = {**names.values, **address.values, **phone.values, "whatsapp_permission": values["whatsapp_permission"]}
    return clean, errors


def _dispatch_follow_up(case_id: str) -> None:
    """Run the receipt and CRM jobs now, off the request thread in production.

    The jobs are already durable rows; this is only the fast path. If it fails or the
    process dies, ``lmsctl setup process-jobs`` picks the rows up.
    """
    if current_app.testing or current_app.config.get("SETUP_INLINE_JOBS"):
        service.process_due_jobs(case_id)
        return
    app = current_app._get_current_object()  # pylint: disable=protected-access

    def _work():
        with app.app_context():
            try:
                service.process_due_jobs(case_id)
            except Exception as error:  # pylint: disable=broad-exception-caught
                log.error(f"Setup follow-up for case {case_id} deferred to the job runner: {type(error).__name__}")

    threading.Thread(target=_work, name="setup-follow-up", daemon=True).start()


@participant_setup.route("/setup/<token>", methods=["GET", "POST"])
def setup_page(token: str) -> Response:
    """The single private setup page."""
    ip = request.remote_addr or "unknown"
    if request.method == "POST" and _rate_limited(ip):
        return _render("rate_limited", 429)

    lookup = service.lookup_token(token)
    if lookup.state != "valid" or lookup.case is None or lookup.token is None:
        if request.method == "GET" and lookup.state == "unknown" and _rate_limited(ip):
            return _render("rate_limited", 429)
        return _message_state(lookup)
    case, token_row = lookup.case, lookup.token

    agreement = service.load_agreement()
    if agreement is None:
        return _render("unavailable", 503)

    if request.method == "GET":
        return _page(lookup, agreement, _initial_values(case))

    form = SetupForm()
    values = _form_values(request.form)
    if not form.validate_on_submit():
        return _page(lookup, agreement, values, notice=_("Your session expired. Please submit the page again."), status=400)

    if form.action.data == "save":
        service.save_draft(case, values)
        return _page(lookup, agreement, values, notice=_("Saved. You can return to this link later to finish."))

    clean, errors = _validate_for_acceptance(values)
    if not form.agree.data:
        errors["agree"] = _("Tick the box to confirm you agree before accepting.")
    if form.agreement_sha256.data != agreement.sha256:
        errors["agreement"] = _(
            "The agreement was updated after you opened this page. Please review the current version, then accept again."
        )
    if errors:
        service.save_draft(case, values)
        return _page(lookup, agreement, values, errors=errors, status=422)

    acceptance, created = service.record_acceptance(
        token_row=token_row,
        case=case,
        values=clean,
        agreement=agreement,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    if created and acceptance is not None:
        _dispatch_follow_up(acceptance.case_id)
    return _private(redirect(url_for("participant_setup.setup_page", token=token)))


@participant_setup.route("/setup/<token>/agreement.pdf", methods=["GET"])
def agreement_pdf(token: str) -> Response:
    """Download the configured agreement PDF, behind the same token."""
    lookup = service.lookup_token(token)
    if lookup.state not in ("valid", "used"):
        if lookup.state == "unknown" and _rate_limited(request.remote_addr or "unknown"):
            abort(429)
        abort(404)
    agreement = service.load_agreement()
    if agreement is None or agreement.pdf_path is None:
        abort(404)
    response = send_file(
        agreement.pdf_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"user-agreement-{agreement.version}.pdf",
        max_age=0,
    )
    return _private(response)
