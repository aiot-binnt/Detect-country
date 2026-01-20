import re
import json
import os
import traceback
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel, GenerationConfig
import vertexai

# Import HS Code Lookup for validation
try:
    from utils.hscode_lookup import hscode_lookup
    HSCODE_LOOKUP_AVAILABLE = True
except ImportError:
    HSCODE_LOOKUP_AVAILABLE = False
    hscode_lookup = None

# Constants
MODEL_NAME = "gemini-2.0-flash-exp" 
MAX_TEXT_LENGTH = 1500

# Path to prompts config file
PROMPTS_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'prompts.json')

def load_prompts(force_reload: bool = False) -> Dict[str, Any]:
    """
    Load prompts from external JSON config file.
    
    Args:
        force_reload: If True, reload from file even if already cached
        
    Returns:
        Dict containing all prompt configurations
    """
    global _prompts_cache
    
    if not force_reload and '_prompts_cache' in globals() and _prompts_cache:
        return _prompts_cache
    
    try:
        with open(PROMPTS_CONFIG_PATH, 'r', encoding='utf-8') as f:
            _prompts_cache = json.load(f)
            logging.info(f"✓ Loaded prompts from {PROMPTS_CONFIG_PATH}")
            return _prompts_cache
    except FileNotFoundError:
        logging.error(f"Prompts config file not found: {PROMPTS_CONFIG_PATH}")
        raise
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in prompts config: {e}")
        raise

# Load prompts on module import
_prompts_cache = None
try:
    _prompts_cache = load_prompts()
except Exception as e:
    logging.warning(f"Failed to load prompts config, using fallback: {e}")
    _prompts_cache = {
        "field_rules": {},
        "field_schema": {},
        "hs_code_examples": "",
        "prompt_template": "",
        "default_attributes": {
            "country": {"value": [], "evidence": "", "confidence": 0.0},
            "size": {"value": "", "evidence": "", "confidence": 0.0},
            "material": {"value": "", "evidence": "", "confidence": 0.0},
            "target_user": {"value": [], "evidence": "", "confidence": 0.0},
            "hscode": {"value": "", "evidence": "", "confidence": 0.0}
        }
    }

# Convenience accessors
def get_field_rules() -> Dict[str, str]:
    """Get field extraction rules from config."""
    prompts = load_prompts()
    return prompts.get("field_rules", {})

def get_field_schema() -> Dict[str, str]:
    """Get field output schema from config."""
    prompts = load_prompts()
    return prompts.get("field_schema", {})

def get_hs_code_examples() -> str:
    """Get HS code examples from config."""
    prompts = load_prompts()
    return prompts.get("hs_code_examples", "")

def get_prompt_template() -> str:
    """Get main prompt template from config."""
    prompts = load_prompts()
    return prompts.get("prompt_template", "")

def get_default_attributes() -> Dict[str, Any]:
    """Get default attribute values from config."""
    prompts = load_prompts()
    return prompts.get("default_attributes", {})

# Keep DEFAULT_ATTRIBUTES for backward compatibility
DEFAULT_ATTRIBUTES = get_default_attributes()


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
            # Model without static system instruction - will use dynamic prompts
            self.model = GenerativeModel(model_name=self.model_name)
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

    def _get_default_result(self, error: str = None, code: str = None, fields: list = None) -> Dict[str, Any]:
        """Return a standardized fallback result."""
        import copy
        if fields:
            # Only include requested fields
            attrs = {k: copy.deepcopy(v) for k, v in DEFAULT_ATTRIBUTES.items() if k in fields}
        else:
            attrs = copy.deepcopy(DEFAULT_ATTRIBUTES)
        result = {"attributes": attrs}
        if error:
            result["error"] = error
            result["error_code"] = code
        return result

    def _build_dynamic_prompt(self, fields: list) -> str:
        """
        Build a dynamic system prompt based on requested fields.
        This reduces token usage by only including rules for needed attributes.
        
        Args:
            fields: List of field names to detect
            
        Returns:
            Dynamic prompt string
        """
        # Load from JSON config
        field_rules = get_field_rules()
        field_schema = get_field_schema()
        hs_code_examples = get_hs_code_examples()
        prompt_template = get_prompt_template()
        
        # Build rules section - only for requested fields
        rules = []
        for i, field in enumerate(fields, 1):
            if field in field_rules:
                rule = f"{i}. {field_rules[field]}"
                rules.append(rule)
        
        # Build schema section - only for requested fields
        schema_parts = []
        for field in fields:
            if field in field_schema:
                schema_parts.append(f"    {field_schema[field]}")
        
        schema = "{\n  \"attributes\": {\n" + ",\n".join(schema_parts) + "\n  }\n}"
        
        # Include HS code examples only if hscode is requested
        hs_examples_section = hs_code_examples if "hscode" in fields else ""
        
        # Build the complete prompt using template
        if prompt_template:
            prompt = prompt_template.format(
                rules="\n".join(rules),
                hs_code_examples=hs_examples_section,
                schema=schema
            )
        else:
            # Fallback if template not available
            prompt = f"""あなたは商品説明の属性検出とHSコード分類の専門家です。

【タスク】
以下の情報から指定された商品属性のみを抽出してください。

【入力情報】
- 商品タイトル (title)
- 商品説明 (description)

【抽出する属性】
{chr(10).join(rules)}

{hs_examples_section}

【出力スキーマ (JSON)】
{schema}

【重要】
- JSONのみを出力してください
- 指定された属性のみを返却してください
- HSコードがある場合は必ず10桁で返却してください（日本郵便形式）
- confidence は 0.0 〜 1.0 の範囲で判定の確信度を記載
- 見つからない場合は、value と evidence を空にしてください（説明文は不要）
"""
        return prompt

    async def detect_product(self, title: str = "", description: str = "", fields: list = None) -> Dict[str, Any]:
        """
        Main entry point to detect product attributes and HS Code.
        
        Args:
            title: Product title
            description: Product description
            fields: List of fields to detect (e.g., ["country", "hscode"])
            
        Returns:
            Dict with detected attributes for requested fields only
        """
        # Default to all fields if not specified (for backward compatibility)
        if not fields:
            fields = list(DEFAULT_ATTRIBUTES.keys())
        
        # Validate input
        if not title and not description:
            return self._get_default_result("Both title and description are empty", "VALIDATION_ERROR", fields)
        
        # Clean and combine text
        cleaned_title = self._clean_text(title or "")
        cleaned_desc = self._clean_text(description or "")
        
        if not cleaned_title and not cleaned_desc:
            return self._get_default_result("No valid text after cleaning", "VALIDATION_ERROR", fields)
        
        try:
            # Truncate if needed
            combined_text = f"タイトル: {cleaned_title}\n説明: {cleaned_desc}"
            if len(combined_text) > MAX_TEXT_LENGTH:
                combined_text = combined_text[:MAX_TEXT_LENGTH] + "..."
            
            # Build dynamic prompt based on requested fields
            dynamic_prompt = self._build_dynamic_prompt(fields)
            
            # Vertex AI Async Call
            generation_config = GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json"
            )
            
            # Combine system prompt with user input
            full_prompt = f"{dynamic_prompt}\n\n【商品情報】\n{combined_text}"
            
            response = await self.model.generate_content_async(
                full_prompt,
                generation_config=generation_config
            )
            
            raw_content = response.text.strip()
            return self._parse_json_response(raw_content, fields)

        except Exception as e:
            error_str = str(e).lower()
            
            # Handle specific Vertex AI errors
            if "quota" in error_str or "resource exhausted" in error_str:
                return self._get_default_result("Vertex AI quota exceeded. Please try again later.", "QUOTA_ERROR", fields)
            elif "permission" in error_str or "unauthorized" in error_str or "unauthenticated" in error_str:
                return self._get_default_result("Invalid credentials or insufficient permissions.", "AUTH_ERROR", fields)
            elif "not found" in error_str:
                return self._get_default_result(f"Model '{self.model_name}' not found or not available.", "MODEL_ERROR", fields)
            elif "invalid" in error_str and "api" in error_str:
                return self._get_default_result("Invalid API configuration. Please check your settings.", "CONFIG_ERROR", fields)
            else:
                logging.error(f"Vertex AI Error: {e}", exc_info=True)
                # Fallback to regex if AI fails completely
                return self._heuristic_fallback(title or "", description or "", fields)

    # Keep old method name for backward compatibility
    async def detect_country(self, text: str) -> Dict[str, Any]:
        """
        Legacy method for backward compatibility.
        Treats input as description only.
        """
        return await self.detect_product(title="", description=text)

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

    def _validate_hscode(self, hscode_value: str) -> str:
        """Validate and normalize HS Code to 10 digits (Japan Post format)."""
        if not hscode_value:
            return ""
        
        # Remove non-digits
        digits_only = re.sub(r'[^0-9]', '', str(hscode_value))
        
        # Take first 10 digits if longer
        if len(digits_only) >= 10:
            return digits_only[:10]
        elif len(digits_only) >= 6:
            # Pad with zeros to reach 10 digits
            return digits_only.ljust(10, '0')
        elif len(digits_only) > 0:
            # Too short, pad to 10 digits
            return digits_only.ljust(10, '0')
        
        return ""

    def _parse_json_response(self, raw_text: str, fields: list = None) -> Dict[str, Any]:
        """Parse JSON and ensure structure, filtering to requested fields only."""
        try:
            parsed = json.loads(raw_text)
            import copy
            all_attributes = parsed.get("attributes", {})
            
            # Filter to only requested fields
            if fields:
                attributes = {}
                for field in fields:
                    if field in all_attributes:
                        attributes[field] = all_attributes[field]
                    else:
                        attributes[field] = copy.deepcopy(DEFAULT_ATTRIBUTES.get(field, {}))
            else:
                attributes = all_attributes
            
            # Normalize country value to list if it's a string
            if 'country' in attributes:
                country_attr = attributes.get('country', {})
                if isinstance(country_attr.get('value'), str):
                    country_attr['value'] = [country_attr['value']] if country_attr['value'] else []
                    attributes['country'] = country_attr
            
            # Normalize target_user value to list if it's a string
            if 'target_user' in attributes:
                target_user_attr = attributes.get('target_user', {})
                if isinstance(target_user_attr.get('value'), str):
                    target_user_attr['value'] = [target_user_attr['value']] if target_user_attr['value'] else []
                    attributes['target_user'] = target_user_attr
            
            # Validate and normalize HS Code
            if 'hscode' in attributes:
                hscode_attr = attributes.get('hscode', {})
                if hscode_attr:
                    original_hscode = hscode_attr.get('value', '')
                    validated_hscode = self._validate_hscode(original_hscode)
                    hscode_attr['value'] = validated_hscode
                    
                    # Validate against Japan Post database if available
                    if HSCODE_LOOKUP_AVAILABLE and hscode_lookup and validated_hscode:
                        validation_result = hscode_lookup.get_validated_hscode(validated_hscode)
                        hscode_attr['validated'] = validation_result.get('is_valid', False)
                        if validation_result.get('suggestions'):
                            hscode_attr['suggestions'] = validation_result['suggestions'][:2]
                    
                    attributes['hscode'] = hscode_attr
            
            # Sanitize all attributes to remove newlines and extra whitespace
            attributes = self._sanitize_attributes(attributes)
                
            return {"attributes": attributes}
        except json.JSONDecodeError as e:
            logging.warning(f"JSON decode failed: {e}")
            return self._get_default_result("Failed to parse AI response", "PARSE_ERROR", fields)

    def _heuristic_fallback(self, title: str, description: str, fields: list = None) -> Dict[str, Any]:
        """Regex-based fallback when AI fails. Only detects requested fields."""
        import copy
        
        # Default to all fields if not specified
        if not fields:
            fields = list(DEFAULT_ATTRIBUTES.keys())
        
        # Start with default values for requested fields only
        attributes = {k: copy.deepcopy(v) for k, v in DEFAULT_ATTRIBUTES.items() if k in fields}
        text = f"{title} {description}"
        
        # Country detection
        if "country" in fields:
            country_match = re.search(r'((?:made\s+in|原産国|製造国)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff]+))', text, re.IGNORECASE)
            if country_match:
                c_name = country_match.group(2).upper()
                code = ""
                if "JAPAN" in c_name or "日本" in c_name: code = "JP"
                elif "CHINA" in c_name or "中国" in c_name: code = "CN"
                elif "VIETNAM" in c_name or "ベトナム" in c_name: code = "VN"
                elif "INDONESIA" in c_name: code = "ID"
                
                if code:
                    attributes["country"] = {"value": [code], "evidence": country_match.group(1), "confidence": 0.3}

        # Size
        if "size" in fields:
            size_match = re.search(r'((?:size|サイズ)[\s:/]*([A-Za-z0-9/ cmMLXS.]+))', text, re.IGNORECASE)
            if size_match:
                attributes["size"] = {"value": size_match.group(2).strip(), "evidence": size_match.group(1).strip(), "confidence": 0.3}

        # Material
        if "material" in fields:
            mat_match = re.search(r'((?:material|素材|材料)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff0-9％/・]+))', text, re.IGNORECASE)
            if mat_match:
                 val = mat_match.group(2) if len(mat_match.groups()) > 1 else mat_match.group(1)
                 attributes["material"] = {"value": val.strip(), "evidence": mat_match.group(0).strip(), "confidence": 0.3}

        # Target User - collect all matches
        if "target_user" in fields:
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

        # HS Code heuristic (basic category detection - Japan Post 10-digit format)
        if "hscode" in fields:
            hscode_patterns = [
                (r'(laptop|ノートパソコン|ノートPC)', '8471300000', 'Laptop computer'),
                (r'(earring|イヤリング|ピアス)', '7117900000', 'Earring/jewelry'),
                (r'(eyeshadow|アイシャドウ)', '3304200000', 'Eyeshadow cosmetic'),
                (r'(dress|ワンピース|ドレス)', '6204421090', 'Dress for women'),
                (r'(t-?shirt|Tシャツ)', '6109100099', 'T-shirt cotton'),
                (r'(pants|パンツ|ズボン)', '6204631890', 'Pants for women synthetic'),
                (r'(jacket|ジャケット|ブルゾン)', '6201931000', 'Jacket'),
                (r'(coat|コート)', '6201121090', 'Coat'),
                (r'(sweater|セーター|ニット)', '6110301090', 'Sweater knitted'),
                (r'(bag|バッグ|ポーチ)', '4202290090', 'Bag/Pouch'),
            ]
            
            for pattern, code, evidence in hscode_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    attributes["hscode"] = {"value": code, "evidence": evidence, "confidence": 0.3}
                    break

        return {"attributes": attributes}