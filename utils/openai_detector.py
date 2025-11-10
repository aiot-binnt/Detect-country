
import openai
import re
import json
from typing import Dict, List, Any
# import asyncio 
from openai import AsyncOpenAI 

class OpenAIDetector:
    def __init__(self, api_key: str):
        """Initialize OpenAI API với client mới (v1+)"""
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required")
        
        self.client = AsyncOpenAI(api_key=api_key)  
        self.model = "gpt-4o-mini"  
        print(f"✓ Using OpenAI model: {self.model}")
    
    def _clean_text(self, text: str) -> str:
        """Clean text: Remove HTML/tags/tables, keep text + punctuation, normalize spaces to save tokens."""
        if not text:
            return text
        text = re.sub(r'<[^>]*>', '', text)
        text = re.sub(r'<tr[^>]*>.*?</tr>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<th[^>]*>.*?</th>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<td[^>]*>.*?</td>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<table[^>]*>.*?</table>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'[^a-zA-Z0-9\u3040-\u30ff\u4e00-\u9fff.,;:/\-\(\)\[\]（）％™\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        print(f"[DEBUG] Cleaned text length: {len(text)} chars")
        return text
    

    async def detect_country(self, text: str) -> Dict[str, Any]:
        """
        Detect country and attributes using ChatGPT.
        Returns: {"attributes": {...}}
        """
        if not text or not text.strip():
            return self._fallback_result()
        
        cleaned_text = self._clean_text(text)
        
        if not cleaned_text:
             return self._fallback_result()
        
        try:
            max_length = 800
            truncated_text = cleaned_text[:max_length] + "..." if len(cleaned_text) > max_length else cleaned_text
            
            system_prompt = """あなたは商品説明の製造国・属性検出の専門家です。製造/原産国に焦点を当て、配送先やブランド名から推測しないでください。

【JSON構造】:
レスポンスは有効なJSONのみ出力してください。
{
  "attributes": {
    "country": {"value": ["XX"], "evidence": "none", "confidence": 0.0},
    "size": {"value": "none", "evidence": "none", "confidence": 0.0},
    "color": {"value": "none", "evidence": "none", "confidence": 0.0},
    "material": {"value": "none", "evidence": "none", "confidence": 0.0},
    "brand": {"value": "none", "evidence": "none", "confidence": 0.0}
  }
}

【抽出ルール】:
1.  **attributes**: 
    * **value**: 抽出した値 (複数可の場合は配列)。見つからない場合は "none" (countryは["ZZ"])。
    * **evidence**: `value`の根拠となった原文のテキスト断片。見つからない場合は "none"。
    * **confidence**: この属性の検出信頼度 (0.0 - 1.0)。

【Country ルール】:
1.  `value`は有効な2文字ISO 3166-1 alpha-2国コードの配列 (e.g., ["JP"], ["ID", "VN"])。
2.  明示的な手がかり ("Made in [国]", "原産国: [国]", "製造国: [国]") のみ探す。配送先やブランド名は無視。
3.  複数国がある場合 (e.g., "原産国: Indonesia / Vietnam")、配列で返却 `{"value": ["ID", "VN"], "evidence": "原産国: Indonesia / Vietnam", "confidence": 1.0}`。
4.  明確な国情報がない場合、`{"value": ["ZZ"], "evidence": "none", "confidence": 0.0}` を返す。

【国コードの正規化 (重要)】:
1.  **最重要ルール**: もし、スコットランド、イングランド、ウェールズ、プエルトリコ、台湾（中華民国）など、独立した主要ISOコードを持たない、または政治的に敏感な地域、領土、構成国を見つけた場合は、**その主権国家（親国）または地域を代表するISO 3166-1コードを返却してください。**
    * 例: "Made in Scotland" -> `{"value": ["GB"], "evidence": "Made in Scotland", "confidence": 0.9}`
    * 例: "Made in Wales" -> `{"value": ["GB"], "evidence": "Made in Wales", "confidence": 0.9}`
    * 例: "Made in Puerto Rico" -> `{"value": ["US"], "evidence": "Made in Puerto Rico", "confidence": 0.9}`
    * 例: "Made in Taiwan" -> `{"value": ["TW"], "evidence": "Made in Taiwan", "confidence": 1.0}` (TWは有効なコード)
    * 例: "Made in Hong Kong" -> `{"value": ["HK"], "evidence": "Made in Hong Kong", "confidence": 1.0}` (HKは有効なコード)
2.  一般的な名称も正規化します。
    * 例: "America" (アメリカ) または "USA" -> `["US"]`
    * 例: "Japan" (日本) -> `["JP"]`
    * 例: "China" (中国) -> `["CN"]`

【Other Attributes ルール】:
1.  `size`, `material`, `brand`: (変更なし)
2.  **`color` (色) ルール (重要):**
    * `value`には、原文で見つかった**正確な**色の記述（例: "Glacier Grey/Pure Silver", "ブルー系（青・紺・ネイビー）"）をそのまま抽出してください。
    * **翻訳や単純化（例: 「ネイビー」を「blue」に変える）は絶対に行わないでください。** 見つかった文字列全体を `value` として返します。
3.  見つからない場合は `{"value": "none", "evidence": "none", "confidence": 0.0}`。

【例】:
- "日本製、サイズM、レッドコットンNikeシャツ" →
  {"attributes": {"country": {"value": ["JP"], "evidence": "日本製", "confidence": 1.0}, "size": {"value": "M", "evidence": "サイズM", "confidence": 1.0}, "color": {"value": "red", "evidence": "レッドコットン", "confidence": 0.8}, "material": {"value": "cotton", "evidence": "レッドコットン", "confidence": 0.8}, "brand": {"value": "Nike", "evidence": "Nikeシャツ", "confidence": 0.9}}}
- "【原産国】Indonesia / Vietnam、カラーGlacier Grey/Pure Silver" →
  {"attributes": {"country": {"value": ["ID", "VN"], "evidence": "【原産国】Indonesia / Vietnam", "confidence": 1.0}, "size": {"value": "none", "evidence": "none", "confidence": 0.0}, "color": {"value": "Glacier Grey/Pure Silver", "evidence": "カラーGlacier Grey/Pure Silver", "confidence": 1.0}, "material": {"value": "none", "evidence": "none", "confidence": 0.0}, "brand": {"value": "none", "evidence": "none", "confidence": 0.0}}}
- "日本発送; Made in Wales. RASWカシミヤセーター、アイボリー" →
  {"attributes": {"country": {"value": ["GB"], "evidence": "Made in Wales", "confidence": 0.9}, "size": {"value": "none", "evidence": "none", "confidence": 0.0}, "color": {"value": "ivory", "evidence": "アイボリー", "confidence": 0.9}, "material": {"value": "cashmere", "evidence": "カシミヤセーター", "confidence": 1.0}, "brand": {"value": "RASW", "evidence": "RASWカシミヤセーター", "confidence": 1.0}}}

JSONのみ出力。"""

            user_prompt = f"""この商品説明を分析し、構造化JSONを返却してください。

商品説明:
{truncated_text}

出力JSON:"""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                max_tokens=400, 
                top_p=0.8
            )
            
            if not response.choices or not response.choices[0].message.content:
                print("OpenAI returned empty response")
                return self._fallback_result()
            
            raw_text = response.choices[0].message.content.strip()
            print(f"[DEBUG] OpenAI raw response: '{raw_text}'")
            
            try:
                parsed = json.loads(raw_text)
                default_attrs = self._fallback_result()["attributes"]
                attributes = parsed.get("attributes", default_attrs)
                country_attr = attributes.get('country', default_attrs['country'])
                if isinstance(country_attr.get('value'), str):
                    country_attr['value'] = [country_attr['value']]
                if not attributes.get('country') or not attributes['country'].get('value'):
                    attributes['country'] = default_attrs['country']
                
                print(f"[DEBUG] Parsed JSON: attrs={attributes}")
                return {
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
        """Default fallback with new structure"""
        return {
            "attributes": {
                "country": {"value": ["ZZ"], "evidence": "none", "confidence": 0.0},
                "size": {"value": "none", "evidence": "none", "confidence": 0.0},
                "color": {"value": "none", "evidence": "none", "confidence": 0.0},
                "material": {"value": "none", "evidence": "none", "confidence": 0.0},
                "brand": {"value": "none", "evidence": "none", "confidence": 0.0}
            }
        }
    
    def _fallback_parse(self, raw_text: str, original_text: str) -> Dict[str, Any]:
        """Heuristic parse (nếu JSON fail) dùng text gốc để tìm evidence"""
        
        attributes = self._fallback_result()["attributes"]
        
        try:
            country_match = re.search(r'((?:made\s+in|原産国|製造国)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff]+))', original_text, re.IGNORECASE)
            countries = ["ZZ"]
            country_conf = 0.0
            
            if country_match:
                country_name = country_match.group(2).upper()
                if "JAPAN" in country_name or "日本" in country_name: countries, country_conf = ["JP"], 0.3
                elif "CHINA" in country_name or "中国" in country_name: countries, country_conf = ["CN"], 0.3
                elif "VIETNAM" in country_name or "ベトナム" in country_name: countries, country_conf = ["VN"], 0.3
                elif "INDONESIA" in country_name: countries, country_conf = ["ID"], 0.3
                elif "SCOTLAND" in country_name or "ENGLAND" in country_name or "WALES" in country_name: countries, country_conf = ["GB"], 0.3
                elif "PUERTO RICO" in country_name: countries, country_conf = ["US"], 0.3
                
                if countries != ["ZZ"]:
                    attributes["country"] = {"value": countries, "evidence": country_match.group(1), "confidence": country_conf}
            
            size_match = re.search(r'((?:size|サイズ)[\s:/]*([A-Za-z0-9/ cmMLXS.]+))', original_text, re.IGNORECASE)
            if size_match:
                attributes["size"] = {"value": size_match.group(2).strip(), "evidence": size_match.group(1).strip(), "confidence": 0.3}

            color_match = re.search(r'((?:color|カラー|色|颜色)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff/ ]+))', original_text, re.IGNORECASE)
            if not color_match:
                color_match = re.search(r'(アイボリー|ivory|black|red|blue|white|黒|赤|青|Glacier Grey/Pure Silver)', original_text, re.IGNORECASE)
                if color_match:
                    attributes["color"] = {"value": color_match.group(1).strip(), "evidence": color_match.group(1).strip(), "confidence": 0.3}
            elif color_match:
                attributes["color"] = {"value": color_match.group(2).strip(), "evidence": color_match.group(1).strip(), "confidence": 0.3}
            
            material_match = re.search(r'((?:material|素材|材料)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff0-9％/・]+))', original_text, re.IGNORECASE)
            if not material_match:
                material_match = re.search(r'(カシミヤ|cashmere|cotton|wool)', original_text, re.IGNORECASE)
                if material_match:
                    attributes["material"] = {"value": material_match.group(1).strip(), "evidence": material_match.group(1).strip(), "confidence": 0.3}
            elif material_match:
                attributes["material"] = {"value": material_match.group(2).strip(), "evidence": material_match.group(1).strip(), "confidence": 0.3}

            brand_match = re.search(r'((?:brand|ブランド)[\s:]*([A-Za-z\u3040-\u30ff\u4e00-\u9fff（）]+))', original_text, re.IGNORECASE)
            if not brand_match:
                brand_match = re.search(r'(ASICS|RASW|Nike)', original_text, re.IGNORECASE)
                if brand_match:
                    attributes["brand"] = {"value": brand_match.group(1).strip(), "evidence": brand_match.group(1).strip(), "confidence": 0.3}
            elif brand_match:
                attributes["brand"] = {"value": brand_match.group(2).strip(), "evidence": brand_match.group(1).strip(), "confidence": 0.3}


            print(f"[DEBUG] Fallback result: attrs={attributes}")
            return {"attributes": attributes}
            
        except Exception as e:
            print(f"[ERROR] Fallback parse error: {e}")
            return self._fallback_result()