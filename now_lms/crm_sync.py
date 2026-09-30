# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.
"""Twenty CRM hand-off for an accepted setup (one module, one outbound integration).

What it does: find the ONE Twenty person whose primary email equals the setup's
personal email, then PATCH the confirmed legal name, phone, structured mailing
address and the CRM status field. Nothing else in the application talks to Twenty.

Rules this module keeps:

- The acceptance row is committed before this runs and is never touched here. A
  CRM failure changes only the job row, so it can never lose an acceptance.
- No guessing. Zero matches or more than one match is ``needs_review`` (the
  failed-work list), not a pick. An operator can pin the person id on the case.
- The API key comes from configuration only and is never logged or stored. Errors
  recorded on the job are HTTP status codes and fixed strings, never response
  bodies, because Twenty echoes submitted values back in its error payloads.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------------------
from dataclasses import dataclass
from os import environ

# ---------------------------------------------------------------------------------------
# Third-party libraries
# ---------------------------------------------------------------------------------------
import requests
from flask import current_app

# ---------------------------------------------------------------------------------------
# Local resources
# ---------------------------------------------------------------------------------------
from now_lms.setup_validation import country_name, phone_country, split_calling_code

HTTP_TIMEOUT_SECONDS = 10
STATUS_FIELD = "cpnStatus"
ADDRESS_FIELD = "mailingAddress"
ACCEPTED_STATUS_VALUE = "agreement_accepted"
# Statuses that deserve another attempt later; everything else in 4xx needs a person.
_RETRYABLE_HTTP = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class SyncOutcome:
    """Result of one sync attempt, as recorded on the job row."""

    status: str  # "done" | "retry" | "needs_review" | "failed"
    detail: str  # PII-free
    person_id: str | None = None


def _setting(name: str) -> str:
    """App config first (tests, file config), then the environment."""
    value = current_app.config.get(name) if current_app else None
    return str(value if value else environ.get(name, "")).strip()


def is_configured() -> bool:
    """True when both the Twenty base URL and API key are available."""
    return bool(_setting("TWENTY_API_URL") and _setting("TWENTY_API_KEY"))


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {_setting('TWENTY_API_KEY')}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
    return session


def _base_url() -> str:
    return _setting("TWENTY_API_URL").rstrip("/")


def _http_outcome(response: requests.Response, action: str) -> SyncOutcome:
    """Map a non-2xx response to an outcome without reading its body."""
    if response.status_code in _RETRYABLE_HTTP:
        return SyncOutcome("retry", f"{action}: HTTP {response.status_code}")
    if response.status_code == 400 and action == "update":
        # The usual cause is a field that does not exist yet (mailingAddress before
        # the one-off metadata script ran). Retry: running the script fixes it.
        return SyncOutcome("retry", "update: HTTP 400 (is the mailingAddress field installed?)")
    return SyncOutcome("failed", f"{action}: HTTP {response.status_code}")


def find_people_by_email(session: requests.Session, email: str) -> list[dict] | SyncOutcome:
    """Return the people whose primary email equals `email` (case-insensitive)."""
    wanted = email.strip().casefold()
    params: dict[str, str | int] = {"filter": f'emails.primaryEmail[ilike]:"{wanted}"', "limit": 5}
    try:
        response = session.get(
            f"{_base_url()}/rest/people",
            # ilike without wildcards is a case-insensitive equality; "_" and "%"
            # inside an address are still wildcards, so results are re-checked exactly.
            params=params,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        return SyncOutcome("retry", f"lookup: {type(error).__name__}")
    if not response.ok:
        return _http_outcome(response, "lookup")
    try:
        people = (response.json().get("data") or {}).get("people") or []
    except ValueError:
        return SyncOutcome("retry", "lookup: response was not JSON")
    return [
        person
        for person in people
        if str(((person.get("emails") or {}).get("primaryEmail") or "")).strip().casefold() == wanted
    ]


def build_person_patch(acceptance, existing_phones: dict | None = None) -> dict:
    """The explicit field map from an acceptance to Twenty People fields."""
    digits = acceptance.phone_e164.lstrip("+")
    calling, national = split_calling_code(digits) or ("", digits)
    phones = {
        "primaryPhoneNumber": national,
        "primaryPhoneCallingCode": f"+{calling}" if calling else "",
        "primaryPhoneCountryCode": phone_country(acceptance.phone_e164, acceptance.country_code) or "",
    }
    # Keep any additional numbers staff already recorded; PATCH replaces the whole
    # composite, so omitting them would silently delete them.
    if existing_phones and existing_phones.get("additionalPhones"):
        phones["additionalPhones"] = existing_phones["additionalPhones"]
    return {
        "name": {
            "firstName": acceptance.legal_given_names,
            "lastName": acceptance.legal_family_names or "",
        },
        "phones": phones,
        ADDRESS_FIELD: {
            "addressStreet1": acceptance.address_line1,
            "addressStreet2": acceptance.address_line2 or "",
            "addressCity": acceptance.locality,
            "addressState": acceptance.region or "",
            "addressPostcode": acceptance.postal_code or "",
            "addressCountry": country_name(acceptance.country_code, "en"),
        },
        STATUS_FIELD: ACCEPTED_STATUS_VALUE,
    }


def sync_acceptance(acceptance, pinned_person_id: str | None = None) -> SyncOutcome:
    """Write one accepted setup to its Twenty person. Never raises."""
    if not is_configured():
        return SyncOutcome("retry", "not configured: set TWENTY_API_URL and TWENTY_API_KEY")
    session = _session()
    try:
        existing_phones = None
        if pinned_person_id:
            person_id = pinned_person_id
        else:
            found = find_people_by_email(session, acceptance.personal_email)
            if isinstance(found, SyncOutcome):
                return found
            if not found:
                return SyncOutcome("needs_review", "no Twenty person has this primary email")
            if len(found) > 1:
                return SyncOutcome("needs_review", f"{len(found)} Twenty people share this primary email")
            person_id = str(found[0].get("id") or "")
            existing_phones = found[0].get("phones")
            if not person_id:
                return SyncOutcome("failed", "lookup: matched person has no id")
        try:
            response = session.patch(
                f"{_base_url()}/rest/people/{person_id}",
                json=build_person_patch(acceptance, existing_phones),
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            return SyncOutcome("retry", f"update: {type(error).__name__}", person_id)
        if response.status_code == 404 and pinned_person_id:
            return SyncOutcome("needs_review", "pinned Twenty person id was not found", person_id)
        if not response.ok:
            outcome = _http_outcome(response, "update")
            return SyncOutcome(outcome.status, outcome.detail, person_id)
        return SyncOutcome("done", "updated", person_id)
    finally:
        session.close()
