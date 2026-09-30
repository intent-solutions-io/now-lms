# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Twenty CRM hand-off: exact matching, explicit field map, no guessing, no leaks.

A fake HTTP session stands in for Twenty; nothing leaves the process.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from now_lms import crm_sync

pytestmark = pytest.mark.unit

API_KEY = "test-key-never-logged"


def _acceptance(**overrides):
    values = {
        "personal_email": "ada.test@example.org",
        "legal_given_names": "Ada María",
        "legal_family_names": "O’Neil",
        "phone_e164": "+14165550100",
        "country_code": "CA",
        "address_line1": "1 Example Ave",
        "address_line2": None,
        "locality": "Toronto",
        "region": "ON",
        "postal_code": "M5V 2T6",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, get_response=None, patch_response=None, raise_on=None):
        self.get_response = get_response
        self.patch_response = patch_response or FakeResponse(200, {"data": {}})
        self.raise_on = raise_on
        self.calls = []
        self.headers = {"Authorization": f"Bearer {API_KEY}"}

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        if self.raise_on == "get":
            raise requests.ConnectionError("down")
        return self.get_response

    def patch(self, url, json=None, timeout=None):
        self.calls.append(("PATCH", url, json))
        if self.raise_on == "patch":
            raise requests.Timeout("slow")
        return self.patch_response

    def close(self):
        pass


@pytest.fixture()
def configured(app, monkeypatch):
    monkeypatch.setitem(app.config, "TWENTY_API_URL", "https://crm.example.org/")
    monkeypatch.setitem(app.config, "TWENTY_API_KEY", API_KEY)
    with app.app_context():
        yield


def _people(*people):
    return FakeResponse(200, {"data": {"people": list(people)}})


def _use(monkeypatch, session):
    monkeypatch.setattr(crm_sync, "_session", lambda: session)
    return session


def test_unconfigured_sync_retries_without_calling_out(app, monkeypatch):
    monkeypatch.delenv("TWENTY_API_URL", raising=False)
    monkeypatch.delenv("TWENTY_API_KEY", raising=False)
    with app.app_context():
        outcome = crm_sync.sync_acceptance(_acceptance())
    assert outcome.status == "retry" and "not configured" in outcome.detail


def test_exact_match_updates_the_explicit_field_map(configured, monkeypatch):
    session = _use(
        monkeypatch,
        FakeSession(
            _people(
                {"id": "p-1", "emails": {"primaryEmail": "ADA.TEST@example.org"}, "phones": {"additionalPhones": [{"number": "1"}]}},
                {"id": "p-2", "emails": {"primaryEmail": "adaxtest@example.org"}},  # ilike wildcard look-alike
            )
        ),
    )
    outcome = crm_sync.sync_acceptance(_acceptance())
    assert outcome == crm_sync.SyncOutcome("done", "updated", "p-1")
    method, url, body = session.calls[-1]
    assert method == "PATCH" and url == "https://crm.example.org/rest/people/p-1"
    assert body["name"] == {"firstName": "Ada María", "lastName": "O’Neil"}
    assert body["phones"]["primaryPhoneNumber"] == "4165550100"
    assert body["phones"]["primaryPhoneCallingCode"] == "+1"
    assert body["phones"]["primaryPhoneCountryCode"] == "CA"
    assert body["phones"]["additionalPhones"] == [{"number": "1"}]
    assert body["mailingAddress"] == {
        "addressStreet1": "1 Example Ave",
        "addressStreet2": "",
        "addressCity": "Toronto",
        "addressState": "ON",
        "addressPostcode": "M5V 2T6",
        "addressCountry": "Canada",
    }
    assert body["cpnStatus"] == "agreement_accepted"


def test_single_name_maps_to_an_empty_last_name(configured, monkeypatch):
    session = _use(monkeypatch, FakeSession(_people({"id": "p-1", "emails": {"primaryEmail": "ada.test@example.org"}})))
    crm_sync.sync_acceptance(_acceptance(legal_given_names="Teller", legal_family_names=None))
    assert session.calls[-1][2]["name"] == {"firstName": "Teller", "lastName": ""}


def test_no_match_goes_to_review(configured, monkeypatch):
    _use(monkeypatch, FakeSession(_people()))
    assert crm_sync.sync_acceptance(_acceptance()).status == "needs_review"


def test_two_exact_matches_go_to_review_not_a_guess(configured, monkeypatch):
    session = _use(
        monkeypatch,
        FakeSession(
            _people(
                {"id": "p-1", "emails": {"primaryEmail": "ada.test@example.org"}},
                {"id": "p-2", "emails": {"primaryEmail": "Ada.Test@example.org"}},
            )
        ),
    )
    outcome = crm_sync.sync_acceptance(_acceptance())
    assert outcome.status == "needs_review"
    assert all(call[0] == "GET" for call in session.calls)


def test_pinned_person_skips_matching(configured, monkeypatch):
    session = _use(monkeypatch, FakeSession())
    outcome = crm_sync.sync_acceptance(_acceptance(), pinned_person_id="p-9")
    assert outcome.status == "done"
    assert [call[0] for call in session.calls] == ["PATCH"]


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        (FakeSession(raise_on="get"), "retry"),
        (FakeSession(FakeResponse(503)), "retry"),
        (FakeSession(FakeResponse(429)), "retry"),
        (FakeSession(FakeResponse(401)), "failed"),
    ],
)
def test_lookup_failures_are_classified(configured, monkeypatch, session, expected):
    _use(monkeypatch, session)
    assert crm_sync.sync_acceptance(_acceptance()).status == expected


def test_update_failures_are_classified_without_bodies(configured, monkeypatch):
    match = _people({"id": "p-1", "emails": {"primaryEmail": "ada.test@example.org"}})
    _use(monkeypatch, FakeSession(match, FakeResponse(400, {"messages": ["ada.test@example.org is bad"]})))
    outcome = crm_sync.sync_acceptance(_acceptance())
    assert outcome.status == "retry" and "mailingAddress" in outcome.detail
    assert "example.org" not in outcome.detail
    _use(monkeypatch, FakeSession(match, raise_on="patch"))
    assert crm_sync.sync_acceptance(_acceptance()).status == "retry"


def test_api_key_never_appears_in_outcomes(configured, monkeypatch):
    _use(monkeypatch, FakeSession(FakeResponse(500)))
    outcome = crm_sync.sync_acceptance(_acceptance())
    assert API_KEY not in outcome.detail


# ---------------------------------------------------------------------------------------
# The one-off metadata script (exercised offline; never against a real CRM here)
# ---------------------------------------------------------------------------------------
def _load_script():
    path = Path(__file__).resolve().parent.parent / "scripts" / "twenty_add_mailing_address_field.py"
    spec = importlib.util.spec_from_file_location("twenty_add_mailing_address_field", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _objects(fields):
    return {
        "objects": {
            "edges": [
                {"node": {"id": "obj-company", "nameSingular": "company", "fields": {"edges": []}}},
                {
                    "node": {
                        "id": "obj-person",
                        "nameSingular": "person",
                        "fields": {"edges": [{"node": field} for field in fields]},
                    }
                },
            ]
        }
    }


def test_metadata_script_dry_run_does_not_mutate(monkeypatch, capsys):
    script = _load_script()
    calls = []
    monkeypatch.setattr(script, "_graphql", lambda *a, **k: calls.append(a) or _objects([{"id": "f", "name": "phones", "type": "PHONES"}]))
    monkeypatch.setenv("TWENTY_API_URL", "https://crm.example.org")
    monkeypatch.setenv("TWENTY_API_KEY", API_KEY)
    assert script.main([]) == 0
    assert len(calls) == 1  # read only
    out = capsys.readouterr().out
    assert "DRY RUN" in out and API_KEY not in out


def test_metadata_script_apply_creates_an_address_field_once(monkeypatch, capsys):
    script = _load_script()
    calls = []

    def fake(base, key, query, variables=None):
        calls.append(variables)
        if variables:
            return {"createOneField": {"id": "new", "name": "mailingAddress", "type": "ADDRESS", "label": "Mailing address"}}
        return _objects([])

    monkeypatch.setattr(script, "_graphql", fake)
    monkeypatch.setenv("TWENTY_API_URL", "https://crm.example.org")
    monkeypatch.setenv("TWENTY_API_KEY", API_KEY)
    assert script.main(["--apply"]) == 0
    field = calls[-1]["input"]["field"]
    assert field["type"] == "ADDRESS" and field["name"] == "mailingAddress" and field["objectMetadataId"] == "obj-person"
    # Idempotent: an existing field means no mutation.
    calls.clear()
    monkeypatch.setattr(
        script, "_graphql", lambda *a, **k: calls.append(a) or _objects([{"id": "x", "name": "mailingAddress", "type": "ADDRESS"}])
    )
    assert script.main(["--apply"]) == 0
    assert len(calls) == 1


def test_metadata_script_requires_credentials(monkeypatch):
    script = _load_script()
    monkeypatch.delenv("TWENTY_API_URL", raising=False)
    monkeypatch.delenv("TWENTY_API_KEY", raising=False)
    assert script.main([]) == 2
