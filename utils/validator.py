# File: utils/validator.py
import re
from typing import List  # ← FIX: Thêm import này

# Valid ISO 3166-1 alpha-2 country codes (most common) - Added ID for Indonesia
VALID_COUNTRY_CODES = {
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

def validate_country_code(code: str) -> str:
    """
    Validate single country code (backward compat)
    Returns: Valid 2-letter code or "ZZ"
    """
    if not code:
        return "ZZ"
    
    # Clean and normalize
    code = code.strip().upper()
    code = re.sub(r'[^A-Z]', '', code)
    
    # Special case for ZZ
    if code == "ZZ":
        return "ZZ"
    
    # Must be exactly 2 letters
    if len(code) != 2:
        return "ZZ"
    
    # Check if valid ISO code
    if code not in VALID_COUNTRY_CODES:
        return "ZZ"
    
    return code

def validate_countries(codes: List[str]) -> List[str]:
    """
    Validate list of country codes
    Returns: List of valid codes, or ["ZZ"] if empty/invalid
    """
    if not codes:
        return ["ZZ"]
    
    validated = []
    for code in codes:
        valid_code = validate_country_code(code)
        if valid_code != "ZZ":
            validated.append(valid_code)
    
    if not validated:
        return ["ZZ"]
    
    return validated

def is_valid_country_code(code: str) -> bool:
    """Check if single country code is valid (excluding ZZ)"""
    return validate_country_code(code) != "ZZ"