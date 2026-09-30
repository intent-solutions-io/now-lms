# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.
"""Private participant setup: tokens, drafts, click-to-accept ledger and follow-up jobs.

The durability boundary is the acceptance commit. One transaction writes the
immutable acceptance, marks the token used, moves the case to
``agreement_accepted``, deletes the draft and enqueues the follow-up jobs. Everything
after that (receipt email, CRM hand-off, release enqueue) runs from those job rows,
claimed atomically and retried with back-off, so an outage in mail or the CRM can
delay a step but never lose an acceptance or repeat a completed step.

Nothing here logs personal data or tokens: log lines carry case/job ids only.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------------------
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from os import environ
from pathlib import Path

# ---------------------------------------------------------------------------------------
# Third-party libraries
# ---------------------------------------------------------------------------------------
from flask import current_app, render_template
from markupsafe import Markup, escape
from sqlalchemy.exc import IntegrityError

# ---------------------------------------------------------------------------------------
# Local resources
# ---------------------------------------------------------------------------------------
from now_lms import crm_sync
from now_lms.db import (
    AgreementAcceptance,
    SetupCase,
    SetupDraft,
    SetupJob,
    SetupToken,
    database,
    utc_now_naive,
)
from now_lms.i18n import _
from now_lms.logs import log

DEFAULT_TOKEN_TTL_DAYS = 14
MAX_TOKEN_TTL_DAYS = 90
TOKEN_BYTES = 32

# Exact assent wording and its version. Deliberately NOT passed through gettext: the
# recorded text must be byte-for-byte what was shown, and changing it means bumping
# the version so older acceptances stay attributable to the wording they saw.
ASSENT_TEXT_VERSION = "assent-2026-09-29-v1"
ASSENT_TEXT = (
    "I have had the opportunity to review and download the User Agreement and the applicable documents "
    "listed with it. I agree to these terms and intend this action to be my electronic signature."
)
ACCEPT_BUTTON_LABEL = "Accept agreement and complete setup"
# Version of the "what you are joining" explanation and collection notice shown on
# the page (the copy lives in the theme template). Bump when that copy changes.
EXPLANATION_VERSION = "explanation-2026-09-29-v1"

JOB_MAX_ATTEMPTS = 10
JOB_BASE_DELAY = timedelta(minutes=5)
JOB_MAX_DELAY = timedelta(hours=6)
JOB_STALE_SENDING = timedelta(minutes=30)
RECEIPT_TEXT_TEMPLATE = "themes/intent_learn/email/setup_receipt.txt"
RECEIPT_HTML_TEMPLATE = "themes/intent_learn/email/setup_receipt.html"

_HTML_ALLOWED_TAGS = [
    "a", "abbr", "b", "blockquote", "br", "code", "dd", "div", "dl", "dt", "em", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "i", "li", "ol", "p", "pre", "section", "small", "span", "strong", "sub", "sup",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
]  # fmt: skip
_HTML_ALLOWED_ATTRS = {"*": ["id", "class"], "a": ["href", "title"], "td": ["colspan", "rowspan"],
                       "th": ["colspan", "rowspan", "scope"]}  # fmt: skip


# ---------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------
def setting(name: str, default: str = "") -> str:
    """App config first (tests, file config), then the environment."""
    value = current_app.config.get(name)
    return str(value if value not in (None, "") else environ.get(name, default)).strip()


def token_ttl_days() -> int:
    """Configured link lifetime in days (SETUP_TOKEN_TTL_DAYS, default 14, capped at 90)."""
    try:
        days = int(setting("SETUP_TOKEN_TTL_DAYS", str(DEFAULT_TOKEN_TTL_DAYS)))
    except ValueError:
        days = DEFAULT_TOKEN_TTL_DAYS
    return max(1, min(days, MAX_TOKEN_TTL_DAYS))


@dataclass(frozen=True)
class AgreementDocument:
    """The exact agreement served to the applicant, with its content hashes."""

    document_id: str
    version: str
    sha256: str
    html: Markup
    pdf_path: Path | None
    pdf_sha256: str | None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_agreement(path: Path, raw: bytes) -> Markup:
    """Render the configured file for display. Operator-supplied, still sanitised."""
    text = raw.decode("utf-8")
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        from now_lms.misc import markdown_to_clean_html

        return Markup(markdown_to_clean_html(text))  # nosec B704 - sanitised by bleach in markdown_to_clean_html
    if suffix in {".html", ".htm"}:
        from bleach import clean

        cleaned = clean(text, tags=_HTML_ALLOWED_TAGS, attributes=_HTML_ALLOWED_ATTRS, strip=True)
        return Markup(cleaned)  # nosec B704 - sanitised by bleach with an explicit allowlist
    return Markup('<div class="agreement-plain">') + escape(text) + Markup("</div>")


def load_agreement() -> AgreementDocument | None:
    """Load the configured agreement, or None when the deployment has not set it up.

    Read on every call, deliberately: the hash must describe the file as it is at
    the moment it is shown and at the moment it is accepted.
    """
    text_path = setting("SETUP_AGREEMENT_TEXT_PATH")
    document_id = setting("SETUP_AGREEMENT_DOCUMENT_ID")
    version = setting("SETUP_AGREEMENT_VERSION")
    if not (text_path and document_id and version):
        return None
    path = Path(text_path)
    try:
        raw = path.read_bytes()
        html = _render_agreement(path, raw)
    except (OSError, UnicodeDecodeError) as error:
        log.error(f"Setup agreement text could not be read: {type(error).__name__}")
        return None
    pdf_path: Path | None = None
    pdf_sha: str | None = None
    pdf_setting = setting("SETUP_AGREEMENT_PDF_PATH")
    if pdf_setting:
        candidate = Path(pdf_setting)
        try:
            pdf_sha = _sha256_file(candidate)
            pdf_path = candidate
        except OSError as error:
            log.error(f"Setup agreement PDF could not be read: {type(error).__name__}")
            return None
    return AgreementDocument(document_id, version, hashlib.sha256(raw).hexdigest(), html, pdf_path, pdf_sha)


# ---------------------------------------------------------------------------------------
# Tokens and cases
# ---------------------------------------------------------------------------------------
def hash_token(token: str) -> str:
    """SHA-256 hex of a setup token. Only this is stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalise_email(email: str) -> str:
    """Trim and lower-case an email for storage and matching."""
    return (email or "").strip().lower()


def _new_token(case: SetupCase, ttl_days: int) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = utc_now_naive()
    database.session.add(
        SetupToken(case_id=case.id, token_hash=hash_token(token), created_at=now, expires_at=now + timedelta(days=ttl_days))
    )
    return token


def create_case(  # pylint: disable=too-many-arguments
    *,
    personal_email: str,
    display_name: str,
    known_phone: str | None = None,
    application_ref: str | None = None,
    person_ref: str | None = None,
    access_scope: str | None = None,
    ttl_days: int | None = None,
) -> tuple[SetupCase, str]:
    """Create a setup case and its first token. Returns (case, plaintext token)."""
    case = SetupCase(
        personal_email=normalise_email(personal_email),
        display_name=display_name.strip(),
        known_phone=(known_phone or "").strip() or None,
        application_ref=(application_ref or "").strip() or None,
        person_ref=(person_ref or "").strip() or None,
        access_scope=(access_scope or "").strip() or None,
        status="setup_pending",
    )
    database.session.add(case)
    database.session.flush()
    token = _new_token(case, ttl_days or token_ttl_days())
    database.session.commit()
    return case, token


def reissue_token(case: SetupCase, ttl_days: int | None = None) -> str:
    """Revoke every live token for the case and issue a fresh one."""
    if case.status != "setup_pending":
        raise ValueError("case is no longer pending setup")
    now = utc_now_naive()
    for row in database.session.execute(
        database.select(SetupToken).filter(
            SetupToken.case_id == case.id, SetupToken.revoked_at.is_(None), SetupToken.used_at.is_(None)
        )
    ).scalars():
        row.revoked_at = now
    token = _new_token(case, ttl_days or token_ttl_days())
    database.session.commit()
    return token


@dataclass(frozen=True)
class TokenLookup:
    """Why a token can or cannot be used, plus the rows when it exists."""

    state: str  # "valid" | "unknown" | "revoked" | "expired" | "used"
    token: SetupToken | None = None
    case: SetupCase | None = None
    presented: str = ""  # the plaintext token as presented, for building same-page URLs only


def lookup_token(token: str) -> TokenLookup:
    """Resolve a presented token to its case without trusting anything else."""
    if not token or len(token) > 200:
        return TokenLookup("unknown", presented=token or "")
    row = database.session.execute(
        database.select(SetupToken).filter_by(token_hash=hash_token(token))
    ).scalar_one_or_none()
    if row is None:
        return TokenLookup("unknown", presented=token)
    case = database.session.get(SetupCase, row.case_id)
    if case is None:
        return TokenLookup("unknown", presented=token)
    if row.used_at is not None or case.status != "setup_pending":
        return TokenLookup("used", row, case, token)
    if row.revoked_at is not None:
        return TokenLookup("revoked", row, case, token)
    if row.expires_at <= utc_now_naive():
        return TokenLookup("expired", row, case, token)
    return TokenLookup("valid", row, case, token)


def load_draft(case: SetupCase) -> dict:
    """Return the saved draft fields (empty dict when none)."""
    draft = database.session.execute(database.select(SetupDraft).filter_by(case_id=case.id)).scalar_one_or_none()
    return dict(draft.data or {}) if draft else {}


def save_draft(case: SetupCase, data: dict) -> None:
    """Upsert the case's draft. A draft is never acceptance."""
    draft = database.session.execute(database.select(SetupDraft).filter_by(case_id=case.id)).scalar_one_or_none()
    if draft is None:
        database.session.add(SetupDraft(case_id=case.id, data=dict(data)))
    else:
        draft.data = dict(data)
    database.session.commit()


def acceptance_for(case: SetupCase) -> AgreementAcceptance | None:
    """The case's acceptance, if it has one."""
    return database.session.execute(
        database.select(AgreementAcceptance).filter_by(case_id=case.id)
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------------------
def record_acceptance(  # pylint: disable=too-many-arguments
    *,
    token_row: SetupToken,
    case: SetupCase,
    values: dict,
    agreement: AgreementDocument,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[AgreementAcceptance, bool]:
    """Freeze the acceptance and enqueue follow-up work, atomically and idempotently.

    Returns (acceptance, created). A repeated or concurrent submit for the same case
    returns the existing acceptance with created=False and changes nothing.
    """
    # Serialise concurrent submits for one case (row lock on PostgreSQL; SQLite
    # serialises writers anyway). The UNIQUE(case_id) constraint is the backstop.
    locked = database.session.execute(
        database.select(SetupCase).filter_by(id=case.id).with_for_update()
    ).scalar_one()
    existing = acceptance_for(locked)
    if existing is not None or locked.status != "setup_pending":
        database.session.rollback()
        return existing, False  # type: ignore[return-value]

    now = utc_now_naive()
    acceptance = AgreementAcceptance(
        case_id=locked.id,
        personal_email=locked.personal_email,
        legal_given_names=values["legal_given_names"],
        legal_family_names=values["legal_family_names"],
        legal_full_name=values["legal_full_name"],
        single_name=values["single_name"],
        country_code=values["country_code"],
        address_line1=values["address_line1"],
        address_line2=values["address_line2"],
        locality=values["locality"],
        region=values["region"],
        postal_code=values["postal_code"],
        phone_e164=values["phone_e164"],
        whatsapp_permission=bool(values.get("whatsapp_permission")),
        access_scope=locked.access_scope,
        explanation_version=EXPLANATION_VERSION,
        agreement_document_id=agreement.document_id,
        agreement_version=agreement.version,
        agreement_sha256=agreement.sha256,
        agreement_pdf_sha256=agreement.pdf_sha256,
        assent_text_version=ASSENT_TEXT_VERSION,
        assent_text=ASSENT_TEXT,
        accepted_at_utc=now,
        ip_address=(ip_address or "")[:45] or None,
        user_agent=(user_agent or "")[:512] or None,
    )
    database.session.add(acceptance)
    token_row.used_at = now
    locked.status = "agreement_accepted"
    draft = database.session.execute(database.select(SetupDraft).filter_by(case_id=locked.id)).scalar_one_or_none()
    if draft is not None:
        database.session.delete(draft)
    for kind in ("receipt_email", "crm_sync"):
        database.session.add(SetupJob(case_id=locked.id, kind=kind, status="pending", attempts=0))
    try:
        database.session.commit()
    except IntegrityError:
        database.session.rollback()
        return acceptance_for(case), False  # type: ignore[return-value]
    log.info(f"Setup case {locked.id} accepted the agreement (acceptance {acceptance.id}).")
    return acceptance, True


# ---------------------------------------------------------------------------------------
# Follow-up jobs
# ---------------------------------------------------------------------------------------
def _backoff(attempts: int) -> timedelta:
    delay = JOB_BASE_DELAY * (2 ** max(attempts - 1, 0))
    return min(delay, JOB_MAX_DELAY)


def _claim(job: SetupJob, from_status: str) -> bool:
    """Atomically move a job to 'sending'. False when another worker got it first."""
    result = database.session.execute(
        database.update(SetupJob)
        .where(SetupJob.id == job.id, SetupJob.status == from_status)
        .values(status="sending", attempts=SetupJob.attempts + 1, updated_at=utc_now_naive())
    )
    database.session.commit()
    if result.rowcount != 1:
        return False
    database.session.refresh(job)
    return True


def _finish(job: SetupJob, status: str, detail: str | None = None) -> None:
    now = utc_now_naive()
    job.status = status
    job.last_error = (detail or None) if status != "done" else None
    if status == "done":
        job.completed_at = now
        job.next_attempt_at = None
    elif status == "pending":
        if job.attempts >= JOB_MAX_ATTEMPTS:
            job.status = "failed"
            job.next_attempt_at = None
        else:
            job.next_attempt_at = now + _backoff(job.attempts)
    database.session.commit()


def enqueue_release(case: SetupCase) -> SetupJob:
    """Idempotently create the release job phase 3 consumes; move the case to release_pending."""
    job = database.session.execute(
        database.select(SetupJob).filter_by(case_id=case.id, kind="release")
    ).scalar_one_or_none()
    if job is None:
        job = SetupJob(case_id=case.id, kind="release", status="release_pending", attempts=0)
        database.session.add(job)
    if case.status == "agreement_accepted":
        case.status = "release_pending"
    try:
        database.session.commit()
    except IntegrityError:
        database.session.rollback()
        job = database.session.execute(
            database.select(SetupJob).filter_by(case_id=case.id, kind="release")
        ).scalar_one()
    return job


def _build_receipt(case: SetupCase, acceptance: AgreementAcceptance):
    from flask_mail import Message

    from now_lms.mail import resolve_sender

    agreement = load_agreement()
    context = {
        "acceptance": acceptance,
        "accepted_at": acceptance.accepted_at_utc.strftime("%Y-%m-%d %H:%M UTC"),
        "help_email": setting("SETUP_HELP_EMAIL"),
        "pdf_attached": False,
    }
    msg = Message(
        subject=_("Your agreement acceptance receipt"),
        recipients=[case.personal_email],
        sender=resolve_sender(),  # type: ignore[arg-type]  # same (name, None) shape every mail caller passes
    )
    # Attach the PDF only when it is still the exact file that was accepted.
    if agreement and agreement.pdf_path and agreement.pdf_sha256 == acceptance.agreement_pdf_sha256:
        msg.attach(
            filename=f"user-agreement-{acceptance.agreement_version}.pdf",
            content_type="application/pdf",
            data=agreement.pdf_path.read_bytes(),
        )
        context["pdf_attached"] = True
    msg.body = render_template(RECEIPT_TEXT_TEMPLATE, **context)
    msg.html = render_template(RECEIPT_HTML_TEMPLATE, **context)
    return msg


def deliver_receipt(case: SetupCase, acceptance: AgreementAcceptance) -> None:
    """Send the receipt synchronously so failure is observable. Raises on failure."""
    from now_lms.mail import send_mail

    send_mail(_build_receipt(case, acceptance), background=False)


def mail_ready() -> bool:
    """Whether the effective mail configuration (environment or database) can send."""
    from now_lms.mail import mail_delivery_available

    return mail_delivery_available()


def _run_receipt(job: SetupJob, case: SetupCase, acceptance: AgreementAcceptance) -> None:
    if not mail_ready():
        _finish(job, "pending", "mail is not configured")
        return
    try:
        deliver_receipt(case, acceptance)
    except Exception as error:  # pylint: disable=broad-exception-caught
        # Class name only: SMTP exceptions can quote the recipient address.
        _finish(job, "pending", f"send failed: {type(error).__name__}")
        return
    _finish(job, "done")
    enqueue_release(case)


def _run_crm(job: SetupJob, case: SetupCase, acceptance: AgreementAcceptance) -> None:
    try:
        outcome = crm_sync.sync_acceptance(acceptance, pinned_person_id=case.person_ref)
    except Exception as error:  # pylint: disable=broad-exception-caught
        outcome = crm_sync.SyncOutcome("retry", f"unexpected: {type(error).__name__}")
    if outcome.status == "done" and outcome.person_id and not case.person_ref:
        case.person_ref = outcome.person_id
    status = {"done": "done", "retry": "pending"}.get(outcome.status, outcome.status)
    _finish(job, status, outcome.detail)


def run_job(job: SetupJob) -> str:
    """Claim and run one job. Returns the job's resulting status."""
    from_status = job.status
    if from_status not in ("pending", "sending") or job.kind == "release":
        return job.status
    if not _claim(job, from_status):
        return "skipped"
    case = database.session.get(SetupCase, job.case_id)
    acceptance = acceptance_for(case) if case else None
    if case is None or acceptance is None:
        _finish(job, "failed", "case or acceptance missing")
        return job.status
    if job.kind == "receipt_email":
        _run_receipt(job, case, acceptance)
    elif job.kind == "crm_sync":
        _run_crm(job, case, acceptance)
    else:
        _finish(job, "failed", "unknown job kind")
    log.info(f"Setup job {job.id} ({job.kind}) for case {job.case_id}: {job.status}.")
    return job.status


def due_jobs(case_id: str | None = None, now: datetime | None = None) -> list[SetupJob]:
    """Pending jobs whose back-off has elapsed, plus 'sending' jobs abandoned by a crash."""
    now = now or utc_now_naive()
    query = database.select(SetupJob).filter(
        SetupJob.kind.in_(("receipt_email", "crm_sync")),
        database.or_(
            database.and_(
                SetupJob.status == "pending",
                database.or_(SetupJob.next_attempt_at.is_(None), SetupJob.next_attempt_at <= now),
            ),
            database.and_(SetupJob.status == "sending", SetupJob.updated_at <= now - JOB_STALE_SENDING),
        ),
    )
    if case_id:
        query = query.filter(SetupJob.case_id == case_id)
    return list(database.session.execute(query.order_by(SetupJob.created_at)).scalars())


def process_due_jobs(case_id: str | None = None) -> list[tuple[str, str, str]]:
    """Run every due job. Returns (job id, kind, resulting status) for each attempted job."""
    results = []
    for job in due_jobs(case_id):
        results.append((job.id, job.kind, run_job(job)))
    return results


def failed_work() -> list[SetupJob]:
    """Jobs that need a person: CRM ambiguity, exhausted retries, hard failures."""
    return list(
        database.session.execute(
            database.select(SetupJob)
            .filter(SetupJob.status.in_(("failed", "needs_review")))
            .order_by(SetupJob.updated_at)
        ).scalars()
    )


def requeue(job: SetupJob) -> None:
    """Put a failed/needs_review job back in the queue for an immediate attempt."""
    if job.kind == "release" or job.status in ("done", "sending"):
        raise ValueError("only failed or needs_review receipt/CRM jobs can be requeued")
    job.status = "pending"
    job.attempts = 0
    job.next_attempt_at = None
    database.session.commit()
