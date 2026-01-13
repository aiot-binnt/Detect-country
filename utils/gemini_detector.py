import re
import json
import os
import traceback
import logging
from typing import Dict, Any, Optional
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel, GenerationConfig
import vertexai

# Constants
MODEL_NAME = "gemini-2.0-flash-exp" 
MAX_TEXT_LENGTH = 1000

# Prompt 
SYSTEM_PROMPT = """
あなたは商品説明の製造国・属性検出の専門家です。
以下のルールに従って、商品説明から「製造国 (Country of Origin)」、「サイズ (Size)」、「素材 (Material)」、「対象ユーザー (Target User)」を抽出してください。

【重要ルール】
1. 製造国・原産国に焦点を当ててください。配送先やブランドの所在地から推測しないでください。
2. 明示的な手がかり（例：「Made in ...」「原産国：...」）を探してください。

【出力スキーマ (JSON)】
レスポンスは必ず以下のJSON形式のみを返してください。
{
  "attributes": {
    "country": {"value": ["XX"], "evidence": "抽出した根拠テキスト", "confidence": 0.0},
    "size": {"value": "抽出値", "evidence": "抽出した根拠テキスト", "confidence": 0.0},
    "material": {"value": "抽出値", "evidence": "抽出した根拠テキスト", "confidence": 0.0},
    "target_user": {"value": ["抽出値1", "抽出値2"], "evidence": "抽出した根拠テキスト", "confidence": 0.0}
  }
}

【抽出ルール】
1. **Country (国)**: 
   - ISO 3166-1 alpha-2 コードに正規化してください (例: Japan -> "JP", China -> "CN", Vietnam -> "VN")。
   - 見つからない場合は、value を [] (空の配列) としてください。
   - 複数の国が記載されている場合はリストで返してください (例: ["ID", "VN"])。
2. **Size (サイズ) & Material (素材)**: 
   - 見つからない場合は、value を "none" としてください。
3. **Target User (対象ユーザー)**:
   - 商品の対象者/使用者を特定してください。
   - 値は以下から選択: "children", "adult", "men", "women", "senior", "baby", "unisex"
   - 複数の対象者がある場合はリストで返してください（例: ["women", "men"]）。
   - 見つからない場合は、value を [] (空の配列) としてください。
"""

DEFAULT_ATTRIBUTES = {
    "country": {"value": [], "evidence": "none", "confidence": 0.0},
    "size": {"value": "none", "evidence": "none", "confidence": 0.0},
    "material": {"value": "none", "evidence": "none", "confidence": 0.0},
    "target_user": {"value": [], "evidence": "none", "confidence": 0.0}
}

class GeminiDetector:
    def __init__(self, model_name: Optional[str] = None):
        """
        Initialize Gemini Detector with Vertex AI using service account authentication.
        
        Args:
            model_name: Optional model name (defaults to MODEL_NAME)
        
        Raises:
            ValueError: If GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_CLOUD_PROJECT is not set
        """
        self.model_name = model_name or MODEL_NAME
        
        # Check if service account credentials are available
        service_account_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
        location = os.getenv('GCP_LOCATION', 'us-central1')
        
        if not service_account_path:
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS environment variable is required. "
                "Please set it to the path of your service account JSON file."
            )
        
        if not project_id:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT environment variable is required. "
                "Please set it to your GCP project ID."
            )
        
        # Initialize Vertex AI with service account
        try:
            vertexai.init(project=project_id, location=location)
            self.model = GenerativeModel(
                model_name=self.model_name,
                system_instruction=SYSTEM_PROMPT
            )
            logging.info(f"✓ Using Vertex AI with Service Account: {self.model_name} (Project: {project_id}, Location: {location})")
        except Exception as e:
            logging.error(f"Failed to initialize Vertex AI with service account: {e}")
            raise ValueError(f"Vertex AI initialization failed: {e}")

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
            
            # Vertex AI Async Call
            generation_config = GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json"
            )
            
            response = await self.model.generate_content_async(
                f"この商品説明を分析し、構造化JSONを返却してください。\n\n商品説明:\n{truncated_text}",
                generation_config=generation_config
            )
            
            raw_content = response.text.strip()
            return self._parse_json_response(raw_content)

        except Exception as e:
            error_str = str(e).lower()
            
            # Handle specific Vertex AI errors
            if "quota" in error_str or "resource exhausted" in error_str:
                return self._get_default_result("Vertex AI quota exceeded.", "QUOTA_ERROR")
            elif "permission" in error_str or "unauthorized" in error_str or "unauthenticated" in error_str:
                return self._get_default_result("Invalid credentials or insufficient permissions.", "AUTH_ERROR")
            elif "not found" in error_str:
                return self._get_default_result(f"Model '{self.model_name}' not found or not available.", "MODEL_ERROR")
            else:
                logging.error(f"Vertex AI Error: {e}", exc_info=True)
                # Fallback to regex if AI fails completely
                return self._heuristic_fallback(text)

    def _sanitize_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean newlines, extra whitespace, and special characters from attribute values.
        Ensures clean JSON responses without formatting artifacts.
        """
        sanitized = {}
        
        for attr_name, attr_data in attributes.items():
            if not isinstance(attr_data, dict):
                sanitized[attr_name] = attr_data
                continue
            
            sanitized_data = {}
            for key, value in attr_data.items():
                if key in ['value', 'evidence'] and isinstance(value, str):
                    # Remove newlines and normalize whitespace
                    cleaned = value.replace('\n', ' ').replace('\r', ' ')
                    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                    sanitized_data[key] = cleaned
                elif key == 'value' and isinstance(value, list):
                    # Clean list values
                    sanitized_data[key] = [
                        v.replace('\n', ' ').replace('\r', ' ').strip() 
                        if isinstance(v, str) else v 
                        for v in value
                    ]
                else:
                    sanitized_data[key] = value
            
            sanitized[attr_name] = sanitized_data
        
        return sanitized

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
            
            # Normalize target_user value to list if it's a string
            target_user_attr = attributes.get('target_user', {})
            if isinstance(target_user_attr.get('value'), str):
                target_user_attr['value'] = [target_user_attr['value']]
                attributes['target_user'] = target_user_attr
            
            # Sanitize all attributes to remove newlines and extra whitespace
            attributes = self._sanitize_attributes(attributes)
                
            return {"attributes": attributes}
        except json.JSONDecodeError:
             logging.warning("JSON decode failed despite strict mode")
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

        # Target User - collect all matches
        target_patterns = [
            (r'((?:for|向け|対象)[\s:]*((?:kids?|children|baby|infant|toddler|キッズ|子供|こども|ベビー|赤ちゃん|幼児)))', 'children'),
            (r'((?:for|向け|対象)[\s:]*((?:adult|大人|おとな|成人)))', 'adult'),
            (r'((?:for|向け|対象)[\s:]*((?:men|male|メンズ|男性|紳士)))', 'men'),
            (r'((?:for|向け|対象)[\s:]*((?:women|ladies|female|レディース|女性|婦人)))', 'women'),
            (r'((?:for|向け|対象)[\s:]*((?:senior|elderly|シニア|高齢者|お年寄り)))', 'senior'),
            (r'((?:for|向け|対象)[\s:]*((?:unisex|ユニセックス|男女兼用)))', 'unisex'),
            # Direct mentions without prefix
            (r'(キッズ|子供用|子ども用)', 'children'),
            (r'(ベビー用|赤ちゃん用|乳児用)', 'baby'),
            (r'(メンズ|男性用|紳士用)', 'men'),
            (r'(レディース|女性用|婦人用)', 'women'),
            (r'(シニア|高齢者用)', 'senior'),
        ]
        
        found_users = []
        evidence_list = []
        
        for pattern, user_type in target_patterns:
            target_match = re.search(pattern, text, re.IGNORECASE)
            if target_match and user_type not in found_users:
                found_users.append(user_type)
                evidence_list.append(target_match.group(0).strip())
        
        if found_users:
            attributes["target_user"] = {
                "value": found_users, 
                "evidence": " ".join(evidence_list), 
                "confidence": 0.3
            }

        return {"attributes": attributes}