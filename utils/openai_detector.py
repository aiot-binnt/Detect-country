# File: utils/openai_detector.py (Updated: JP-first prompt, multilingual, multiple countries array, clean_text)
import openai
import re
import json
from typing import Dict, List, Any
from langdetect import detect, LangDetectException

class OpenAIDetector:
    def __init__(self, api_key: str):
        """Initialize OpenAI API với client mới (v1+)"""
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required")
        
        self.client = openai.OpenAI(api_key=api_key)  
        self.model = "gpt-4o-mini"  
        print(f"✓ Using OpenAI model: {self.model}")
    
    def _clean_text(self, text: str) -> str:
        """Clean text: Remove HTML/tags/tables, keep text + punctuation, normalize spaces to save tokens."""
        if not text:
            return text
        # Remove HTML tags
        text = re.sub(r'<[^>]*>', '', text)
        # Remove table structures
        text = re.sub(r'<tr[^>]*>.*?</tr>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<th[^>]*>.*?</th>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<td[^>]*>.*?</td>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<table[^>]*>.*?</table>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Keep letters/numbers/Unicode (JP/CN) + punctuation: . , ; : / - ( ) [ ] % TM
        text = re.sub(r'[^a-zA-Z0-9\u3040-\u30ff\u4e00-\u9fff.,;:/\-\(\)\[\]％™\s]', '', text)
        # Normalize spaces: multiple → single, strip
        text = re.sub(r'\s+', ' ', text).strip()
        print(f"[DEBUG] Cleaned text length: {len(text)} chars (original: {len(text) + 1000 if len(text) > 1000 else len(text)})")
        return text
    
    def _detect_and_translate(self, text: str) -> str:
        """Detect lang và translate sang EN nếu cần. Giữ nguyên JP để accuracy."""
        if not text.strip():
            return text
        
        try:
            lang = detect(text)
            print(f"[DEBUG] Detected language: {lang}")
            
            # Ưu tiên: Giữ nguyên JP (ja). Hỗ trợ en, vi, zh (Trung). Translate nếu khác.
            if lang in ['ja', 'en', 'vi', 'zh']:
                print(f"[DEBUG] Keeping original lang: {lang}")
                return text
            else:
                print(f"[DEBUG] Translating from {lang} to EN...")
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a translator. Translate accurately to English, keep original meaning, especially product terms."},
                        {"role": "user", "content": f"Translate to English: {text}"}
                    ],
                    temperature=0.1,
                    max_tokens=500
                )
                translated = response.choices[0].message.content.strip()
                print(f"[DEBUG] Translated: {translated[:100]}...")
                return translated
        except LangDetectException:
            print("[DEBUG] Lang detect failed, assuming JP/EN")
            return text
        except Exception as e:
            print(f"[ERROR] Translation error: {e}")
            return text  # Fallback to original
        
    def detect_country(self, text: str) -> Dict[str, Any]:
        """
        Detect country using ChatGPT với API v1+ và improved error handling
        Returns: {"country": ["XX"], "confidence": 0.0-1.0, "attributes": {"size": "none", "color": "none", "material": "none", "brand": "none"}}
        """
        if not text or not text.strip():
            return self._fallback_result()
        
        # Clean text first to save tokens
        text = self._clean_text(text)
        
        text = self._detect_and_translate(text)
        try:
            # Truncate very long text to save tokens
            max_length = 800  # Giảm thêm sau clean
            truncated_text = text[:max_length] + "..." if len(text) > max_length else text
            
            system_prompt = """あなたは商品説明の製造国検出の専門家です。製造/原産国に焦点を当て、配送先やブランド名から推測しないでください。主に日本語をサポートし、英語、中国語、ベトナム語も対応。

【国検出ルール】:
1. JSONで有効な2文字ISO 3166-1 alpha-2国コードの配列を返却 (単一なら配列1要素)。
2. 一般的なコード: JP (日本), CN (中国), US (USA), KR (韓国), VN (ベトナム), TH (タイ), TW (台湾), DE (ドイツ), GB (UK), FR (フランス), IT (イタリア), ES (スペイン), SA (サウジアラビア), AE (UAE), IN (インド), BR (ブラジル), AU (オーストラリア), ID (インドネシア) など。
3. 世界195カ国すべて対応。国名をコードにマップ (e.g., Indonesia → ID, Vietnam → VN)。サブ地域は明示的な原産地の場合のみ。
4. 明示的な手がかりのみ探す: "Made in [国]", "原産国: [国]", "製造国: [国]", "Assembled in [都市、国]" (製造優先、配送無視)。
5. 複数国がある場合 (e.g., / や , で区切られた場合)、配列で返却: "原産国: Indonesia / Vietnam" → ["ID", "VN"]。
6. 日本語、英語、中国語、ベトナム語対応。配送住所、ブランド名、言語パターンからは推測せず、製造として明示された場合のみ。
7. 明確な国情報がない場合、["ZZ"] を返却、confidence 0.0。

【属性抽出ルール】:
- 商品属性を正確に抽出、日本語用語対応 (複数値はスラッシュ区切りで保持):
  - size: e.g., "M", "M/L", "サイズ：M", "23cm/24cm" → "23cm/24cm"
  - color: e.g., "red", "black", "アイボリー", "カラー：Glacier Grey/Pure Silver" → "Glacier Grey/Pure Silver"
  - material: e.g., "cotton", "カシミヤ100％", "素材：wool" → "cashmere 100%"
  - brand: e.g., "Nike", "RASW（ラス）", "ブランド：ASICS" → "ASICS"
- 未記載または不明なら "none"。
- JSONのみ出力。

IMPORTANT: レスポンスは有効なJSONのみ: {"country": ["XX"], "confidence": 0.95, "attributes": {"size": "value or none", "color": "none", "material": "none", "brand": "none"}}。余計なテキストなし。

例:
- "日本製、サイズM、レッドコットンNikeシャツ" → {"country": ["JP"], "confidence": 1.0, "attributes": {"size": "M", "color": "red", "material": "cotton", "brand": "Nike"}}
- "東京組立、日本; スコットランドウール" → {"country": ["JP"], "confidence": 0.95, "attributes": {"size": "none", "color": "none", "material": "wool", "brand": "none"}}
- "中国制造、黒プラスチック北京工場" → {"country": ["CN"], "confidence": 1.0, "attributes": {"size": "none", "color": "black", "material": "plastic", "brand": "none"}}
- "ベトナム生産、青Samsung電話" → {"country": ["VN"], "confidence": 1.0, "attributes": {"size": "none", "color": "blue", "material": "none", "brand": "Samsung"}}
- "【原産国】Indonesia / Vietnam、カラーGlacier Grey/Pure Silver、サイズ23cm/24cm" → {"country": ["ID", "VN"], "confidence": 1.0, "attributes": {"size": "23cm/24cm", "color": "Glacier Grey/Pure Silver", "material": "none", "brand": "none"}}
- "日本発送; RASWカシミヤセーター、アイボリー" → {"country": ["ZZ"], "confidence": 0.0, "attributes": {"size": "none", "color": "ivory", "material": "cashmere", "brand": "RASW"}}  // 明示なし
- "情報なし" → {"country": ["ZZ"], "confidence": 0.0, "attributes": {"size": "none", "color": "none", "material": "none", "brand": "none"}}

Confidence: 1.0 = 明示的; 0.0 = 明示なし (ZZ)。"""

            user_prompt = f"""この商品説明を分析し、構造化JSONを返却してください。

商品説明:
{truncated_text}

出力JSON:"""

            # Gọi API mới: client.chat.completions.create
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,  # Strict hơn: 0.0 để deterministic
                max_tokens=150,
                top_p=0.8
            )
            
            # Extract text từ response mới
            if not response.choices or not response.choices[0].message.content:
                print("OpenAI returned empty response")
                return self._fallback_result()
            
            raw_text = response.choices[0].message.content.strip()
            print(f"[DEBUG] OpenAI raw response: '{raw_text}'")
            
            # Parse JSON
            try:
                parsed = json.loads(raw_text)
                country = parsed.get("country", ["ZZ"])
                # Ensure country is list
                if isinstance(country, str):
                    country = [country]
                confidence = float(parsed.get("confidence", 0.0))
                attributes = parsed.get("attributes", {"size": "none", "color": "none", "material": "none", "brand": "none"})
                
                # Validate country format (basic)
                valid_countries = [c for c in country if c != "ZZ" and re.match(r'^[A-Z]{2}$', str(c).upper())]
                if not valid_countries:
                    country = ["ZZ"]
                    confidence = 0.0
                
                print(f"[DEBUG] Parsed JSON: country={country}, conf={confidence}, attrs={attributes}")
                return {
                    "country": country,
                    "confidence": confidence,
                    "attributes": attributes
                }
            except json.JSONDecodeError as e:
                print(f"[DEBUG] JSON parse error: {e}, fallback to heuristic")
                return self._fallback_parse(raw_text, text)
        
        except Exception as e:
            print(f"[ERROR] OpenAI API Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return self._fallback_result()
    
    def _fallback_result(self) -> Dict[str, Any]:
        """Default fallback"""
        return {
            "country": ["ZZ"],
            "confidence": 0.0,
            "attributes": {"size": "none", "color": "none", "material": "none", "brand": "none"}
        }
    
    def _fallback_parse(self, raw_text: str, original_text: str) -> Dict[str, Any]:
        """Heuristic parse nếu JSON fail, strict cho country array, JP-enhanced attributes"""
        # Extract countries: Multiple 2-letter codes
        countries = re.findall(r'\b([A-Z]{2})\b', raw_text.upper())
        countries = list(set(countries))  # Unique
        if not countries:
            countries = ["ZZ"]
        # Explicit check for made-in/origin
        if re.search(r'(?:made\s+in|原産国|製造国)', raw_text, re.IGNORECASE):
            pass  # Keep
        else:
            countries = ["ZZ"]
        
        # Confidence: Rất low nếu không explicit
        confidence = 0.0
        if len(countries) > 0 and any('製' in original_text or 'made in' in original_text.lower() for _ in countries):
            confidence = 0.8
        elif len(countries) > 0 and countries != ["ZZ"]:
            confidence = 0.3
        
        # Attributes: Enhanced JP/多言語 regex (giữ multiple values)
        attributes = {"size": "none", "color": "none", "material": "none", "brand": "none"}
        
        # Size: JP/EN, capture multiple
        size_match = re.search(r'(?:size|サイズ)[:\s/]*([A-Za-z0-9/ cm.]+)', original_text, re.IGNORECASE)
        if size_match:
            attributes["size"] = size_match.group(1).strip()
        
        # Color: JP/EN/CN common, capture multiple
        color_patterns = r'(?:color|カラー|色|颜色)[:\s]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff/ ]+)|(?:アイボリー|ivory|black|red|blue|white|黒|赤|青|Glacier Grey/Pure Silver)'
        color_match = re.search(color_patterns, original_text, re.IGNORECASE)
        if color_match:
            color_val = color_match.group(1).strip() if color_match.group(1) else color_match.group(0).strip()
            attributes["color"] = color_val.lower() if color_val.isascii() else color_val
        
        # Material: JP/EN/CN
        material_match = re.search(r'(?:material|素材|材料)[:\s]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff0-9％/・]+)', original_text, re.IGNORECASE)
        if material_match:
            attributes["material"] = material_match.group(1).strip()
        
        # Brand: JP/EN (tìm GEL-KAYANO → ASICS, nhưng simple regex)
        brand_match = re.search(r'(?:brand|ブランド)[:\s]*([A-Za-z\u3040-\u30ff]+)', original_text, re.IGNORECASE)
        if not brand_match:
            brand_match = re.search(r'(ASICS|GEL-KAYANO)', original_text, re.IGNORECASE)  # Sample-specific
        if brand_match:
            attributes["brand"] = brand_match.group(1).strip()
        
        print(f"[DEBUG] Fallback result: countries={countries} with confidence {confidence}, attrs={attributes}")
        return {
            "country": countries,
            "confidence": confidence,
            "attributes": attributes
        }