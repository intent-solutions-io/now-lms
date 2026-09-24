# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Contracts for the repository-owned Intent Solutions Learn About page."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ABOUT = (ROOT / "now_lms/content/intent_learn/about.html").read_text()
DEPLOY = (ROOT / "scripts/deploy-vps.sh").read_text()


def test_about_page_has_complete_ordered_entity_architecture():
    """The CMS seed source keeps the requested heading order and semantic facts."""
    headings = [
        "What Intent Solutions Learn does",
        "What makes Intent Solutions Learn different",
        "Who uses Intent Solutions Learn",
        "The team behind Intent Solutions Learn",
        "How Intent Solutions Learn works",
        "Key facts",
        "Frequently asked questions",
    ]
    cursor = 0
    for heading in headings:
        position = ABOUT.find(f">{heading}</h2>", cursor)
        assert position > cursor, f"missing or out-of-order H2: {heading}"
        cursor = position

    assert "Intent Solutions Learn is a practitioner practice for agentic systems" in ABOUT
    assert "<table>" in ABOUT
    for field in [
        "Company Name",
        "Type",
        "Founded",
        "Founder",
        "Headquarters",
        "Website",
        "Core Offering",
        "Pricing",
        "Contract Terms",
        "Services",
        "Communication",
        "Notable Clients",
        "Customers Served",
        "Projects Delivered",
        "Competitors",
        "Social",
        "Part of",
    ]:
        assert f'<th scope="row">{field}</th>' in ABOUT


def test_about_page_names_public_team_and_valid_faq_schema():
    """Public roster and FAQ structured data stay extractable from the CMS source."""
    for person in [
        "Jeremy Longshore",
        "Opeyemi Ariyo",
        "Pablo Perez",
        "Max Sheahan",
        "Tim Neunzig",
        "Tolulope Ariyo",
    ]:
        assert person in ABOUT

    match = re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', ABOUT, re.DOTALL)
    assert match
    payload = json.loads(match.group(1))
    assert payload["@type"] == "FAQPage"
    assert len(payload["mainEntity"]) == 7


def test_deploy_upserts_repository_owned_pages():
    """A merge deploys the CMS source instead of leaving the live DB stale."""
    assert "-e PYTHONPATH=/app app" in DEPLOY
    assert "/usr/bin/python3.12 /app/scripts/seed_intent_pages.py" in DEPLOY
