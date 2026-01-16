"""
HS Code Lookup Module
Provides search and validation functions for Japan Post HS Codes.
"""
import json
import os
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class HSCodeItem:
    """Represents an HS Code item from Japan Post."""
    japanese: str
    chinese: str
    english: str
    hscode: str
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "japanese": self.japanese,
            "chinese": self.chinese,
            "english": self.english,
            "hscode": self.hscode
        }


class HSCodeLookup:
    """
    HS Code lookup service using Japan Post data.
    Provides search by keyword and validation functions.
    """
    
    _instance = None
    _data: List[HSCodeItem] = []
    _hscode_map: Dict[str, HSCodeItem] = {}
    _loaded = False
    
    def __new__(cls):
        """Singleton pattern for efficient memory usage."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not HSCodeLookup._loaded:
            self._load_data()
    
    def _load_data(self):
        """Load HS Code data from JSON file."""
        # Try multiple possible paths
        possible_paths = [
            os.path.join(os.path.dirname(__file__), '..', 'data', 'japan_post_hscode.json'),
            os.path.join(os.path.dirname(__file__), 'data', 'japan_post_hscode.json'),
            'data/japan_post_hscode.json',
        ]
        
        for path in possible_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        raw_data = json.load(f)
                    
                    items = raw_data.get('items', [])
                    HSCodeLookup._data = []
                    HSCodeLookup._hscode_map = {}
                    
                    for item in items:
                        hs_item = HSCodeItem(
                            japanese=item.get('ja', ''),
                            chinese=item.get('cn', ''),
                            english=item.get('en', ''),
                            hscode=item.get('hscode', '')
                        )
                        HSCodeLookup._data.append(hs_item)
                        HSCodeLookup._hscode_map[hs_item.hscode] = hs_item
                    
                    HSCodeLookup._loaded = True
                    logger.info(f"✓ Loaded {len(HSCodeLookup._data)} HS Codes from {abs_path}")
                    return
                except Exception as e:
                    logger.error(f"Error loading HS Code data: {e}")
        
        logger.warning("HS Code data file not found. Lookup features will be limited.")
        HSCodeLookup._loaded = True  # Mark as loaded to prevent repeated attempts
    
    @property
    def total_items(self) -> int:
        """Get total number of HS Code items loaded."""
        return len(HSCodeLookup._data)
    
    def search(self, keyword: str, limit: int = 10) -> List[HSCodeItem]:
        """
        Search HS Codes by keyword (Japanese, English, or Chinese).
        
        Args:
            keyword: Search term
            limit: Maximum results to return
            
        Returns:
            List of matching HSCodeItem objects
        """
        if not keyword:
            return []
        
        keyword_lower = keyword.lower()
        results = []
        
        for item in HSCodeLookup._data:
            # Search in all language fields
            if (keyword_lower in item.japanese.lower() or
                keyword_lower in item.english.lower() or
                keyword_lower in item.chinese.lower() or
                keyword in item.hscode):
                results.append(item)
                if len(results) >= limit:
                    break
        
        return results
    
    def validate(self, hscode: str) -> bool:
        """
        Check if an HS Code exists in Japan Post database.
        
        Args:
            hscode: 10-digit HS Code to validate
            
        Returns:
            True if valid, False otherwise
        """
        if not hscode:
            return False
        
        # Normalize: remove non-digits and pad to 10 digits
        clean_code = re.sub(r'[^0-9]', '', hscode)
        if len(clean_code) < 6:
            return False
        
        # Check exact match
        if clean_code in HSCodeLookup._hscode_map:
            return True
        
        # Check 6-digit prefix match
        prefix = clean_code[:6]
        for code in HSCodeLookup._hscode_map.keys():
            if code.startswith(prefix):
                return True
        
        return False
    
    def get_by_code(self, hscode: str) -> Optional[HSCodeItem]:
        """
        Get HS Code item by exact code.
        
        Args:
            hscode: 10-digit HS Code
            
        Returns:
            HSCodeItem if found, None otherwise
        """
        clean_code = re.sub(r'[^0-9]', '', hscode)
        return HSCodeLookup._hscode_map.get(clean_code)
    
    def find_similar(self, hscode: str, limit: int = 5) -> List[HSCodeItem]:
        """
        Find HS Codes with similar prefix.
        
        Args:
            hscode: HS Code to find similar items for
            limit: Maximum results
            
        Returns:
            List of similar HSCodeItem objects
        """
        if not hscode or len(hscode) < 4:
            return []
        
        clean_code = re.sub(r'[^0-9]', '', hscode)
        prefix = clean_code[:4]  # Match first 4 digits
        
        results = []
        for item in HSCodeLookup._data:
            if item.hscode.startswith(prefix):
                results.append(item)
                if len(results) >= limit:
                    break
        
        return results
    
    def get_validated_hscode(self, ai_hscode: str, product_keywords: str = "") -> Dict[str, Any]:
        """
        Validate AI-suggested HS Code and return validated result.
        
        Args:
            ai_hscode: HS Code suggested by AI
            product_keywords: Optional product keywords for fallback search
            
        Returns:
            Dict with validated HS Code and metadata
        """
        result = {
            "original": ai_hscode,
            "validated": ai_hscode,
            "is_valid": False,
            "matched_item": None,
            "suggestions": []
        }
        
        if not ai_hscode:
            return result
        
        # Check if exact match exists
        item = self.get_by_code(ai_hscode)
        if item:
            result["is_valid"] = True
            result["matched_item"] = item.to_dict()
            return result
        
        # Check prefix match
        if self.validate(ai_hscode):
            result["is_valid"] = True
            similar = self.find_similar(ai_hscode, limit=3)
            if similar:
                result["suggestions"] = [s.to_dict() for s in similar]
            return result
        
        # Fallback: search by product keywords
        if product_keywords:
            search_results = self.search(product_keywords, limit=3)
            if search_results:
                result["suggestions"] = [s.to_dict() for s in search_results]
        
        return result


# Singleton instance for easy import
hscode_lookup = HSCodeLookup()
