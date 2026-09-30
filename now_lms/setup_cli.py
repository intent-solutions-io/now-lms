# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.
"""Operator commands for private participant setup: ``lmsctl setup ...``.

Links are printed exactly once, when issued. Only the token's SHA-256 is stored,
so a lost link cannot be recovered, only reissued (which revokes the old one).
Listings mask email addresses unless ``--show-email`` is passed.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Third-party libraries
# ---------------------------------------------------------------------------------------
import click
from flask.cli import AppGroup

# ---------------------------------------------------------------------------------------
# Local resources
# ---------------------------------------------------------------------------------------
from now_lms import setup_service as service
from now_lms.db import SetupCase, SetupJob, database

setup_cli = AppGroup("setup", help="Private participant setup links, cases and follow-up jobs.")


def _mask(email: str) -> str:
    local, _sep, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _setup_url(base_url: str | None, token: str) -> str:
    base = (base_url or service.setting("SETUP_BASE_URL")).rstrip("/")
    if not base:
        raise click.UsageError("Set SETUP_BASE_URL (e.g. https://learn.example.org) or pass --base-url.")
    return f"{base}/setup/{token}"


def _get_case(case_id: str) -> SetupCase:
    case = database.session.get(SetupCase, case_id)
    if case is None:
        raise click.ClickException(f"No setup case with id {case_id}.")
    return case


@setup_cli.command("issue")
@click.option("--email", "personal_email", required=True, help="The person's personal email (receipt goes here).")
@click.option("--name", "display_name", required=True, help="Display name for operators. Never split into legal names.")
@click.option("--phone", "known_phone", default=None, help="Known phone number, prefilled on the page.")
@click.option("--application-ref", default=None, help="Application id this setup belongs to.")
@click.option("--person-id", "person_ref", default=None, help="Known CRM person id (skips email matching).")
@click.option("--access-scope", default=None, help="The access this agreement covers, shown on the page.")
@click.option("--expiry-days", type=int, default=None, help="Link lifetime in days (default SETUP_TOKEN_TTL_DAYS or 14).")
@click.option("--base-url", default=None, help="Public base URL; defaults to SETUP_BASE_URL.")
@click.option("--allow-duplicate", is_flag=True, default=False, help="Create even if this email has an open case.")
def issue(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    personal_email, display_name, known_phone, application_ref, person_ref, access_scope, expiry_days, base_url, allow_duplicate
):
    """Create a setup case and print its private link once."""
    _setup_url(base_url, "check")  # fail before writing anything if no base URL
    email = service.normalise_email(personal_email)
    if "@" not in email:
        raise click.BadParameter("must be an email address", param_hint="--email")
    open_case = database.session.execute(
        database.select(SetupCase).filter(SetupCase.personal_email == email, SetupCase.status == "setup_pending")
    ).scalar_one_or_none()
    if open_case is not None and not allow_duplicate:
        raise click.ClickException(
            f"Case {open_case.id} is already pending for this email. Use 'lmsctl setup reissue {open_case.id}'."
        )
    case, token = service.create_case(
        personal_email=email,
        display_name=display_name,
        known_phone=known_phone,
        application_ref=application_ref,
        person_ref=person_ref,
        access_scope=access_scope,
        ttl_days=expiry_days,
    )
    click.echo(f"Case: {case.id}")
    click.echo(f"Link (shown once, valid {expiry_days or service.token_ttl_days()} days): {_setup_url(base_url, token)}")


@setup_cli.command("reissue")
@click.argument("case_id")
@click.option("--expiry-days", type=int, default=None, help="Link lifetime in days.")
@click.option("--base-url", default=None, help="Public base URL; defaults to SETUP_BASE_URL.")
def reissue(case_id, expiry_days, base_url):
    """Revoke a case's live links and print a fresh one once."""
    _setup_url(base_url, "check")
    case = _get_case(case_id)
    try:
        token = service.reissue_token(case, expiry_days)
    except ValueError as error:
        raise click.ClickException(f"Cannot reissue: {error} (status {case.status}).") from error
    click.echo(f"Case: {case.id}")
    click.echo(f"Link (shown once, valid {expiry_days or service.token_ttl_days()} days): {_setup_url(base_url, token)}")


@setup_cli.command("list")
@click.option("--status", default=None, help="Filter by case status.")
@click.option("--show-email", is_flag=True, default=False, help="Print full email addresses.")
def list_cases(status, show_email):
    """List setup cases with their status and follow-up jobs."""
    query = database.select(SetupCase).order_by(SetupCase.created_at)
    if status:
        query = query.filter(SetupCase.status == status)
    cases = list(database.session.execute(query).scalars())
    if not cases:
        click.echo("No setup cases.")
        return
    for case in cases:
        jobs = database.session.execute(database.select(SetupJob).filter_by(case_id=case.id)).scalars()
        job_text = ", ".join(f"{job.kind}={job.status}" for job in jobs) or "-"
        email = case.personal_email if show_email else _mask(case.personal_email)
        click.echo(
            f"{case.id}  {case.status:<18}  created {case.created_at:%Y-%m-%d}  updated {case.updated_at:%Y-%m-%d}  "
            f"{email}  jobs: {job_text}"
        )


@setup_cli.command("process-jobs")
def process_jobs():
    """Run due receipt and CRM jobs (safe to run from cron; claims are atomic)."""
    results = service.process_due_jobs()
    for job_id, kind, status in results:
        click.echo(f"{job_id}  {kind:<14} {status}")
    click.echo(f"{len(results)} job(s) attempted.")


@setup_cli.command("failed-work")
def failed_work():
    """List jobs that need a person (CRM ambiguity, exhausted retries)."""
    jobs = service.failed_work()
    if not jobs:
        click.echo("No failed work.")
        return
    for job in jobs:
        click.echo(f"{job.id}  case {job.case_id}  {job.kind:<14} {job.status:<13} attempts {job.attempts}  {job.last_error or ''}")


@setup_cli.command("requeue")
@click.argument("job_id")
def requeue(job_id):
    """Put a failed or needs_review job back in the queue."""
    job = database.session.get(SetupJob, job_id)
    if job is None:
        raise click.ClickException(f"No job with id {job_id}.")
    try:
        service.requeue(job)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Requeued {job.id} ({job.kind}). Run 'lmsctl setup process-jobs'.")


@setup_cli.command("resolve-crm")
@click.argument("case_id")
@click.option("--person-id", required=True, help="The CRM person id an operator confirmed for this case.")
def resolve_crm(case_id, person_id):
    """Pin the CRM person for a case (after review) and requeue its CRM job."""
    case = _get_case(case_id)
    case.person_ref = person_id.strip()
    job = database.session.execute(database.select(SetupJob).filter_by(case_id=case.id, kind="crm_sync")).scalar_one_or_none()
    database.session.commit()
    if job is not None and job.status in ("failed", "needs_review"):
        service.requeue(job)
        click.echo(f"Pinned the CRM person and requeued job {job.id}. Run 'lmsctl setup process-jobs'.")
    else:
        click.echo("Pinned the CRM person.")
