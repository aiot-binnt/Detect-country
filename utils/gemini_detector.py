import re
import json
import os
import traceback
import logging
from typing import Dict, Any, Optional
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

# HS Code Reference Examples from Japan Post (10-digit format)
# Source: https://www.post.japanpost.jp/int/use/publication/contentslist/index.php
# VERIFIED DATA from Japan Post official website
HS_CODE_EXAMPLES = """
【HSコード参考例 - Japan Post公式 10桁形式】
※ 以下は日本郵便公式ウェブサイトから取得した正確なHSコードです。

■ 衣類 (Clothing):
- ズボン（女性用 合成繊維）Pants for women, synthetic → 6204631890
- ズボン（女性用 綿製）Pants for women, cotton → 6204621090
- ズボン（男性用 合成繊維）Pants for men, synthetic → 6203431890
- ズボン（男性用 綿製）Pants for men, cotton → 6203421090
- アイマスク Eye Mask → 6307909899

■ 電子機器 (Electronics):
- IHコンロ IH cooking heater → 8516609000
- アイロン Clothing Iron → 8451300000
- アダプター Adapter → 8471900000
- アコースティックギター Acoustic Guitar → 9202903000

■ 化粧品 (Cosmetics):
- アイシャドウ Eyeshadow → 3304200000
- アイブロウペンシル Eyebrow Pencil → 3304200000
- アイライナー Eyeliner → 3304200000
- 油絵具 Oil Color → 3213100000

■ 食品 (Food):
- アーモンド Almond → 0802129000
- アーモンドミルク Almond Milk → 2009899999
- 青汁（糖が添加） Green Juice with sugar → 2009905180
- 青汁（糖が添加されていない） Green Juice without sugar → 2009905990
- 青のり Green Laver → 1212210000
- あずき Red Bean → 0713320000
- 甘栗 Baked Chestnut → 2008199980
- 飴 Candy → 1704909919

■ 日用品 (Daily goods):
- アイラッシュカーラー Eyelash Curler → 9615900000
- アクリルスタンド Acrylic Stand Figure → 9503002190
- 圧縮バッグ Compression bag → 4202929890
- 編針 Knitting Needles → 7319901000

■ 医薬品 (Medicine):
- アスピリン Aspirin → 3004900000

【重要な注意事項】
- 上記のHSコードは日本郵便公式サイトから取得した正確なデータです
- 商品の素材、性別、用途によってHSコードが異なります
- 判断に迷う場合は日本郵便公式サイトで検索してください
- URL: https://www.post.japanpost.jp/int/use/publication/contentslist/index.php
"""

# Updated System Prompt with HS Code Detection (Japan Post 10-digit format)
SYSTEM_PROMPT = f"""
あなたは商品説明の属性検出とHSコード分類の専門家です。

【タスク】
以下の情報から商品属性を抽出し、日本郵便のHSコード（10桁形式）を判定してください。

【入力情報】
- 商品タイトル (title)
- 商品説明 (description)

【抽出ルール】
1. **Country (製造国/原産国)**: 
   - ISO 3166-1 alpha-2 コードに正規化 (例: Japan → "JP", China → "CN")
   - 見つからない場合: value を [], evidence を "" (空文字)
   - 複数の国がある場合はリストで返却 (例: ["ID", "VN"])

2. **Size (サイズ)**: 
   - 見つからない場合: value を "", evidence を "" (空文字)

3. **Material (素材)**: 
   - 見つからない場合: value を "", evidence を "" (空文字)

4. **Target User (対象ユーザー)**:
   - 値は: "children", "adult", "men", "women", "senior", "baby", "unisex" から選択
   - 見つからない場合: value を [], evidence を "" (空文字)

5. **HS Code (HSコード) - 日本郵便10桁形式**:
   - 上記で抽出した title, description, material, size, target_user を総合的に判断
   - **必ず10桁のHSコードを返却** (例: "6204631890", "6109100099")
   - 日本郵便の公式HSコード表に基づいて判定
   - 判定できない場合: value を "", evidence を "" (空文字)

{HS_CODE_EXAMPLES}

【出力スキーマ (JSON)】
{{
  "attributes": {{
    "country": {{"value": ["XX"], "evidence": "根拠テキスト", "confidence": 0.0}},
    "size": {{"value": "抽出値", "evidence": "根拠テキスト", "confidence": 0.0}},
    "material": {{"value": "抽出値", "evidence": "根拠テキスト", "confidence": 0.0}},
    "target_user": {{"value": ["抽出値"], "evidence": "根拠テキスト", "confidence": 0.0}},
    "hscode": {{"value": "10桁コード", "evidence": "判定根拠", "confidence": 0.0}}
  }}
}}

【重要】
- JSONのみを出力してください
- HSコードは必ず10桁で返却してください（日本郵便形式）
- confidence は 0.0 〜 1.0 の範囲で判定の確信度を記載
- 見つからない場合は、value と evidence を空にしてください（説明文は不要）
"""

DEFAULT_ATTRIBUTES = {
    "country": {"value": [], "evidence": "", "confidence": 0.0},
    "size": {"value": "", "evidence": "", "confidence": 0.0},
    "material": {"value": "", "evidence": "", "confidence": 0.0},
    "target_user": {"value": [], "evidence": "", "confidence": 0.0},
    "hscode": {"value": "", "evidence": "", "confidence": 0.0}
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
        import copy
        result = {"attributes": copy.deepcopy(DEFAULT_ATTRIBUTES)}
        if error:
            result["error"] = error
            result["error_code"] = code
        return result

    async def detect_product(self, title: str = "", description: str = "") -> Dict[str, Any]:
        """
        Main entry point to detect product attributes and HS Code.
        
        Args:
            title: Product title
            description: Product description
            
        Returns:
            Dict with detected attributes including hscode
        """
        # Validate input
        if not title and not description:
            return self._get_default_result("Both title and description are empty", "VALIDATION_ERROR")
        
        # Clean and combine text
        cleaned_title = self._clean_text(title or "")
        cleaned_desc = self._clean_text(description or "")
        
        if not cleaned_title and not cleaned_desc:
            return self._get_default_result("No valid text after cleaning", "VALIDATION_ERROR")
        
        try:
            # Truncate if needed
            combined_text = f"タイトル: {cleaned_title}\n説明: {cleaned_desc}"
            if len(combined_text) > MAX_TEXT_LENGTH:
                combined_text = combined_text[:MAX_TEXT_LENGTH] + "..."
            
            # Vertex AI Async Call
            generation_config = GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json"
            )
            
            response = await self.model.generate_content_async(
                f"この商品情報を分析し、属性とHSコードを判定してください。\n\n{combined_text}",
                generation_config=generation_config
            )
            
            raw_content = response.text.strip()
            return self._parse_json_response(raw_content)

        except Exception as e:
            error_str = str(e).lower()
            
            # Handle specific Vertex AI errors
            if "quota" in error_str or "resource exhausted" in error_str:
                return self._get_default_result("Vertex AI quota exceeded. Please try again later.", "QUOTA_ERROR")
            elif "permission" in error_str or "unauthorized" in error_str or "unauthenticated" in error_str:
                return self._get_default_result("Invalid credentials or insufficient permissions.", "AUTH_ERROR")
            elif "not found" in error_str:
                return self._get_default_result(f"Model '{self.model_name}' not found or not available.", "MODEL_ERROR")
            elif "invalid" in error_str and "api" in error_str:
                return self._get_default_result("Invalid API configuration. Please check your settings.", "CONFIG_ERROR")
            else:
                logging.error(f"Vertex AI Error: {e}", exc_info=True)
                # Fallback to regex if AI fails completely
                return self._heuristic_fallback(title or "", description or "")

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

    def _parse_json_response(self, raw_text: str) -> Dict[str, Any]:
        """Parse JSON and ensure structure."""
        try:
            parsed = json.loads(raw_text)
            import copy
            attributes = parsed.get("attributes", copy.deepcopy(DEFAULT_ATTRIBUTES))
            
            # Normalize country value to list if it's a string
            country_attr = attributes.get('country', {})
            if isinstance(country_attr.get('value'), str):
                country_attr['value'] = [country_attr['value']] if country_attr['value'] else []
                attributes['country'] = country_attr
            
            # Normalize target_user value to list if it's a string
            target_user_attr = attributes.get('target_user', {})
            if isinstance(target_user_attr.get('value'), str):
                target_user_attr['value'] = [target_user_attr['value']] if target_user_attr['value'] else []
                attributes['target_user'] = target_user_attr
            
            # Validate and normalize HS Code
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
            return self._get_default_result("Failed to parse AI response", "PARSE_ERROR")

    def _heuristic_fallback(self, title: str, description: str) -> Dict[str, Any]:
        """Regex-based fallback when AI fails."""
        import copy
        attributes = copy.deepcopy(DEFAULT_ATTRIBUTES)
        text = f"{title} {description}"
        
        # Country detection
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

        # HS Code heuristic (basic category detection - Japan Post 10-digit format)
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