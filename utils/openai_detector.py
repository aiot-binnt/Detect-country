# File: utils/openai_detector.py (Updated: evidence, nested country, new prompt)
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
        Detect country and attributes using ChatGPT.
        Returns: {"confidence": 0.0-1.0, "attributes": {...}}
        """
        if not text or not text.strip():
            return self._fallback_result()
        
        # Clean text first to save tokens
        text = self._clean_text(text)
        
        processed_text = self._detect_and_translate(text)
        try:
            # Truncate very long text to save tokens
            max_length = 800  # Giảm thêm sau clean
            truncated_text = processed_text[:max_length] + "..." if len(processed_text) > max_length else processed_text
            
            system_prompt = """あなたは商品説明の製造国・属性検出の専門家です。製造/原産国に焦点を当て、配送先やブランド名から推測しないでください。

【JSON構造】:
レスポンスは有効なJSONのみ出力してください。
{
  "confidence": 0.0,
  "attributes": {
    "country": {"value": ["XX"], "evidence": "none"},
    "size": {"value": "none", "evidence": "none"},
    "color": {"value": "none", "evidence": "none"},
    "material": {"value": "none", "evidence": "none"},
    "brand": {"value": "none", "evidence": "none"}
  }
}

【抽出ルール】:
1.  **confidence**: 検出の総合信頼度 (0.0 - 1.0)。
2.  **attributes**: 
    * **value**: 抽出した値 (複数可の場合は配列)。見つからない場合は "none" (countryは["ZZ"])。
    * **evidence**: `value`の根拠となった原文のテキスト断片 (e.g., "原産国: Vietnam")。見つからない場合は "none"。

【Country ルール】:
1.  `value`は有効な2文字ISO 3166-1 alpha-2国コードの配列 (e.g., ["JP"], ["ID", "VN"])。
2.  明示的な手がかり ("Made in [国]", "原産国: [国]", "製造国: [国]") のみ探す。配送先やブランド名は無視。
3.  複数国がある場合 (e.g., "原産国: Indonesia / Vietnam")、配列で返却 `{"value": ["ID", "VN"], "evidence": "原産国: Indonesia / Vietnam"}`。
4.  明確な国情報がない場合、`{"value": ["ZZ"], "evidence": "none"}` を返し、`confidence` を 0.0 にする。

【Other Attributes ルール】:
* `size`: e.g., "M", "M/L", "23cm/24cm"
* `color`: e.g., "red", "アイボリー", "Glacier Grey/Pure Silver"
* `material`: e.g., "cotton", "カシミヤ100％"
* `brand`: e.g., "Nike", "RASW（ラス）", "ASICS"
* 複数値はスラッシュ区切りで `value` に保持 (e.g., `{"value": "Glacier Grey/Pure Silver", "evidence": "カラーGlacier Grey/Pure Silver"}`)。
* 見つからない場合は `{"value": "none", "evidence": "none"}`。

【例】:
- "日本製、サイズM、レッドコットンNikeシャツ" →
  {"confidence": 1.0, "attributes": {"country": {"value": ["JP"], "evidence": "日本製"}, "size": {"value": "M", "evidence": "サイズM"}, "color": {"value": "red", "evidence": "レッドコットン"}, "material": {"value": "cotton", "evidence": "レッドコットン"}, "brand": {"value": "Nike", "evidence": "Nikeシャツ"}}}
- "【原産国】Indonesia / Vietnam、カラーGlacier Grey/Pure Silver、サイズ23cm/24cm" →
  {"confidence": 1.0, "attributes": {"country": {"value": ["ID", "VN"], "evidence": "【原産国】Indonesia / Vietnam"}, "size": {"value": "23cm/24cm", "evidence": "サイズ23cm/24cm"}, "color": {"value": "Glacier Grey/Pure Silver", "evidence": "カラーGlacier Grey/Pure Silver"}, "material": {"value": "none", "evidence": "none"}, "brand": {"value": "none", "evidence": "none"}}}
- "日本発送; RASWカシミヤセーター、アイボリー" →
  {"confidence": 0.0, "attributes": {"country": {"value": ["ZZ"], "evidence": "none"}, "size": {"value": "none", "evidence": "none"}, "color": {"value": "ivory", "evidence": "アイボリー"}, "material": {"value": "cashmere", "evidence": "カシミヤセーター"}, "brand": {"value": "RASW", "evidence": "RASWカシミヤセーター"}}}
- "情報なし" →
  {"confidence": 0.0, "attributes": {"country": {"value": ["ZZ"], "evidence": "none"}, "size": {"value": "none", "evidence": "none"}, "color": {"value": "none", "evidence": "none"}, "material": {"value": "none", "evidence": "none"}, "brand": {"value": "none", "evidence": "none"}}}

Confidence: 1.0 = 明示的; 0.0 = 明示なし (ZZ)。JSONのみ出力。"""

            user_prompt = f"""この商品説明を分析し、構造化JSONを返却してください。

商品説明:
{truncated_text}

出力JSON:"""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                max_tokens=250, # Tăng nhẹ token cho evidence
                top_p=0.8
            )
            
            if not response.choices or not response.choices[0].message.content:
                print("OpenAI returned empty response")
                return self._fallback_result()
            
            raw_text = response.choices[0].message.content.strip()
            print(f"[DEBUG] OpenAI raw response: '{raw_text}'")
            
            # Parse JSON
            try:
                parsed = json.loads(raw_text)
                
                # NEW STRUCTURE: Extract confidence and attributes
                confidence = float(parsed.get("confidence", 0.0))
                default_attrs = self._fallback_result()["attributes"]
                attributes = parsed.get("attributes", default_attrs)
                
                # Ensure country value is a list
                country_attr = attributes.get('country', default_attrs['country'])
                if isinstance(country_attr.get('value'), str):
                    country_attr['value'] = [country_attr['value']]
                
                # Basic validation
                if not attributes.get('country') or not attributes['country'].get('value'):
                    attributes['country'] = default_attrs['country']
                    confidence = 0.0
                
                print(f"[DEBUG] Parsed JSON: conf={confidence}, attrs={attributes}")
                return {
                    "confidence": confidence,
                    "attributes": attributes
                }
            except json.JSONDecodeError as e:
                print(f"[DEBUG] JSON parse error: {e}, fallback to heuristic")
                # Dùng text gốc (chưa dịch) để fallback evidence
                return self._fallback_parse(raw_text, text) 
        
        except Exception as e:
            print(f"[ERROR] OpenAI API Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return self._fallback_result()
    
    def _fallback_result(self) -> Dict[str, Any]:
        """Default fallback with new structure"""
        return {
            "confidence": 0.0,
            "attributes": {
                "country": {"value": ["ZZ"], "evidence": "none"},
                "size": {"value": "none", "evidence": "none"},
                "color": {"value": "none", "evidence": "none"},
                "material": {"value": "none", "evidence": "none"},
                "brand": {"value": "none", "evidence": "none"}
            }
        }
    
    def _fallback_parse(self, raw_text: str, original_text: str) -> Dict[str, Any]:
        """Heuristic parse (nếu JSON fail) dùng text gốc để tìm evidence"""
        
        attributes = self._fallback_result()["attributes"]
        confidence = 0.0
        
        try:
            # 1. Country (Rất khó để fallback evidence)
            # Thử tìm "Made in/Origin" + Country Name (đơn giản)
            country_match = re.search(r'((?:made\s+in|原産国|製造国)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff]+))', original_text, re.IGNORECASE)
            countries = ["ZZ"]
            if country_match:
                # Map tên quốc gia (rất cơ bản)
                country_name = country_match.group(2).upper()
                if "JAPAN" in country_name or "日本" in country_name: countries = ["JP"]
                elif "CHINA" in country_name or "中国" in country_name: countries = ["CN"]
                elif "VIETNAM" in country_name or "ベトナム" in country_name: countries = ["VN"]
                elif "INDONESIA" in country_name: countries = ["ID"]
                else:
                    # Thử tìm code 2 chữ cái trong raw_text (kém tin cậy)
                    codes = re.findall(r'\b([A-Z]{2})\b', raw_text.upper())
                    if codes: countries = list(set(codes))
                
                if countries != ["ZZ"]:
                    attributes["country"] = {"value": countries, "evidence": country_match.group(1)}
                    confidence = 0.3 # Low confidence for fallback
            
            # 2. Size
            size_match = re.search(r'((?:size|サイズ)[\s:/]*([A-Za-z0-9/ cmMLXS.]+))', original_text, re.IGNORECASE)
            if size_match:
                attributes["size"] = {"value": size_match.group(2).strip(), "evidence": size_match.group(1).strip()}

            # 3. Color
            color_match = re.search(r'((?:color|カラー|色|颜色)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff/ ]+))', original_text, re.IGNORECASE)
            if not color_match:
                # Thử tìm các màu phổ biến
                color_match = re.search(r'(アイボリー|ivory|black|red|blue|white|黒|赤|青|Glacier Grey/Pure Silver)', original_text, re.IGNORECASE)
                if color_match:
                    attributes["color"] = {"value": color_match.group(1).strip(), "evidence": color_match.group(1).strip()}
            elif color_match:
                attributes["color"] = {"value": color_match.group(2).strip(), "evidence": color_match.group(1).strip()}
            
            # 4. Material
            material_match = re.search(r'((?:material|素材|材料)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff0-9％/・]+))', original_text, re.IGNORECASE)
            if not material_match:
                material_match = re.search(r'(カシミヤ|cashmere|cotton|wool)', original_text, re.IGNORECASE)
                if material_match:
                    attributes["material"] = {"value": material_match.group(1).strip(), "evidence": material_match.group(1).strip()}
            elif material_match:
                attributes["material"] = {"value": material_match.group(2).strip(), "evidence": material_match.group(1).strip()}

            # 5. Brand
            brand_match = re.search(r'((?:brand|ブランド)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff（）]+))', original_text, re.IGNORECASE)
            if not brand_match:
                brand_match = re.search(r'(ASICS|RASW|Nike)', original_text, re.IGNORECASE) # Mẫu
                if brand_match:
                    attributes["brand"] = {"value": brand_match.group(1).strip(), "evidence": brand_match.group(1).strip()}
            elif brand_match:
                attributes["brand"] = {"value": brand_match.group(2).strip(), "evidence": brand_match.group(1).strip()}

            print(f"[DEBUG] Fallback result: conf={confidence}, attrs={attributes}")
            return {"confidence": confidence, "attributes": attributes}
            
        except Exception as e:
            print(f"[ERROR] Fallback parse error: {e}")
            return self._fallback_result()