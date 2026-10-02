# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.
"""Server-side validation for the private setup page: names, postal addresses, phones.

Pure functions with no Flask or database dependency so they can be unit tested
directly. The browser repeats a subset of these checks for guidance only; the
rules here are the authority.

Design rules (see the fork decision record for the reasoning):

- Names keep Unicode letters, combining marks, spaces, apostrophes, hyphens and
  periods. They are never split or guessed: given and family names are entered
  separately, and a single-name person is a first-class case.
- The country is chosen first and decides which address parts apply. No country is
  assumed to have a US-style state and ZIP. Postal codes are strings: leading zeros
  and letters survive.
- Phones are stored as E.164. Plausibility is checked; ownership is not claimed.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------------------
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

# ---------------------------------------------------------------------------------------
# Third-party libraries
# ---------------------------------------------------------------------------------------
from babel import Locale

# ---------------------------------------------------------------------------------------
# Local resources
# ---------------------------------------------------------------------------------------
from now_lms.i18n import _

NAME_MAX = 200
LINE_MAX = 200
LOCALITY_MAX = 120
REGION_MAX = 120
POSTAL_MAX = 20

_NAME_PUNCTUATION = frozenset(" '’‘-‐.")
_ADDRESS_FORBIDDEN = frozenset("<>{}\\")

US_STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "AS": "American Samoa", "GU": "Guam", "MP": "Northern Mariana Islands",
    "PR": "Puerto Rico", "VI": "U.S. Virgin Islands", "AA": "Armed Forces Americas", "AE": "Armed Forces Europe",
    "AP": "Armed Forces Pacific",
}  # fmt: skip

CA_PROVINCES: dict[str, str] = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories", "NU": "Nunavut",
    "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec", "SK": "Saskatchewan", "YT": "Yukon",
}  # fmt: skip

AU_STATES: dict[str, str] = {
    "ACT": "Australian Capital Territory", "NSW": "New South Wales", "NT": "Northern Territory",
    "QLD": "Queensland", "SA": "South Australia", "TAS": "Tasmania", "VIC": "Victoria", "WA": "Western Australia",
}  # fmt: skip


@dataclass(frozen=True)
class AddressRule:
    """How one country's mailing address is labelled and checked."""

    region: str = "optional"  # "required" | "optional" | "none"
    region_label: str = "State / province / region"
    region_choices: dict[str, str] | None = None
    postal: str = "optional"  # "required" | "optional" | "none"
    postal_label: str = "Postal code"
    postal_pattern: str | None = None  # applied to the normalised (upper-case) value
    postal_example: str = ""
    locality_label: str = "City / town"
    upper_postal: bool = True


_UK_POSTCODE = r"^(GIR 0AA|[A-Z]{1,2}[0-9][0-9A-Z]? ?[0-9][A-Z]{2})$"

ADDRESS_RULES: dict[str, AddressRule] = {
    "US": AddressRule("required", "State", US_STATES, "required", "ZIP code", r"^\d{5}(-\d{4})?$", "02134"),
    "CA": AddressRule("required", "Province / territory", CA_PROVINCES, "required", "Postal code",
                      r"^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] ?\d[ABCEGHJ-NPRSTV-Z]\d$", "K1A 0B1"),
    "GB": AddressRule("optional", "County (optional)", None, "required", "Postcode", _UK_POSTCODE, "SW1A 1AA",
                      "Town / city"),
    "DE": AddressRule("none", "", None, "required", "Postleitzahl (postal code)", r"^\d{5}$", "01067"),
    "AU": AddressRule("required", "State / territory", AU_STATES, "required", "Postcode", r"^\d{4}$", "0800",
                      "Suburb / town"),
    "FR": AddressRule("none", "", None, "required", "Code postal (postal code)", r"^\d{5}$", "75008"),
    "IT": AddressRule("optional", "Province (optional)", None, "required", "CAP (postal code)", r"^\d{5}$", "00118"),
    "ES": AddressRule("optional", "Province (optional)", None, "required", "Código postal", r"^\d{5}$", "08001"),
    "NL": AddressRule("none", "", None, "required", "Postcode", r"^\d{4} ?[A-Z]{2}$", "1012 AB"),
    "IE": AddressRule("optional", "County (optional)", None, "optional", "Eircode (optional)",
                      r"^[A-Z]\d[0-9W] ?[0-9A-Z]{4}$", "D02 X285"),
    "IN": AddressRule("required", "State / union territory", None, "required", "PIN code", r"^\d{6}$", "110001"),
    "BR": AddressRule("required", "State", None, "required", "CEP", r"^\d{5}-?\d{3}$", "01310-100"),
    "MX": AddressRule("required", "State", None, "required", "Código postal", r"^\d{5}$", "06000"),
    "JP": AddressRule("required", "Prefecture", None, "required", "Postal code", r"^\d{3}-?\d{4}$", "100-0001"),
    "NZ": AddressRule("none", "", None, "required", "Postcode", r"^\d{4}$", "6011", "Town / city"),
    "SE": AddressRule("none", "", None, "required", "Postnummer (postal code)", r"^\d{3} ?\d{2}$", "114 55"),
    "CH": AddressRule("none", "", None, "required", "Postal code", r"^\d{4}$", "8001"),
    "AT": AddressRule("none", "", None, "required", "Postal code", r"^\d{4}$", "1010"),
    "PL": AddressRule("none", "", None, "required", "Kod pocztowy", r"^\d{2}-\d{3}$", "00-001"),
    "PT": AddressRule("none", "", None, "required", "Código postal", r"^\d{4}-\d{3}$", "1000-001"),
    "PH": AddressRule("optional", "Province (optional)", None, "required", "ZIP code", r"^\d{4}$", "1000"),
    "SG": AddressRule("none", "", None, "required", "Postal code", r"^\d{6}$", "018956"),
    "ZA": AddressRule("optional", "Province (optional)", None, "required", "Postal code", r"^\d{4}$", "0001"),
    "NG": AddressRule("required", "State", None, "optional", "Postal code (optional)", r"^\d{6}$", "100001"),
    "HK": AddressRule("optional", "District (optional)", None, "none", ""),
    "AE": AddressRule("required", "Emirate", None, "none", ""),
}  # fmt: skip

DEFAULT_ADDRESS_RULE = AddressRule()

# ITU-T E.164 country calling codes. Calling codes form a prefix-free set, so a
# longest-prefix match on an E.164 number is unambiguous about the CODE; the
# country is ambiguous only inside shared plans (+1, +7, +44, +47, +61, ...).
CALLING_CODES: dict[str, str] = {
    "AD": "376", "AE": "971", "AF": "93", "AG": "1", "AI": "1", "AL": "355", "AM": "374", "AO": "244",
    "AR": "54", "AS": "1", "AT": "43", "AU": "61", "AW": "297", "AX": "358", "AZ": "994", "BA": "387",
    "BB": "1", "BD": "880", "BE": "32", "BF": "226", "BG": "359", "BH": "973", "BI": "257", "BJ": "229",
    "BL": "590", "BM": "1", "BN": "673", "BO": "591", "BQ": "599", "BR": "55", "BS": "1", "BT": "975",
    "BW": "267", "BY": "375", "BZ": "501", "CA": "1", "CC": "61", "CD": "243", "CF": "236", "CG": "242",
    "CH": "41", "CI": "225", "CK": "682", "CL": "56", "CM": "237", "CN": "86", "CO": "57", "CR": "506",
    "CU": "53", "CV": "238", "CW": "599", "CX": "61", "CY": "357", "CZ": "420", "DE": "49", "DJ": "253",
    "DK": "45", "DM": "1", "DO": "1", "DZ": "213", "EC": "593", "EE": "372", "EG": "20", "EH": "212",
    "ER": "291", "ES": "34", "ET": "251", "FI": "358", "FJ": "679", "FK": "500", "FM": "691", "FO": "298",
    "FR": "33", "GA": "241", "GB": "44", "GD": "1", "GE": "995", "GF": "594", "GG": "44", "GH": "233",
    "GI": "350", "GL": "299", "GM": "220", "GN": "224", "GP": "590", "GQ": "240", "GR": "30", "GT": "502",
    "GU": "1", "GW": "245", "GY": "592", "HK": "852", "HN": "504", "HR": "385", "HT": "509", "HU": "36",
    "ID": "62", "IE": "353", "IL": "972", "IM": "44", "IN": "91", "IO": "246", "IQ": "964", "IR": "98",
    "IS": "354", "IT": "39", "JE": "44", "JM": "1", "JO": "962", "JP": "81", "KE": "254", "KG": "996",
    "KH": "855", "KI": "686", "KM": "269", "KN": "1", "KP": "850", "KR": "82", "KW": "965", "KY": "1",
    "KZ": "7", "LA": "856", "LB": "961", "LC": "1", "LI": "423", "LK": "94", "LR": "231", "LS": "266",
    "LT": "370", "LU": "352", "LV": "371", "LY": "218", "MA": "212", "MC": "377", "MD": "373", "ME": "382",
    "MF": "590", "MG": "261", "MH": "692", "MK": "389", "ML": "223", "MM": "95", "MN": "976", "MO": "853",
    "MP": "1", "MQ": "596", "MR": "222", "MS": "1", "MT": "356", "MU": "230", "MV": "960", "MW": "265",
    "MX": "52", "MY": "60", "MZ": "258", "NA": "264", "NC": "687", "NE": "227", "NF": "672", "NG": "234",
    "NI": "505", "NL": "31", "NO": "47", "NP": "977", "NR": "674", "NU": "683", "NZ": "64", "OM": "968",
    "PA": "507", "PE": "51", "PF": "689", "PG": "675", "PH": "63", "PK": "92", "PL": "48", "PM": "508",
    "PR": "1", "PS": "970", "PT": "351", "PW": "680", "PY": "595", "QA": "974", "RE": "262", "RO": "40",
    "RS": "381", "RU": "7", "RW": "250", "SA": "966", "SB": "677", "SC": "248", "SD": "249", "SE": "46",
    "SG": "65", "SH": "290", "SI": "386", "SJ": "47", "SK": "421", "SL": "232", "SM": "378", "SN": "221",
    "SO": "252", "SR": "597", "SS": "211", "ST": "239", "SV": "503", "SX": "1", "SY": "963", "SZ": "268",
    "TC": "1", "TD": "235", "TG": "228", "TH": "66", "TJ": "992", "TK": "690", "TL": "670", "TM": "993",
    "TN": "216", "TO": "676", "TR": "90", "TT": "1", "TV": "688", "TW": "886", "TZ": "255", "UA": "380",
    "UG": "256", "US": "1", "UY": "598", "UZ": "998", "VA": "39", "VC": "1", "VE": "58", "VG": "1",
    "VI": "1", "VN": "84", "VU": "678", "WF": "681", "WS": "685", "XK": "383", "YE": "967", "YT": "262",
    "ZA": "27", "ZM": "260", "ZW": "263",
}  # fmt: skip

# The default country for each shared calling code, used only when the address
# country does not share the code.
_CODE_DEFAULT_COUNTRY = {"1": "US", "7": "RU", "44": "GB", "47": "NO", "61": "AU", "39": "IT", "212": "MA",
                         "262": "RE", "358": "FI", "590": "GP", "599": "CW"}  # fmt: skip
_ALL_CODES = frozenset(CALLING_CODES.values())


@dataclass
class ValidationResult:
    """Normalised values plus per-field error messages (empty when valid)."""

    values: dict = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when no field failed."""
        return not self.errors


@lru_cache(maxsize=8)
def country_choices(locale: str = "en") -> tuple[tuple[str, str], ...]:
    """Return (ISO code, localised name) pairs for every country with a calling code."""
    try:
        territories = Locale.parse(locale).territories
    except (ValueError, TypeError):  # unknown locale string
        territories = Locale.parse("en").territories
    pairs = [(code, territories.get(code, code)) for code in CALLING_CODES]
    return tuple(sorted(pairs, key=lambda pair: pair[1].casefold()))


def country_name(code: str, locale: str = "en") -> str:
    """Return the country's name in `locale` (English names feed the CRM)."""
    return dict(country_choices(locale)).get(code, code)


def address_rule(country_code: str) -> AddressRule:
    """Return the address rule for a country (a permissive default when not listed)."""
    return ADDRESS_RULES.get(country_code, DEFAULT_ADDRESS_RULE)


def clean_text(value: str | None) -> str:
    """NFC-normalise, turn control characters into spaces and collapse whitespace."""
    text = unicodedata.normalize("NFC", value or "")
    text = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def valid_name(value: str) -> bool:
    """Letters and marks from any script, plus space, apostrophes, hyphens and periods."""
    if not value or not any(unicodedata.category(ch).startswith("L") for ch in value):
        return False
    return all(unicodedata.category(ch)[0] in "LM" or ch in _NAME_PUNCTUATION for ch in value)


def validate_names(given: str | None, family: str | None, single_name: bool) -> ValidationResult:
    """Validate the confirmed legal name. Nothing is split or re-ordered."""
    result = ValidationResult()
    given_clean = clean_text(given)
    family_clean = clean_text(family)
    if not given_clean:
        result.errors["legal_given_names"] = (
            _("Enter your name.") if single_name else _("Enter your given name or names.")
        )
    elif len(given_clean) > NAME_MAX or not valid_name(given_clean):
        result.errors["legal_given_names"] = _("Use letters, spaces, apostrophes, hyphens or periods only.")
    if single_name:
        family_clean = ""
    elif not family_clean:
        result.errors["legal_family_names"] = _(
            "Enter your family name or names, or tick “I have only one name”."
        )
    elif len(family_clean) > NAME_MAX or not valid_name(family_clean):
        result.errors["legal_family_names"] = _("Use letters, spaces, apostrophes, hyphens or periods only.")
    full = given_clean if single_name else f"{given_clean} {family_clean}".strip()
    result.values = {
        "legal_given_names": given_clean,
        "legal_family_names": family_clean or None,
        "single_name": bool(single_name),
        "legal_full_name": full,
    }
    return result


def _address_text_ok(value: str) -> bool:
    return not any(ch in _ADDRESS_FORBIDDEN for ch in value)


def normalise_postal(country_code: str, value: str) -> str:
    """Upper-case and tidy spacing; digits (including leading zeros) are kept verbatim."""
    text = clean_text(value)
    rule = address_rule(country_code)
    if rule.upper_postal:
        text = text.upper()
    if country_code == "CA" and re.fullmatch(r"[A-Z]\d[A-Z]\d[A-Z]\d", text):
        text = f"{text[:3]} {text[3:]}"
    if country_code == "GB" and " " not in text and 5 <= len(text) <= 7:
        text = f"{text[:-3]} {text[-3:]}"
    return text


def validate_address(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    country_code: str | None,
    line1: str | None,
    line2: str | None,
    locality: str | None,
    region: str | None,
    postal_code: str | None,
) -> ValidationResult:
    """Validate a mailing address against the chosen country's rule."""
    result = ValidationResult()
    country = clean_text(country_code).upper()
    if country not in CALLING_CODES:
        result.errors["country_code"] = _("Choose your country.")
        return result
    rule = address_rule(country)
    line1_c, line2_c, locality_c = clean_text(line1), clean_text(line2), clean_text(locality)
    region_c = clean_text(region)
    postal_c = normalise_postal(country, postal_code or "")

    if not line1_c:
        result.errors["address_line1"] = _("Enter the first line of your mailing address.")
    elif len(line1_c) > LINE_MAX or not _address_text_ok(line1_c):
        result.errors["address_line1"] = _("This address line is too long or contains characters we cannot store.")
    if len(line2_c) > LINE_MAX or not _address_text_ok(line2_c):
        result.errors["address_line2"] = _("This address line is too long or contains characters we cannot store.")
    if not locality_c:
        result.errors["locality"] = _("Enter your city or town.")
    elif len(locality_c) > LOCALITY_MAX or not _address_text_ok(locality_c):
        result.errors["locality"] = _("This city or town is too long or contains characters we cannot store.")

    if rule.region == "none":
        region_c = ""
    elif rule.region_choices is not None:
        region_c = region_c.upper()
        if region_c and region_c not in rule.region_choices:
            result.errors["region"] = _("Choose a value from the list.")
        elif not region_c and rule.region == "required":
            result.errors["region"] = _("Choose your state, province or region.")
    elif not region_c and rule.region == "required":
        result.errors["region"] = _("Enter your state, province or region.")
    elif len(region_c) > REGION_MAX or not _address_text_ok(region_c):
        result.errors["region"] = _("This region is too long or contains characters we cannot store.")

    if rule.postal == "none":
        postal_c = ""
    elif not postal_c:
        if rule.postal == "required":
            result.errors["postal_code"] = _("Enter your postal code.")
    elif len(postal_c) > POSTAL_MAX or (rule.postal_pattern and not re.fullmatch(rule.postal_pattern, postal_c)):
        result.errors["postal_code"] = _("Check the postal code format, for example %(example)s.") % {
            "example": rule.postal_example or "12345"
        }
    elif not rule.postal_pattern and not re.fullmatch(r"[0-9A-Z][0-9A-Z \-]*", postal_c):
        result.errors["postal_code"] = _("Use letters, digits, spaces or hyphens only.")

    result.values = {
        "country_code": country,
        "address_line1": line1_c,
        "address_line2": line2_c or None,
        "locality": locality_c,
        "region": region_c or None,
        "postal_code": postal_c or None,
    }
    return result


def normalise_phone(value: str | None, country_code: str | None = None) -> str | None:
    """Return the E.164 form of a human-typed number, or None when implausible."""
    text = clean_text(value)
    if not text or not re.fullmatch(r"\+?[0-9 ().\-]+", text):
        return None
    has_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if not has_plus and digits.startswith("00"):
        digits, has_plus = digits[2:], True
    if not has_plus:
        # Without an international prefix only the North American plan is unambiguous:
        # ten digits, or eleven starting with the trunk "1".
        if CALLING_CODES.get(country_code or "") == "1":
            if len(digits) == 11 and digits.startswith("1"):
                digits = digits[1:]
            if len(digits) == 10:
                digits = "1" + digits
            else:
                return None
        else:
            return None
    if not 8 <= len(digits) <= 15 or digits.startswith("0") or split_calling_code(digits) is None:
        return None
    return "+" + digits


def split_calling_code(e164_digits: str) -> tuple[str, str] | None:
    """Split E.164 digits (no '+') into (calling code, national number)."""
    digits = e164_digits.lstrip("+")
    for size in (3, 2, 1):
        if digits[:size] in _ALL_CODES:
            return digits[:size], digits[size:]
    return None


def phone_country(e164: str, address_country: str | None = None) -> str | None:
    """Best ISO country for a number: the address country when it shares the code."""
    parts = split_calling_code(e164)
    if parts is None:
        return None
    code = parts[0]
    if address_country and CALLING_CODES.get(address_country) == code:
        return address_country
    if code in _CODE_DEFAULT_COUNTRY:
        return _CODE_DEFAULT_COUNTRY[code]
    matches = [iso for iso, calling in CALLING_CODES.items() if calling == code]
    return matches[0] if matches else None


def validate_phone(value: str | None, country_code: str | None = None) -> ValidationResult:
    """Validate and normalise the confirmed phone number."""
    result = ValidationResult()
    e164 = normalise_phone(value, country_code)
    if e164 is None:
        result.errors["phone"] = _(
            "Enter a valid phone number with its country code, for example +44 20 7946 0958."
        )
    result.values = {"phone_e164": e164}
    return result


def address_rules_for_client() -> dict[str, dict]:
    """The subset of the address rules the browser needs for labels and guidance."""
    return {
        code: {
            "region": rule.region,
            "regionLabel": rule.region_label,
            "regionChoices": rule.region_choices or {},
            "postal": rule.postal,
            "postalLabel": rule.postal_label,
            "postalPattern": rule.postal_pattern or "",
            "postalExample": rule.postal_example,
            "localityLabel": rule.locality_label,
        }
        for code, rule in ADDRESS_RULES.items()
    }
