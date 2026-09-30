# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Private participant setup: tokens, page, click-to-accept ledger, jobs, CRM hand-off.

All people and addresses here are synthetic. Outbound mail and the CRM are replaced
with recorders; nothing leaves the process.
"""

import hashlib
import re
from datetime import timedelta

import pytest

import now_lms.vistas.participant_setup as page_module
from now_lms import crm_sync
from now_lms import setup_service as service
from now_lms.db import (
    AcceptanceImmutableError,
    AgreementAcceptance,
    SetupCase,
    SetupDraft,
    SetupJob,
    SetupToken,
    database,
    utc_now_naive,
)

AGREEMENT_MD = "# User Agreement\n\nSynthetic test terms. **Not** a real agreement.\n"
PDF_BYTES = b"%PDF-1.4\n% synthetic test agreement\n"

VALID_US = {
    "legal_given_names": "Ada María",
    "legal_family_names": "O’Neil-Lovelace",
    "country_code": "US",
    "address_line1": "100 Example Street",
    "address_line2": "Suite 4",
    "locality": "Springfield",
    "region": "MA",
    "postal_code": "01103",
    "phone": "(413) 555-0100",
}


@pytest.fixture(autouse=True)
def _reset_rate_buckets():
    page_module._RATE_BUCKETS.clear()
    yield
    page_module._RATE_BUCKETS.clear()


@pytest.fixture()
def agreement_files(app, tmp_path, monkeypatch):
    """Point the app at synthetic agreement files outside the repository."""
    text = tmp_path / "agreement.md"
    text.write_text(AGREEMENT_MD, encoding="utf-8")
    pdf = tmp_path / "agreement.pdf"
    pdf.write_bytes(PDF_BYTES)
    for key, value in {
        "SETUP_AGREEMENT_TEXT_PATH": str(text),
        "SETUP_AGREEMENT_PDF_PATH": str(pdf),
        "SETUP_AGREEMENT_DOCUMENT_ID": "test-user-agreement",
        "SETUP_AGREEMENT_VERSION": "2026-09-30-test",
        "SETUP_HELP_EMAIL": "help@example.org",
        "SETUP_BASE_URL": "https://learn.example.org",
    }.items():
        monkeypatch.setitem(app.config, key, value)
    return text, pdf


@pytest.fixture()
def recorders(monkeypatch):
    """Replace mail delivery and the CRM call with in-process recorders."""
    sent = []
    synced = []
    monkeypatch.setattr(service, "mail_ready", lambda: True)
    monkeypatch.setattr(service, "deliver_receipt", lambda case, acceptance: sent.append(acceptance.id))

    def _sync(acceptance, pinned_person_id=None):
        synced.append((acceptance.id, pinned_person_id))
        return crm_sync.SyncOutcome("done", "updated", "person-123")

    monkeypatch.setattr(crm_sync, "sync_acceptance", _sync)
    return sent, synced


@pytest.fixture()
def issued(db_session, agreement_files):
    """A fresh case and its plaintext token."""
    case, token = service.create_case(
        personal_email="Ada.Test@Example.org", display_name="Ada Test", known_phone="+1 413 555 0100"
    )
    return case, token


def _page(client, token):
    return client.get(f"/setup/{token}")


def _sha(client, token):
    body = _page(client, token).get_data(as_text=True)
    match = re.search(r'name="agreement_sha256" value="([0-9a-f]{64})"', body)
    assert match, "the setup page did not render the agreement hash"
    return match.group(1)


def _accept(client, token, sha=None, **overrides):
    data = dict(VALID_US, agree="y", action="accept", agreement_sha256=sha or _sha(client, token))
    data.update(overrides)
    return client.post(f"/setup/{token}", data=data)


# ---------------------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------------------
def test_token_is_stored_only_as_a_hash(db_session, issued):
    case, token = issued
    rows = db_session.execute(database.select(SetupToken).filter_by(case_id=case.id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_hash == service.hash_token(token)
    assert token not in rows[0].token_hash
    assert len(token) >= 40  # 32 random bytes, URL-safe


def test_email_is_normalised_on_the_case(issued):
    case, _token = issued
    assert case.personal_email == "ada.test@example.org"


def test_default_expiry_is_fourteen_days(db_session, issued):
    case, _token = issued
    row = db_session.execute(database.select(SetupToken).filter_by(case_id=case.id)).scalar_one()
    assert timedelta(days=13, hours=23) < row.expires_at - row.created_at <= timedelta(days=14)


def test_expiry_is_configurable(app, db_session, agreement_files, monkeypatch):
    monkeypatch.setitem(app.config, "SETUP_TOKEN_TTL_DAYS", "3")
    case, _token = service.create_case(personal_email="b@example.org", display_name="B")
    row = db_session.execute(database.select(SetupToken).filter_by(case_id=case.id)).scalar_one()
    assert row.expires_at - row.created_at <= timedelta(days=3)


def test_valid_token_renders_the_form(client, issued):
    _case, token = issued
    response = _page(client, token)
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Complete your setup" in body
    assert "Why we ask for these details" in body
    assert "https://intentsolutions.io/privacy/" in body
    assert service.ASSENT_TEXT in body
    assert "Accept agreement and complete setup" in body
    assert "Synthetic test terms" in body
    # The assent box is present and NOT prechecked.
    agree = re.search(r'<input type="checkbox" id="agree"[^>]*>', body).group(0)
    assert "checked" not in agree
    # Known phone is prefilled; the display name is never split into legal names.
    assert 'value="+1 413 555 0100"' in body
    assert 'id="legal_given_names" name="legal_given_names" autocomplete="given-name" maxlength="200" required value=""' in body


def test_page_is_private_and_loads_no_third_party_script(client, issued):
    _case, token = issued
    response = _page(client, token)
    body = response.get_data(as_text=True)
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "script-src 'nonce-" in csp
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "no-store" in response.headers["Cache-Control"]
    assert "noindex" in response.headers["X-Robots-Tag"]
    assert "u.js" not in body and "data-website-id" not in body
    assert not re.search(r'<script[^>]+src=', body)
    assert "googlesyndication" not in body


def test_wrong_token_is_rejected(client, issued):
    response = client.get("/setup/not-a-real-token")
    assert response.status_code == 404
    assert "This setup link is not valid" in response.get_data(as_text=True)
    assert "help@example.org" in response.get_data(as_text=True)


def test_expired_token_shows_a_clear_message(client, db_session, issued):
    case, token = issued
    row = db_session.execute(database.select(SetupToken).filter_by(case_id=case.id)).scalar_one()
    row.expires_at = utc_now_naive() - timedelta(minutes=1)
    db_session.commit()
    response = _page(client, token)
    assert response.status_code == 410
    assert "This setup link has expired" in response.get_data(as_text=True)
    assert _accept(client, token, sha="0" * 64).status_code == 410


def test_reissue_revokes_the_old_link(client, db_session, issued):
    case, old = issued
    new = service.reissue_token(case)
    assert _page(client, old).status_code == 404
    assert _page(client, new).status_code == 200


def test_token_is_single_use(client, db_session, issued, recorders):
    case, token = issued
    assert _accept(client, token).status_code == 302
    again = _page(client, token)
    assert again.status_code == 200
    assert "Your agreement is recorded" in again.get_data(as_text=True)
    assert 'name="action"' not in again.get_data(as_text=True)
    with pytest.raises(ValueError):
        service.reissue_token(db_session.get(SetupCase, case.id))


def test_unconfigured_agreement_blocks_acceptance(app, client, db_session, monkeypatch):
    case, token = service.create_case(personal_email="c@example.org", display_name="C")
    monkeypatch.setitem(app.config, "SETUP_AGREEMENT_TEXT_PATH", "")
    monkeypatch.delenv("SETUP_AGREEMENT_TEXT_PATH", raising=False)
    assert _page(client, token).status_code == 503


# ---------------------------------------------------------------------------------------
# Save and resume
# ---------------------------------------------------------------------------------------
def test_save_keeps_a_draft_and_is_not_acceptance(client, db_session, issued):
    case, token = issued
    response = client.post(f"/setup/{token}", data={"action": "save", "legal_given_names": "Zoë", "country_code": "DE"})
    assert response.status_code == 200
    assert "Saved" in response.get_data(as_text=True)
    draft = db_session.execute(database.select(SetupDraft).filter_by(case_id=case.id)).scalar_one()
    assert draft.data["legal_given_names"] == "Zoë"
    assert db_session.execute(database.select(AgreementAcceptance)).first() is None
    resumed = _page(client, token).get_data(as_text=True)
    assert 'value="Zoë"' in resumed
    assert '<option value="DE" selected>' in resumed


# ---------------------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------------------
def test_acceptance_records_the_full_evidence(client, db_session, issued, recorders, agreement_files):
    case, token = issued
    sha = _sha(client, token)
    response = client.post(
        f"/setup/{token}",
        data=dict(VALID_US, agree="y", action="accept", agreement_sha256=sha, whatsapp_permission="y"),
        headers={"User-Agent": "SyntheticBrowser/1.0"},
    )
    assert response.status_code == 302
    acc = db_session.execute(database.select(AgreementAcceptance).filter_by(case_id=case.id)).scalar_one()
    assert acc.legal_given_names == "Ada María"
    assert acc.legal_family_names == "O’Neil-Lovelace"
    assert acc.legal_full_name == "Ada María O’Neil-Lovelace"
    assert acc.postal_code == "01103"  # leading zero preserved
    assert acc.region == "MA"
    assert acc.phone_e164 == "+14135550100"
    assert acc.whatsapp_permission is True
    assert acc.agreement_document_id == "test-user-agreement"
    assert acc.agreement_version == "2026-09-30-test"
    text, pdf = agreement_files
    assert acc.agreement_sha256 == hashlib.sha256(text.read_bytes()).hexdigest() == sha
    assert acc.agreement_pdf_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert acc.assent_text == service.ASSENT_TEXT
    assert acc.assent_text_version == service.ASSENT_TEXT_VERSION
    assert acc.user_agent == "SyntheticBrowser/1.0"
    assert acc.ip_address
    assert acc.accepted_at_utc <= utc_now_naive()
    assert db_session.get(SetupCase, case.id).status in ("agreement_accepted", "release_pending")
    assert db_session.execute(database.select(SetupDraft).filter_by(case_id=case.id)).first() is None


def test_whatsapp_permission_is_optional_and_separate(client, db_session, issued, recorders):
    case, token = issued
    assert _accept(client, token).status_code == 302
    acc = db_session.execute(database.select(AgreementAcceptance).filter_by(case_id=case.id)).scalar_one()
    assert acc.whatsapp_permission is False


def test_unchecked_assent_box_blocks_acceptance(client, db_session, issued, recorders):
    _case, token = issued
    response = _accept(client, token, agree="")
    assert response.status_code == 422
    assert "Tick the box" in response.get_data(as_text=True)
    assert db_session.execute(database.select(AgreementAcceptance)).first() is None


def test_changed_agreement_file_requires_a_fresh_review(client, db_session, issued, recorders, agreement_files):
    _case, token = issued
    sha = _sha(client, token)
    agreement_files[0].write_text(AGREEMENT_MD + "\nAmended clause.\n", encoding="utf-8")
    response = _accept(client, token, sha=sha)
    assert response.status_code == 422
    assert "agreement was updated" in response.get_data(as_text=True)
    assert db_session.execute(database.select(AgreementAcceptance)).first() is None


def test_double_submit_is_idempotent(client, db_session, issued, recorders):
    case, token = issued
    sha = _sha(client, token)
    first = _accept(client, token, sha=sha)
    second = _accept(client, token, sha=sha)
    assert first.status_code == 302
    assert second.status_code == 200  # the used link shows the completed state
    assert len(db_session.execute(database.select(AgreementAcceptance).filter_by(case_id=case.id)).all()) == 1
    sent, synced = recorders
    assert len(sent) == 1 and len(synced) == 1


def test_record_acceptance_replay_returns_the_existing_row(db_session, issued, recorders):
    case, token = issued
    lookup = service.lookup_token(token)
    agreement = service.load_agreement()
    values = {
        "legal_given_names": "Ada",
        "legal_family_names": "Test",
        "legal_full_name": "Ada Test",
        "single_name": False,
        "country_code": "GB",
        "address_line1": "1 Example Road",
        "address_line2": None,
        "locality": "London",
        "region": None,
        "postal_code": "SW1A 1AA",
        "phone_e164": "+442079460958",
        "whatsapp_permission": False,
    }
    first, created = service.record_acceptance(
        token_row=lookup.token, case=lookup.case, values=values, agreement=agreement, ip_address="192.0.2.1", user_agent="t"
    )
    again, created_again = service.record_acceptance(
        token_row=lookup.token, case=db_session.get(SetupCase, case.id), values=values, agreement=agreement,
        ip_address="192.0.2.1", user_agent="t",
    )
    assert created is True and created_again is False
    assert first.id == again.id
    jobs = db_session.execute(database.select(SetupJob).filter_by(case_id=case.id)).scalars().all()
    assert sorted(job.kind for job in jobs) == ["crm_sync", "receipt_email"]


def test_acceptance_is_immutable(client, db_session, issued, recorders):
    case, token = issued
    _accept(client, token)
    acc = db_session.execute(database.select(AgreementAcceptance).filter_by(case_id=case.id)).scalar_one()
    acc.legal_given_names = "Someone Else"
    with pytest.raises(AcceptanceImmutableError):
        db_session.flush()
    db_session.rollback()
    acc = db_session.execute(database.select(AgreementAcceptance).filter_by(case_id=case.id)).scalar_one()
    db_session.delete(acc)
    with pytest.raises(AcceptanceImmutableError):
        db_session.flush()
    db_session.rollback()
    assert db_session.get(AgreementAcceptance, acc.id).legal_given_names == "Ada María"


def test_acceptance_is_immutable_in_postgresql_itself(client, db_session, issued, recorders):
    if db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("the database trigger exists on PostgreSQL only")
    from sqlalchemy.exc import DBAPIError

    case, token = issued
    _accept(client, token)
    with pytest.raises(DBAPIError):
        db_session.execute(
            database.text("UPDATE agreement_acceptance SET legal_given_names = 'x' WHERE case_id = :c"), {"c": case.id}
        )
    db_session.rollback()


# ---------------------------------------------------------------------------------------
# Follow-up jobs: receipt, CRM, release
# ---------------------------------------------------------------------------------------
def test_receipt_is_sent_once_and_release_is_enqueued(client, db_session, issued, recorders):
    case, token = issued
    _accept(client, token)
    sent, _synced = recorders
    assert len(sent) == 1
    # A later runner pass (cron) must not resend.
    service.process_due_jobs()
    service.process_due_jobs()
    assert len(sent) == 1
    receipt = db_session.execute(database.select(SetupJob).filter_by(case_id=case.id, kind="receipt_email")).scalar_one()
    release = db_session.execute(database.select(SetupJob).filter_by(case_id=case.id, kind="release")).scalar_one()
    assert receipt.status == "done"
    assert release.status == "release_pending"
    assert db_session.get(SetupCase, case.id).status == "release_pending"


def test_receipt_failure_is_retried_later_without_losing_anything(client, db_session, issued, recorders, monkeypatch):
    case, token = issued
    calls = []

    def _boom(case_, acceptance):
        calls.append(1)
        raise ConnectionError("smtp down for rcpt ada.test@example.org")

    monkeypatch.setattr(service, "deliver_receipt", _boom)
    _accept(client, token)
    job = db_session.execute(database.select(SetupJob).filter_by(case_id=case.id, kind="receipt_email")).scalar_one()
    assert job.status == "pending" and job.attempts == 1
    assert "example.org" not in (job.last_error or "")  # PII-free error record
    assert db_session.execute(database.select(SetupJob).filter_by(case_id=case.id, kind="release")).first() is None
    assert db_session.get(SetupCase, case.id).status == "agreement_accepted"
    # Not due yet: back-off holds it.
    service.process_due_jobs()
    assert len(calls) == 1
    # When due and mail works again, it is sent exactly once and release follows.
    job.next_attempt_at = utc_now_naive() - timedelta(seconds=1)
    db_session.commit()
    sent = []
    monkeypatch.setattr(service, "deliver_receipt", lambda c, a: sent.append(a.id))
    service.process_due_jobs()
    service.process_due_jobs()
    assert len(sent) == 1
    assert db_session.get(SetupCase, case.id).status == "release_pending"


def test_crm_failure_never_loses_the_acceptance(client, db_session, issued, recorders, monkeypatch):
    case, token = issued

    def _explode(acceptance, pinned_person_id=None):
        raise RuntimeError("crm exploded")

    monkeypatch.setattr(crm_sync, "sync_acceptance", _explode)
    assert _accept(client, token).status_code == 302
    assert db_session.execute(database.select(AgreementAcceptance).filter_by(case_id=case.id)).scalar_one()
    job = db_session.execute(database.select(SetupJob).filter_by(case_id=case.id, kind="crm_sync")).scalar_one()
    assert job.status == "pending" and job.next_attempt_at is not None
    assert job.last_error == "unexpected: RuntimeError"


def test_crm_ambiguity_goes_to_failed_work(client, db_session, issued, recorders, monkeypatch):
    case, token = issued
    monkeypatch.setattr(
        crm_sync, "sync_acceptance", lambda a, pinned_person_id=None: crm_sync.SyncOutcome("needs_review", "2 people")
    )
    _accept(client, token)
    failed = service.failed_work()
    assert [(job.case_id, job.kind, job.status) for job in failed] == [(case.id, "crm_sync", "needs_review")]


def test_crm_success_records_the_person_id(client, db_session, issued, recorders):
    case, token = issued
    _accept(client, token)
    assert db_session.get(SetupCase, case.id).person_ref == "person-123"
    job = db_session.execute(database.select(SetupJob).filter_by(case_id=case.id, kind="crm_sync")).scalar_one()
    assert job.status == "done"


def test_jobs_give_up_after_max_attempts(client, db_session, issued, recorders, monkeypatch):
    case, token = issued
    monkeypatch.setattr(
        crm_sync, "sync_acceptance", lambda a, pinned_person_id=None: crm_sync.SyncOutcome("retry", "lookup: HTTP 503")
    )
    _accept(client, token)
    job = db_session.execute(database.select(SetupJob).filter_by(case_id=case.id, kind="crm_sync")).scalar_one()
    for _ in range(service.JOB_MAX_ATTEMPTS):
        job.next_attempt_at = None
        db_session.commit()
        service.process_due_jobs()
        db_session.refresh(job)
    assert job.status == "failed"
    service.requeue(job)
    assert job.status == "pending" and job.attempts == 0


def test_receipt_message_carries_the_summary_and_pdf(client, db_session, issued, recorders, app):
    case, token = issued
    _accept(client, token)
    acc = db_session.execute(database.select(AgreementAcceptance).filter_by(case_id=case.id)).scalar_one()
    with app.test_request_context():
        msg = service._build_receipt(db_session.get(SetupCase, case.id), acc)
    assert msg.recipients == ["ada.test@example.org"]
    assert "2026-09-30-test" in msg.body and "test-user-agreement" in msg.body
    assert "Ada María O’Neil-Lovelace" in msg.body
    assert acc.id in msg.html
    assert len(msg.attachments) == 1 and msg.attachments[0].data == PDF_BYTES


def test_pdf_download_is_behind_the_token(client, issued):
    _case, token = issued
    response = client.get(f"/setup/{token}/agreement.pdf")
    assert response.status_code == 200
    assert response.data == PDF_BYTES
    assert response.headers["Content-Type"] == "application/pdf"
    assert client.get("/setup/wrong-token/agreement.pdf").status_code == 404


# ---------------------------------------------------------------------------------------
# Transport-level protections
# ---------------------------------------------------------------------------------------
def test_csrf_is_enforced(app, client, issued, recorders, monkeypatch):
    _case, token = issued
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    response = client.post(f"/setup/{token}", data=dict(VALID_US, agree="y", action="accept", agreement_sha256="0" * 64))
    assert response.status_code == 400
    assert "session expired" in response.get_data(as_text=True)


def test_posts_are_rate_limited(client, issued, monkeypatch):
    _case, token = issued
    monkeypatch.setattr(page_module, "_RATE_LIMIT_EVENTS", 2)
    for _ in range(2):
        client.post(f"/setup/{token}", data={"action": "save"})
    assert client.post(f"/setup/{token}", data={"action": "save"}).status_code == 429


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------
def test_cli_issue_list_reissue(app, db_session, agreement_files):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["setup", "issue", "--email", "Grace@Example.org", "--name", "Grace", "--expiry-days", "7"])
    assert result.exit_code == 0, result.output
    link = re.search(r"https://learn\.example\.org/setup/(\S+)", result.output)
    assert link
    case = db_session.execute(database.select(SetupCase).filter_by(personal_email="grace@example.org")).scalar_one()
    assert service.lookup_token(link.group(1)).state == "valid"
    # Duplicate open case is refused.
    dup = runner.invoke(args=["setup", "issue", "--email", "grace@example.org", "--name", "Grace"])
    assert dup.exit_code != 0 and "already pending" in dup.output
    listing = runner.invoke(args=["setup", "list"])
    assert case.id in listing.output and "setup_pending" in listing.output
    assert "grace@example.org" not in listing.output  # masked by default
    again = runner.invoke(args=["setup", "reissue", case.id])
    assert again.exit_code == 0, again.output
    new_token = re.search(r"/setup/(\S+)", again.output).group(1)
    assert service.lookup_token(link.group(1)).state == "revoked"
    assert service.lookup_token(new_token).state == "valid"


def test_cli_issue_requires_a_base_url(app, db_session, agreement_files, monkeypatch):
    monkeypatch.setitem(app.config, "SETUP_BASE_URL", "")
    monkeypatch.delenv("SETUP_BASE_URL", raising=False)
    result = app.test_cli_runner().invoke(args=["setup", "issue", "--email", "x@example.org", "--name", "X"])
    assert result.exit_code != 0
    assert db_session.execute(database.select(SetupCase)).first() is None
