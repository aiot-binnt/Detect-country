import re
from typing import List, Set
from collections import OrderedDict

# Constants
UNKNOWN_COUNTRY_CODE = "ZZZ"

# Mapping from alpha-2 to alpha-3 codes (ISO 3166-1)
ALPHA2_TO_ALPHA3 = {
    # Asia
    "JP": "JPN", "CN": "CHN", "KR": "KOR", "VN": "VNM", "TH": "THA", "TW": "TWN",
    "HK": "HKG", "SG": "SGP", "MY": "MYS", "ID": "IDN", "PH": "PHL", "IN": "IND",
    "BD": "BGD", "PK": "PAK", "MM": "MMR", "KH": "KHM", "LA": "LAO", "BN": "BRN",
    "MO": "MAC", "MN": "MNG", "NP": "NPL", "LK": "LKA",
    # Americas
    "US": "USA", "CA": "CAN", "MX": "MEX", "BR": "BRA", "AR": "ARG", "CL": "CHL",
    "CO": "COL", "PE": "PER", "VE": "VEN", "EC": "ECU", "BO": "BOL", "PY": "PRY",
    "UY": "URY", "CR": "CRI", "PA": "PAN", "GT": "GTM", "HN": "HND", "NI": "NIC",
    "SV": "SLV", "CU": "CUB", "DO": "DOM", "JM": "JAM",
    # Europe
    "GB": "GBR", "DE": "DEU", "FR": "FRA", "IT": "ITA", "ES": "ESP", "NL": "NLD",
    "BE": "BEL", "CH": "CHE", "AT": "AUT", "SE": "SWE", "NO": "NOR", "DK": "DNK",
    "FI": "FIN", "PL": "POL", "CZ": "CZE", "HU": "HUN", "PT": "PRT", "GR": "GRC",
    "RO": "ROU", "IE": "IRL", "UA": "UKR", "RU": "RUS",
    # Middle East
    "AE": "ARE", "SA": "SAU", "IL": "ISR", "TR": "TUR", "IR": "IRN", "IQ": "IRQ",
    "JO": "JOR", "LB": "LBN", "KW": "KWT", "QA": "QAT", "OM": "OMN", "BH": "BHR",
    "YE": "YEM", "SY": "SYR", "PS": "PSE",
    # Africa
    "ZA": "ZAF", "EG": "EGY", "NG": "NGA", "KE": "KEN", "GH": "GHA", "TZ": "TZA",
    "UG": "UGA", "ET": "ETH", "MA": "MAR", "DZ": "DZA", "TN": "TUN", "SD": "SDN",
    "AO": "AGO", "MZ": "MOZ", "ZW": "ZWE", "ZM": "ZMB", "MW": "MWI", "BW": "BWA",
    "NA": "NAM",
    # Oceania
    "AU": "AUS", "NZ": "NZL", "FJ": "FJI", "PG": "PNG", "NC": "NCL", "PF": "PYF",
    "WS": "WSM", "TO": "TON", "VU": "VUT", "SB": "SLB", "GU": "GUM",
}

# Valid ISO 3166-1 alpha-3 codes
VALID_COUNTRY_CODES: Set[str] = set(ALPHA2_TO_ALPHA3.values())

def _normalize_code(code: str) -> str:
    """Normalize input string to uppercase code (2 or 3 letters)."""
    if not code:
        return UNKNOWN_COUNTRY_CODE
    
    # Remove non-alphabet characters and uppercase
    clean_code = re.sub(r'[^A-Z]', '', code.strip().upper())
    
    # Accept both 2-char (alpha-2) and 3-char (alpha-3) codes
    if len(clean_code) == 2:
        # Convert alpha-2 to alpha-3
        return ALPHA2_TO_ALPHA3.get(clean_code, UNKNOWN_COUNTRY_CODE)
    elif len(clean_code) == 3:
        # Already alpha-3, validate it
        return clean_code if clean_code in VALID_COUNTRY_CODES else UNKNOWN_COUNTRY_CODE
    else:
        return UNKNOWN_COUNTRY_CODE

def validate_country_code(code: str) -> str:
    """Validate a single country code and return alpha-3 format."""
    normalized = _normalize_code(code)
    return normalized if normalized in VALID_COUNTRY_CODES else UNKNOWN_COUNTRY_CODE

def validate_countries(codes: List[str]) -> List[str]:
    """
    Validate a list of country codes.
    Returns a list of unique valid alpha-3 codes or [] if none valid.
    """
    if not codes:
        return []
    
    validated = []
    for code in codes:
        valid_code = validate_country_code(code)
        if valid_code != UNKNOWN_COUNTRY_CODE:
            validated.append(valid_code)
    
    # Remove duplicates while preserving order using OrderedDict
    unique_codes = list(OrderedDict.fromkeys(validated))
    
    return unique_codes if unique_codes else []
