import os
import time
import asyncio
import logging
import traceback
from collections import OrderedDict
from typing import Dict, Any
from functools import wraps
from logging.handlers import RotatingFileHandler

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv
from prometheus_client import Counter, Histogram, generate_latest, REGISTRY

from utils.validator import validate_countries, UNKNOWN_COUNTRY_CODE
from utils.gemini_detector import GeminiDetector
from utils.gemini_proxy_service import GeminiProxyService, DEFAULT_MODEL 

# --- Configuration & Logging Setup ---
load_dotenv()

def setup_logger():
    """Configure application logging."""
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    logger = logging.getLogger(__name__)
    logger.setLevel(getattr(logging, log_level))
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    
    file_handler = RotatingFileHandler('app.log', maxBytes=10*1024*1024, backupCount=5)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger

logger = setup_logger()

# --- Metrics ---
REQUEST_COUNT = Counter('api_requests_total', 'Total API requests', ['endpoint', 'status'])
REQUEST_LATENCY = Histogram('api_request_duration_seconds', 'API request latency')

# --- Cache Implementation ---
class LRUCache:
    """Simple LRU Cache wrapper."""
    def __init__(self, max_size: int = 1000):
        self.cache = OrderedDict()
        self.max_size = max_size

    def get(self, key: str) -> Any:
        return self.cache.get(key)

    def set(self, key: str, value: Any):
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

# --- App Initialization ---
app = Flask(__name__)
CORS(app)
result_cache = LRUCache(max_size=1000)

# Initialize Gemini Detector
try:
    # Using GeminiDetector with new Env Var
    ai_detector = GeminiDetector(api_key=os.getenv('GEMINI_API_KEY'))
except ValueError as e:
    logger.error(f"Failed to initialize Gemini Detector: {e}")
    ai_detector = None

VALID_API_KEYS = {k.strip() for k in os.getenv('API_KEYS', '').split(',') if k.strip()}

# --- Helpers ---
def api_response(success: bool, data: Any = None, errors: list = None, status: int = 200):
    """Standardize API response format."""
    payload = {"result": "OK" if success else "Failed"}
    if data: payload["data"] = data
    if errors: payload["errors"] = errors
    return jsonify(payload), status

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if VALID_API_KEYS:
            key = request.headers.get('X-API-KEY')
            if not key or key not in VALID_API_KEYS:
                logger.warning(f"Auth failed from IP: {request.remote_addr}")
                REQUEST_COUNT.labels('auth', 'error').inc()
                return api_response(False, errors=[{"code": "AUTH_ERROR", "message": "Invalid API Key"}], status=401)
        return f(*args, **kwargs)
    return decorated_function

def process_detection_result(text: str, ai_result: Dict, start_time: float, is_cache: bool) -> Dict[str, Any]:
    """Process raw AI result into final response format and handle caching."""
    # Use the default result from the detector instance if result is missing
    default_attrs = ai_detector._get_default_result()['attributes'] if ai_detector else {}
    attributes = ai_result.get('attributes') or default_attrs
    
    # Validation
    raw_countries = attributes.get('country', {}).get('value', [UNKNOWN_COUNTRY_CODE])
    valid_countries = validate_countries(raw_countries)
    attributes['country']['value'] = valid_countries
    
    # Caching logic
    conf = attributes.get('country', {}).get('confidence', 0.0)
    if not is_cache and any(c != UNKNOWN_COUNTRY_CODE for c in valid_countries) and conf > 0.5:
        result_cache.set(text, {"attributes": attributes})
        logger.info(f"Cached result for: {text[:30]}...")

    return {
        "attributes": attributes,
        "cache": is_cache,
        "time": int((time.time() - start_time) * 1000)
    }

# --- Routes ---
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "Gemini Country Detector", "version": "2.0.0"})

@app.route('/detect-country', methods=['POST'])
@require_api_key
@REQUEST_LATENCY.time()
def detect_country():
    start_time = time.time()
    data = request.get_json() or {}
    text = data.get("description", "").strip()

    if not text:
        return api_response(False, errors=[{"code": "VALIDATION_ERROR", "message": "Missing description"}], status=400)

    # 1. Check Cache
    cached_data = result_cache.get(text)
    if cached_data:
        REQUEST_COUNT.labels('detect-country', 'success').inc()
        # Pass empty dict for detector if cached, just needs validation logic
        return api_response(True, data=process_detection_result(text, cached_data, start_time, True))

    # 2. Call AI
    if not ai_detector:
        return api_response(False, errors=[{"code": "INIT_ERROR", "message": "Detector not initialized"}], status=500)

    try:
        logger.info(f"Processing AI (Gemini) for: {text[:50]}...")
        ai_result = asyncio.run(ai_detector.detect_country(text))
        
        if "error" in ai_result:
            status_code = 503 if ai_result.get("error_code") in ["QUOTA_ERROR", "API_ERROR"] else 500
            return api_response(False, errors=[{"code": ai_result.get("error_code"), "message": ai_result.get("error")}], status=status_code)
            
        processed_data = process_detection_result(text, ai_result, start_time, False)
        REQUEST_COUNT.labels('detect-country', 'success').inc()
        return api_response(True, data=processed_data)

    except Exception as e:
        logger.error(f"Endpoint error: {traceback.format_exc()}")
        REQUEST_COUNT.labels('detect-country', 'error').inc()
        return api_response(False, errors=[{"code": "INTERNAL_ERROR", "message": str(e)}], status=500)

@app.route('/batch-detect', methods=['POST'])
@require_api_key
@REQUEST_LATENCY.time()
def batch_detect():
    start_time = time.time()
    data = request.get_json() or {}
    descriptions = data.get("descriptions", [])

    if not descriptions or not isinstance(descriptions, list):
        return api_response(False, errors=[{"code": "VALIDATION_ERROR", "message": "Invalid descriptions list"}], status=400)

    async def _run_batch():
        tasks = []
        indices_needing_ai = []
        results = [None] * len(descriptions)
        
        for i, desc in enumerate(descriptions):
            text = desc.strip()
            cached = result_cache.get(text)
            if cached:
                results[i] = {"attributes": cached['attributes'], "cache": True}
            else:
                if ai_detector:
                    tasks.append(ai_detector.detect_country(text))
                    indices_needing_ai.append(i)
                else:
                    default_res = ai_detector._get_default_result()['attributes'] if ai_detector else {}
                    results[i] = {"attributes": default_res, "cache": False}

        if tasks:
            ai_outputs = await asyncio.gather(*tasks)
            for idx, output in zip(indices_needing_ai, ai_outputs):
                # Logic extracted to keep simple, similar to single detect
                attributes = output.get('attributes') or ai_detector._get_default_result()['attributes']
                raw_countries = attributes.get('country', {}).get('value', [UNKNOWN_COUNTRY_CODE])
                attributes['country']['value'] = validate_countries(raw_countries)
                
                # Cache Update
                conf = attributes.get('country', {}).get('confidence', 0.0)
                if any(c != UNKNOWN_COUNTRY_CODE for c in attributes['country']['value']) and conf > 0.5:
                     result_cache.set(descriptions[idx].strip(), {"attributes": attributes})

                results[idx] = {
                    "attributes": attributes,
                    "cache": False,
                    "error": output.get("error")
                }
        
        return results, len(tasks)

    try:
        results, ai_calls = asyncio.run(_run_batch())
        processing_time = int((time.time() - start_time) * 1000)
        
        data = {
            "results": results,
            "total": len(results),
            "cache_hits": len(descriptions) - ai_calls,
            "ai_calls": ai_calls,
            "time": processing_time
        }
        REQUEST_COUNT.labels('batch-detect', 'success').inc()
        return api_response(True, data=data)

    except Exception as e:
        logger.error(f"Batch error: {traceback.format_exc()}")
        return api_response(False, errors=[{"code": "INTERNAL_ERROR", "message": str(e)}], status=500)

@app.route('/gemini-proxy', methods=['POST'])
@require_api_key
@REQUEST_LATENCY.time()
def gemini_proxy():
    """
    Proxy endpoint for Gemini API calls.
    Allows servers in restricted regions (e.g., China) to call Gemini API through this server.
    
    Request body:
    {
        "prompt": "Your prompt text here",
        "model": "gemini-2.0-flash",  // optional, defaults to gemini-2.0-flash
        "api_key": "your-gemini-api-key"  // optional, uses server's key if not provided
    }
    """
    start_time = time.time()
    data = request.get_json() or {}
    
    # Extract parameters
    prompt = data.get("prompt", "")
    model_name = data.get("model")
    custom_api_key = data.get("api_key")
    
    # Process request using service layer
    result = GeminiProxyService.process_proxy_request(
        prompt=prompt,
        model_name=model_name,
        api_key=custom_api_key,
        fallback_api_key=os.getenv('GEMINI_API_KEY')
    )
    
    processing_time = int((time.time() - start_time) * 1000)
    
    # Handle result
    if result["success"]:
        result_data = {
            "response": result["response"],
            "model": model_name or DEFAULT_MODEL,
            "time": processing_time
        }
        REQUEST_COUNT.labels('gemini-proxy', 'success').inc()
        return api_response(True, data=result_data)
    else:
        # Handle error
        error_code = result.get("error_code", "INTERNAL_ERROR")
        error_message = result.get("error_message", "Unknown error")
        
        REQUEST_COUNT.labels('gemini-proxy', 'error').inc()
        
        # Determine HTTP status code
        status_code = 400 if error_code == "VALIDATION_ERROR" else 500
        
        return api_response(
            False,
            errors=[{"code": error_code, "message": error_message}],
            status=status_code
        )

@app.route('/metrics')
def metrics():
    return Response(generate_latest(REGISTRY), mimetype='text/plain')

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true')