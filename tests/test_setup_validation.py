# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Server-side validation for the private setup page (synthetic addresses only)."""

import pytest

from now_lms.setup_validation import (
    CALLING_CODES,
    country_choices,
    normalise_phone,
    phone_country,
    split_calling_code,
    validate_address,
    validate_names,
    validate_phone,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _ctx(app):
    """gettext needs an app context for error messages."""
    with app.test_request_context():
        yield


# ---------------------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------------------
def test_names_keep_accents_apostrophes_and_hyphens():
    result = validate_names("  José-María ", "D’Arcy  O'Brien", False)
    assert result.ok
    assert result.values["legal_given_names"] == "José-María"
    assert result.values["legal_family_names"] == "D’Arcy O'Brien"
    assert result.values["legal_full_name"] == "José-María D’Arcy O'Brien"


def test_single_name_is_allowed_without_a_family_name():
    result = validate_names("Suharto", "", True)
    assert result.ok
    assert result.values["legal_family_names"] is None
    assert result.values["legal_full_name"] == "Suharto"
    assert result.values["single_name"] is True


def test_single_name_ignores_a_stray_family_name():
    result = validate_names("Teller", "Ignored", True)
    assert result.ok and result.values["legal_full_name"] == "Teller"


def test_family_name_required_unless_single_name():
    result = validate_names("Ada", "", False)
    assert "legal_family_names" in result.errors


def test_non_latin_scripts_are_names():
    assert validate_names("明", "山田", False).ok
    assert validate_names("Ngũgĩ", "wa Thiong’o", False).ok


@pytest.mark.parametrize("bad", ["Ada1", "<b>Ada</b>", "Ada@", "---"])
def test_names_reject_digits_markup_and_symbols(bad):
    assert "legal_given_names" in validate_names(bad, "Test", False).errors


def test_names_are_not_split_or_reordered():
    result = validate_names("Mary Ann", "van der Berg", False)
    assert result.values["legal_given_names"] == "Mary Ann"
    assert result.values["legal_family_names"] == "van der Berg"


# ---------------------------------------------------------------------------------------
# Addresses: US, UK, Canada, Germany (+ others)
# ---------------------------------------------------------------------------------------
def test_us_address_needs_state_and_zip_and_keeps_leading_zeros():
    ok = validate_address("US", "1 Main St", "", "Boston", "ma", "02134-0001")
    assert ok.ok
    assert ok.values["region"] == "MA"
    assert ok.values["postal_code"] == "02134-0001"
    missing = validate_address("US", "1 Main St", "", "Boston", "", "")
    assert {"region", "postal_code"} <= set(missing.errors)
    assert "region" in validate_address("US", "1 Main St", "", "Boston", "ZZ", "02134").errors
    assert "postal_code" in validate_address("US", "1 Main St", "", "Boston", "MA", "2134").errors


def test_uk_address_has_no_state_and_normalises_the_postcode():
    result = validate_address("GB", "10 Downing Street", "", "London", "", "sw1a2aa")
    assert result.ok
    assert result.values["postal_code"] == "SW1A 2AA"
    assert result.values["region"] is None
    assert "postal_code" in validate_address("GB", "10 Downing Street", "", "London", "", "12345").errors


def test_canada_address_needs_province_and_formats_postal_code():
    result = validate_address("CA", "24 Sussex Dr", "", "Ottawa", "on", "k1m1m4")
    assert result.ok
    assert result.values["region"] == "ON"
    assert result.values["postal_code"] == "K1M 1M4"
    assert "region" in validate_address("CA", "24 Sussex Dr", "", "Ottawa", "", "K1M 1M4").errors
    assert "postal_code" in validate_address("CA", "24 Sussex Dr", "", "Ottawa", "ON", "12345").errors


def test_germany_address_has_no_region_and_keeps_leading_zero():
    result = validate_address("DE", "Straße des 17. Juni 135", "", "Dresden", "Sachsen", "01067")
    assert result.ok
    assert result.values["postal_code"] == "01067"
    assert result.values["region"] is None  # Germany uses no region line; nothing is stored
    assert result.values["address_line1"] == "Straße des 17. Juni 135"
    assert "postal_code" in validate_address("DE", "Hauptstr. 1", "", "Berlin", "", "1067").errors


def test_country_without_postal_codes_needs_none():
    assert validate_address("AE", "Villa 1, Street 2", "", "Dubai", "Dubai", "").ok


def test_unlisted_country_is_permissive_but_still_checked():
    ok = validate_address("KE", "Plot 5, Ngong Road", "", "Nairobi", "", "")
    assert ok.ok
    assert "postal_code" in validate_address("KE", "Plot 5", "", "Nairobi", "", "@@@").errors


def test_country_is_required_and_must_be_known():
    assert "country_code" in validate_address("", "1 Main", "", "Town", "", "").errors
    assert "country_code" in validate_address("ZZ", "1 Main", "", "Town", "", "").errors


def test_address_rejects_markup_and_overlong_lines():
    assert "address_line1" in validate_address("US", "<script>", "", "Boston", "MA", "02134").errors
    assert "address_line1" in validate_address("US", "x" * 201, "", "Boston", "MA", "02134").errors


def test_country_choices_are_named_and_sorted():
    choices = country_choices("en")
    codes = dict(choices)
    assert codes["DE"] == "Germany" and codes["GB"] == "United Kingdom"
    names = [name.casefold() for _code, name in choices]
    assert names == sorted(names)


# ---------------------------------------------------------------------------------------
# Phones
# ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "country", "expected"),
    [
        ("(413) 555-0100", "US", "+14135550100"),
        ("1 413 555 0100", "CA", "+14135550100"),
        ("+44 20 7946 0958", "GB", "+442079460958"),
        ("0044 20 7946 0958", "GB", "+442079460958"),
        ("+49 30 901820", "DE", "+4930901820"),
    ],
)
def test_phones_normalise_to_e164(raw, country, expected):
    assert normalise_phone(raw, country) == expected


@pytest.mark.parametrize("raw", ["020 7946 0958", "555-0100", "+0 123 456 789", "call me", "+99912345678"])
def test_implausible_or_ambiguous_phones_are_rejected(raw):
    assert normalise_phone(raw, "GB") is None


def test_phone_error_is_reported():
    assert "phone" in validate_phone("12", "US").errors


def test_calling_code_split_and_country():
    assert split_calling_code("442079460958") == ("44", "2079460958")
    assert split_calling_code("14135550100") == ("1", "4135550100")
    assert phone_country("+14165550100", "CA") == "CA"
    assert phone_country("+14165550100", "DE") == "US"
    assert phone_country("+4930901820", None) == "DE"
    assert all(code.isdigit() for code in CALLING_CODES.values())
