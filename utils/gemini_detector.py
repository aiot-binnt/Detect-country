import re
import json
import traceback
import logging
import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError, ResourceExhausted, Unauthenticated
from typing import Dict, Any

# Constants
MODEL_NAME = "gemini-2.0-flash" 
MAX_TEXT_LENGTH = 1000

# Prompt 
SYSTEM_PROMPT = """
あなたは商品説明の製造国・属性検出の専門家です。
以下のルールに従って、商品説明から「製造国 (Country of Origin)」、「サイズ (Size)」、「素材 (Material)」を抽出してください。

【重要ルール】
1. 製造国・原産国に焦点を当ててください。配送先やブランドの所在地から推測しないでください。
2. 明示的な手がかり（例：「Made in ...」「原産国：...」）を探してください。

【出力スキーマ (JSON)】
レスポンスは必ず以下のJSON形式のみを返してください。
{
  "attributes": {
    "country": {"value": ["XX"], "evidence": "抽出した根拠テキスト", "confidence": 0.0},
    "size": {"value": "抽出値", "evidence": "抽出した根拠テキスト", "confidence": 0.0},
    "material": {"value": "抽出値", "evidence": "抽出した根拠テキスト", "confidence": 0.0}
  }
}

【抽出ルール】
1. **Country (国)**: 
   - ISO 3166-1 alpha-2 コードに正規化してください (例: Japan -> "JP", China -> "CN", Vietnam -> "VN")。
   - 見つからない場合は、value を ["ZZ"] としてください。
   - 複数の国が記載されている場合はリストで返してください (例: ["ID", "VN"])。
2. **Size (サイズ) & Material (素材)**: 
   - 見つからない場合は、value を "none" としてください。
"""

DEFAULT_ATTRIBUTES = {
    "country": {"value": ["ZZ"], "evidence": "none", "confidence": 0.0},
    "size": {"value": "none", "evidence": "none", "confidence": 0.0},
    "material": {"value": "none", "evidence": "none", "confidence": 0.0}
}

class GeminiDetector:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required")
        
        genai.configure(api_key=api_key)
        
        # Configure model with JSON enforcement
        self.model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=SYSTEM_PROMPT,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.0
            }
        )
        print(f"✓ Using Google Gemini model: {MODEL_NAME}")

    def _clean_text(self, text: str) -> str:
        """Remove HTML tags and irrelevant characters to save tokens."""
        if not text:
            return ""
        
        patterns = [
            (r'<[^>]*>', ''),  # Remove all HTML tags
            (r'[^a-zA-Z0-9\u3040-\u30ff\u4e00-\u9fff.,;:/\-\(\)\[\]（）％™\s]', ''), # Keep allowed chars
            (r'\s+', ' ') # Normalize whitespace
        ]
        
        cleaned = text
        for pattern, replacement in patterns:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.DOTALL | re.IGNORECASE)
            
        return cleaned.strip()

    def _get_default_result(self, error: str = None, code: str = None) -> Dict[str, Any]:
        """Return a standardized fallback result."""
        result = {"attributes": DEFAULT_ATTRIBUTES.copy()}
        if error:
            result["error"] = error
            result["error_code"] = code
        return result

    async def detect_country(self, text: str) -> Dict[str, Any]:
        """Main entry point to detect attributes using Gemini."""
        if not text or not text.strip():
            return self._get_default_result()
        
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
             return self._get_default_result()
        
        try:
            truncated_text = cleaned_text[:MAX_TEXT_LENGTH] + "..." if len(cleaned_text) > MAX_TEXT_LENGTH else cleaned_text
            
            # Gemini Async Call (Updated user prompt to Japanese)
            response = await self.model.generate_content_async(
                f"この商品説明を分析し、構造化JSONを返却してください。\n\n商品説明:\n{truncated_text}"
            )
            
            raw_content = response.text.strip()
            return self._parse_json_response(raw_content)

        except ResourceExhausted:
            return self._get_default_result("Gemini quota exceeded.", "QUOTA_ERROR")
        except Unauthenticated:
            return self._get_default_result("Invalid Gemini API Key.", "AUTH_ERROR")
        except GoogleAPIError as e:
            print(f"[ERROR] Gemini API Error: {e}")
            return self._get_default_result(f"API Error: {str(e)}", "API_ERROR")
        except Exception as e:
            print(f"[ERROR] Unexpected: {e}")
            traceback.print_exc()
            # Fallback to regex if AI fails completely
            return self._heuristic_fallback(text)

    def _parse_json_response(self, raw_text: str) -> Dict[str, Any]:
        """Parse JSON and ensure structure."""
        try:
            parsed = json.loads(raw_text)
            attributes = parsed.get("attributes", DEFAULT_ATTRIBUTES.copy())
            
            # Normalize country value to list if it's a string
            country_attr = attributes.get('country', {})
            if isinstance(country_attr.get('value'), str):
                country_attr['value'] = [country_attr['value']]
                attributes['country'] = country_attr
                
            return {"attributes": attributes}
        except json.JSONDecodeError:
             print("[DEBUG] JSON decode failed despite strict mode.")
             return self._get_default_result("JSON Parse Error", "INTERNAL_ERROR")

    def _heuristic_fallback(self, text: str) -> Dict[str, Any]:
        """Regex-based fallback (duplicated from base to keep file independent)."""
        attributes = DEFAULT_ATTRIBUTES.copy()
        
        # Country detection
        country_match = re.search(r'((?:made\s+in|原産国|製造国)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff]+))', text, re.IGNORECASE)
        if country_match:
            c_name = country_match.group(2).upper()
            code = "ZZ"
            if "JAPAN" in c_name or "日本" in c_name: code = "JP"
            elif "CHINA" in c_name or "中国" in c_name: code = "CN"
            elif "VIETNAM" in c_name or "ベトナム" in c_name: code = "VN"
            elif "INDONESIA" in c_name: code = "ID"
            
            if code != "ZZ":
                attributes["country"] = {"value": [code], "evidence": country_match.group(1), "confidence": 0.3}

        # Size
        size_match = re.search(r'((?:size|サイズ)[\s:/]*([A-Za-z0-9/ cmMLXS.]+))', text, re.IGNORECASE)
        if size_match:
            attributes["size"] = {"value": size_match.group(2).strip(), "evidence": size_match.group(1).strip(), "confidence": 0.3}

        # Material
        mat_match = re.search(r'((?:material|素材|材料)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff0-9％/・]+))', text, re.IGNORECASE)
        if mat_match:
             val = mat_match.group(2) if len(mat_match.groups()) > 1 else mat_match.group(1)
             attributes["material"] = {"value": val.strip(), "evidence": mat_match.group(0).strip(), "confidence": 0.3}

        return {"attributes": attributes}