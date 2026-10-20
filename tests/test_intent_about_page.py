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
        "Founder",
        "Website",
        "Core Offering",
        "Pricing",
        "Contract Terms",
        "Services",
        "Communication",
        "Social",
        "Part of",
    ]:
        assert f'<th scope="row">{field}</th>' in ABOUT


def test_about_page_names_public_team_and_valid_faq_schema():
    """Public roster and FAQ structured data stay extractable from the CMS source."""
    for person in [
        "Jeremy Longshore",
        "Pablo Perez",
        "Max Sheahan",
        "Tim Neunzig",
    ]:
        assert person in ABOUT

    for removed in ["Opeyemi Ariyo", "Tolulope Ariyo"]:
        assert removed not in ABOUT


def test_about_page_shows_a_photo_for_every_team_member():
    """Every public team member gets the same photo card, not just one of them."""
    for name, photo in [
        ("Jeremy Longshore", "jeremy-longshore-suit.jpeg"),
        ("Heather C. Johnson, JD", "heather-johnson.png"),
        ("Pablo Perez", "pablo-perez.jpeg"),
        ("Max Sheahan", "max-sheahan-suit.jpeg"),
        ("Tim Neunzig", "tim-neunzig.png"),
    ]:
        assert f'src="/data/themes/intent_learn/team/{photo}" alt="{name}"' in ABOUT
        assert (ROOT / "now_lms/static/themes/intent_learn/team" / photo).is_file()
    assert ABOUT.count('class="isl-about-person"') == 5


def test_about_page_uses_role_address_not_personal_email():
    """Public pages carry role addresses only."""
    assert "jeremy@" not in ABOUT


def test_theme_navbar_offers_request_access_not_login_to_visitors():
    """Learn is invitation-only: anonymous visitors see no login or sign-up buttons."""
    navbar = (ROOT / "now_lms/templates/themes/intent_learn/navbar.j2").read_text()
    assert "user.inicio_sesion" not in navbar
    assert "user.crear_cuenta" not in navbar
    assert "url_for('request_access.request_access')" in navbar

    match = re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', ABOUT, re.DOTALL)
    assert match
    payload = json.loads(match.group(1))
    assert payload["@type"] == "FAQPage"
    assert len(payload["mainEntity"]) == 7


def test_deploy_upserts_repository_owned_pages():
    """A merge deploys the CMS source instead of leaving the live DB stale."""
    assert "-e PYTHONPATH=/app app" in DEPLOY
    assert "/usr/bin/python3.12 /app/scripts/seed_intent_pages.py" in DEPLOY


def test_about_faq_schema_matches_visible_questions_and_answers():
    """Search engines must receive the same answers visitors can actually read."""
    from html import unescape

    def plain_text(value):
        return " ".join(unescape(re.sub(r"<[^>]+>", "", value)).split())

    section = ABOUT.split('<section aria-labelledby="about-faq">', 1)[1].split("</section>", 1)[0]
    visible = [
        (plain_text(question), plain_text(answer))
        for question, answer in re.findall(r"<article><h3>(.*?)</h3><p>(.*?)</p></article>", section, re.DOTALL)
    ]
    match = re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', ABOUT, re.DOTALL)
    assert match
    payload = json.loads(match.group(1))
    structured = [(item["name"], item["acceptedAnswer"]["text"]) for item in payload["mainEntity"]]
    assert len(visible) == 7
    assert structured == visible


def test_about_keeps_unknown_claims_out_of_public_copy():
    """Incomplete business facts must not ship as placeholders or invented claims."""
    assert "[[" not in ABOUT
    assert "Headquarters" not in ABOUT
    assert 'href="https://intentsolutions.io/projects/"' in ABOUT
    assert "This page does not list a public price." in ABOUT


def test_key_facts_table_stacks_on_phones():
    """The 620px Key facts table must not clip on a phone: rows stack under 760px."""
    css = (ROOT / "now_lms/static/themes/intent_learn/about.css").read_text()
    mobile = css[css.index("@media (max-width: 760px)"):]
    assert "min-width: 0;" in mobile
    assert "display: block;" in mobile
