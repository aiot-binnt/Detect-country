import re
from typing import List, Set
from collections import OrderedDict

# Constants
UNKNOWN_COUNTRY_CODE = "ZZ"

# Valid ISO 3166-1 alpha-2 codes
VALID_COUNTRY_CODES: Set[str] = {
    # Asia
    "JP", "CN", "KR", "VN", "TH", "TW", "HK", "SG", "MY", "ID", "PH", "IN",
    "BD", "PK", "MM", "KH", "LA", "BN", "MO", "MN", "NP", "LK",
    # Americas
    "US", "CA", "MX", "BR", "AR", "CL", "CO", "PE", "VE", "EC", "BO",
    "PY", "UY", "CR", "PA", "GT", "HN", "NI", "SV", "CU", "DO", "JM",
    # Europe
    "GB", "DE", "FR", "IT", "ES", "NL", "BE", "CH", "AT", "SE", "NO",
    "DK", "FI", "PL", "CZ", "HU", "PT", "GR", "RO", "IE", "UA", "RU",
    # Middle East
    "AE", "SA", "IL", "TR", "IR", "IQ", "JO", "LB", "KW", "QA", "OM",
    "BH", "YE", "SY", "PS",
    # Africa
    "ZA", "EG", "NG", "KE", "GH", "TZ", "UG", "ET", "MA", "DZ", "TN",
    "SD", "AO", "MZ", "ZW", "ZM", "MW", "BW", "NA",
    # Oceania
    "AU", "NZ", "FJ", "PG", "NC", "PF", "WS", "TO", "VU", "SB", "GU",
}

def _normalize_code(code: str) -> str:
    """Normalize input string to uppercase 2-letter code."""
    if not code:
        return UNKNOWN_COUNTRY_CODE
    
    # Remove non-alphabet characters and uppercase
    clean_code = re.sub(r'[^A-Z]', '', code.strip().upper())
    
    if len(clean_code) != 2 or clean_code == "ZZ":
        return UNKNOWN_COUNTRY_CODE
        
    return clean_code

def validate_country_code(code: str) -> str:
    """Validate a single country code."""
    normalized = _normalize_code(code)
    return normalized if normalized in VALID_COUNTRY_CODES else UNKNOWN_COUNTRY_CODE

def validate_countries(codes: List[str]) -> List[str]:
    """
    Validate a list of country codes.
    Returns a list of unique valid codes or ["ZZ"] if none valid.
    """
    if not codes:
        return [UNKNOWN_COUNTRY_CODE]
    
    validated = []
    for code in codes:
        valid_code = validate_country_code(code)
        if valid_code != UNKNOWN_COUNTRY_CODE:
            validated.append(valid_code)
    
    # Remove duplicates while preserving order using OrderedDict
    unique_codes = list(OrderedDict.fromkeys(validated))
    
    return unique_codes if unique_codes else [UNKNOWN_COUNTRY_CODE]