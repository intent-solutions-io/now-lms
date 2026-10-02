#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.
"""One-off: create the ``mailingAddress`` ADDRESS field on Twenty's People object.

The setup page's CRM hand-off (``now_lms/crm_sync.py``) writes the confirmed mailing
address into ``person.mailingAddress``. Twenty's People object has no such field by
default, and the application never changes CRM schema on its own, so an operator
runs this once, deliberately, before enabling the sync.

Dry run by default: it reads the metadata API and reports what it WOULD do.
``--apply`` performs the single ``createOneField`` mutation. Idempotent: an existing
``mailingAddress`` field is reported and left alone.

    TWENTY_API_URL=https://crm.example.org TWENTY_API_KEY=... \
        python3 scripts/twenty_add_mailing_address_field.py            # dry run
    TWENTY_API_URL=... TWENTY_API_KEY=... \
        python3 scripts/twenty_add_mailing_address_field.py --apply    # create it

After creating it, restrict who can read the field in Twenty's role/field
permissions if addresses must stay limited to specific staff.

The API key is read from the environment only and is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

FIELD_NAME = "mailingAddress"
FIELD_LABEL = "Mailing address"
FIELD_DESCRIPTION = "Mailing address confirmed by the person on their private setup page (agreement record)."
FIELD_ICON = "IconMailbox"
TIMEOUT_SECONDS = 20

OBJECTS_QUERY = """
query PersonFields {
  objects(paging: { first: 200 }) {
    edges { node { id nameSingular fields(paging: { first: 500 }) { edges { node { id name type } } } } }
  }
}
"""

CREATE_MUTATION = """
mutation CreateMailingAddress($input: CreateOneFieldMetadataInput!) {
  createOneField(input: $input) { id name type label }
}
"""


def _graphql(base_url: str, api_key: str, query: str, variables: dict | None = None) -> dict:
    """POST one GraphQL document to Twenty's metadata endpoint."""
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - operator-supplied https URL
        f"{base_url.rstrip('/')}/metadata",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310  # nosec B310
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        messages = "; ".join(str(error.get("message", "unknown error")) for error in payload["errors"])
        raise RuntimeError(f"Twenty metadata API returned errors: {messages}")
    return payload["data"]


def find_person_object(data: dict) -> dict:
    """Return the People object node from an objects query result."""
    for edge in data["objects"]["edges"]:
        if edge["node"]["nameSingular"] == "person":
            return edge["node"]
    raise RuntimeError("Twenty has no 'person' object; is this the right workspace?")


def build_create_input(object_id: str) -> dict:
    """The createOneField input for the mailing address field."""
    return {
        "field": {
            "objectMetadataId": object_id,
            "type": "ADDRESS",
            "name": FIELD_NAME,
            "label": FIELD_LABEL,
            "description": FIELD_DESCRIPTION,
            "icon": FIELD_ICON,
            "isNullable": True,
        }
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Create the field (default: dry run).")
    args = parser.parse_args(argv)

    base_url = os.environ.get("TWENTY_API_URL", "").strip()
    api_key = os.environ.get("TWENTY_API_KEY", "").strip()
    if not base_url or not api_key:
        print("Set TWENTY_API_URL and TWENTY_API_KEY in the environment.", file=sys.stderr)
        return 2

    try:
        person = find_person_object(_graphql(base_url, api_key, OBJECTS_QUERY))
        fields = {edge["node"]["name"]: edge["node"] for edge in person["fields"]["edges"]}
        existing = fields.get(FIELD_NAME)
        if existing:
            if existing["type"] != "ADDRESS":
                print(f"'{FIELD_NAME}' exists with type {existing['type']}, not ADDRESS. Resolve by hand.", file=sys.stderr)
                return 1
            print(f"'{FIELD_NAME}' already exists on People (ADDRESS). Nothing to do.")
            return 0
        if not args.apply:
            print(f"DRY RUN: would create ADDRESS field '{FIELD_NAME}' on People (object {person['id']}).")
            print("Re-run with --apply to create it.")
            return 0
        created = _graphql(base_url, api_key, CREATE_MUTATION, {"input": build_create_input(person["id"])})
        field = created["createOneField"]
        print(f"Created {field['type']} field '{field['name']}' ({field['id']}) on People.")
        return 0
    except (urllib.error.URLError, RuntimeError, KeyError, ValueError) as error:
        print(f"Failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
