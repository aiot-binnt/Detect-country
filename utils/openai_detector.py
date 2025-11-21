import re
import json
import traceback
from typing import Dict, Any, Optional
from openai import AsyncOpenAI, APIError, RateLimitError, AuthenticationError

# Constants
MODEL_NAME = "gpt-4o-mini"
MAX_TEXT_LENGTH = 1000
SYSTEM_PROMPT = """あなたは商品説明の製造国・属性検出の専門家です。製造国や原産国に焦点を当て、配送先やブランド名から推測しないでください。
... (Keep your original long prompt here - shortened for brevity in this view) ...
JSONのみ出力。"""

DEFAULT_ATTRIBUTES = {
    "country": {"value": ["ZZ"], "evidence": "none", "confidence": 0.0},
    "size": {"value": "none", "evidence": "none", "confidence": 0.0},
    "material": {"value": "none", "evidence": "none", "confidence": 0.0}
}

class OpenAIDetector:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required")
        
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = MODEL_NAME
        print(f"✓ Using OpenAI model: {self.model}")
    
    def _clean_text(self, text: str) -> str:
        """Remove HTML tags and irrelevant characters to save tokens."""
        if not text:
            return ""
        
        # Consolidated regex patterns
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
        """Main entry point to detect attributes."""
        if not text or not text.strip():
            return self._get_default_result()
        
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
             return self._get_default_result()
        
        try:
            truncated_text = cleaned_text[:MAX_TEXT_LENGTH] + "..." if len(cleaned_text) > MAX_TEXT_LENGTH else cleaned_text
            return await self._call_openai(truncated_text, text)

        except RateLimitError:
            return self._get_default_result("OpenAI quota exceeded.", "QUOTA_ERROR")
        except AuthenticationError:
            return self._get_default_result("Invalid API Key.", "AUTH_ERROR")
        except APIError as e:
            print(f"[ERROR] OpenAI API Error: {e}")
            return self._get_default_result(f"API Error: {str(e)}", "API_ERROR")
        except Exception as e:
            print(f"[ERROR] Unexpected: {e}")
            traceback.print_exc()
            return self._get_default_result(f"Internal Error: {str(e)}", "INTERNAL_ERROR")

    async def _call_openai(self, text_for_prompt: str, original_text: str) -> Dict[str, Any]:
        """Handle API call and parsing."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"この商品説明を分析し、構造化JSONを返却してください。\n\n商品説明:\n{text_for_prompt}\n\n出力JSON:"}
            ],
            temperature=0.0,
            max_tokens=400,
            top_p=0.8
        )
        
        if not response.choices or not response.choices[0].message.content:
            return self._get_default_result()

        raw_content = response.choices[0].message.content.strip()
        
        try:
            return self._parse_json_response(raw_content)
        except json.JSONDecodeError:
            print(f"[DEBUG] JSON parse failed, using heuristic fallback.")
            return self._heuristic_fallback(original_text)

    def _parse_json_response(self, raw_text: str) -> Dict[str, Any]:
        """Parse JSON and ensure structure."""
        parsed = json.loads(raw_text)
        attributes = parsed.get("attributes", DEFAULT_ATTRIBUTES.copy())
        
        # Normalize country value to list if it's a string
        country_attr = attributes.get('country', {})
        if isinstance(country_attr.get('value'), str):
            country_attr['value'] = [country_attr['value']]
            attributes['country'] = country_attr
            
        return {"attributes": attributes}

    def _heuristic_fallback(self, text: str) -> Dict[str, Any]:
        """Regex-based fallback when LLM fails."""
        attributes = DEFAULT_ATTRIBUTES.copy()
        
        # Country detection
        country_match = re.search(r'((?:made\s+in|原産国|製造国)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff]+))', text, re.IGNORECASE)
        if country_match:
            c_name = country_match.group(2).upper()
            code = "ZZ"
            # Simple mapping (Extensible)
            if "JAPAN" in c_name or "日本" in c_name: code = "JP"
            elif "CHINA" in c_name or "中国" in c_name: code = "CN"
            elif "VIETNAM" in c_name or "ベトナム" in c_name: code = "VN"
            elif "INDONESIA" in c_name: code = "ID"
            
            if code != "ZZ":
                attributes["country"] = {"value": [code], "evidence": country_match.group(1), "confidence": 0.3}

        # Size detection
        size_match = re.search(r'((?:size|サイズ)[\s:/]*([A-Za-z0-9/ cmMLXS.]+))', text, re.IGNORECASE)
        if size_match:
            attributes["size"] = {"value": size_match.group(2).strip(), "evidence": size_match.group(1).strip(), "confidence": 0.3}

        # Material detection
        mat_match = re.search(r'((?:material|素材|材料)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff0-9％/・]+))', text, re.IGNORECASE)
        if not mat_match:
            mat_match = re.search(r'(カシミヤ|cashmere|cotton|wool)', text, re.IGNORECASE)
            
        if mat_match:
             val = mat_match.group(2) if len(mat_match.groups()) > 1 else mat_match.group(1)
             evidence = mat_match.group(0) # simplified
             attributes["material"] = {"value": val.strip(), "evidence": evidence.strip(), "confidence": 0.3}

        return {"attributes": attributes}