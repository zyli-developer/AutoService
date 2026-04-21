"""ISO 3166-1 alpha-2 country registry + tenant.countries validator (M3 T2S.6).

Contract: docs/contracts/m3/e4-compliance.md §1.

Design:
- Single frozenset of 249 alpha-2 codes (ISO 3166-1 as of 2025)
- Extra markers: GLOBAL_TAG ``*`` (applies-to-everyone rule) + ``EU`` alias
  (convenience alias for rules that target the EU bloc; not strict ISO)
- Validation is pure: no network fetch, no runtime mutation
- Empty list handling is POLICY, not REGISTRY concern — callers decide
  fail-closed vs fail-open (OQ-E4-1 chose fail-closed at scan layer)
"""
from __future__ import annotations


GLOBAL_TAG = "*"
EU_ALIAS = "EU"


# ISO 3166-1 alpha-2 (official codes only; "EU" is not ISO but accepted as alias)
ISO_3166_1_ALPHA_2: frozenset[str] = frozenset({
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT",
    "AU", "AW", "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI",
    "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY",
    "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN",
    "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM",
    "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK",
    "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL",
    "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM",
    "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR",
    "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN",
    "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS",
    "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK",
    "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW",
    "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP",
    "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM",
    "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
    "SA", "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM",
    "SN", "SO", "SR", "SS", "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF",
    "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR", "TT", "TV", "TW",
    "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
})


# Accepted-in-tenant-config set = strict ISO + GLOBAL + EU alias.
# Compliance rule files may use codes from this broader set too.
ACCEPTED_COUNTRY_CODES: frozenset[str] = (
    ISO_3166_1_ALPHA_2 | frozenset({GLOBAL_TAG, EU_ALIAS})
)


def is_valid(code: str) -> bool:
    """Return True iff *code* is an accepted country token.

    Case-sensitive: only uppercase codes match (callers must normalize
    via :func:`normalize` first if uncertain).
    """
    return code in ACCEPTED_COUNTRY_CODES


def normalize(code: str) -> str:
    """Uppercase + strip; returns the canonical form for lookup."""
    return code.strip().upper()


def validate_list(codes: list[str]) -> list[str]:
    """Return the subset of *codes* that are NOT valid.

    Empty return = all codes valid.  Caller decides policy on empty
    input list (contract §2.1: fail-closed at scan layer, empty registry
    result means "every code in list was valid").

    Raises :class:`TypeError` if input is not a list of strings —
    defensive to catch config misparse at load time.
    """
    if not isinstance(codes, list):
        raise TypeError(
            f"validate_list: expected list[str], got {type(codes).__name__}"
        )
    invalid: list[str] = []
    for c in codes:
        if not isinstance(c, str):
            raise TypeError(
                f"validate_list: list must contain only strings, "
                f"got {type(c).__name__}"
            )
        if not is_valid(c):
            invalid.append(c)
    return invalid


def assert_valid_list(codes: list[str]) -> None:
    """Convenience: raise :class:`ValueError` listing invalid codes.

    Use at tenant config load time — catches typos early.
    """
    bad = validate_list(codes)
    if bad:
        raise ValueError(
            f"Unknown country code(s) in tenant.countries: {bad}. "
            f"Expected ISO 3166-1 alpha-2 (uppercase) or {GLOBAL_TAG!r} / {EU_ALIAS!r}."
        )
