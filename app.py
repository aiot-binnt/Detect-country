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
from utils.gemini_detector_service import GeminiDetectorService 

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
    """
    Detect country of origin and product attributes from description.
    
    Request body:
    {
        "description": "Product description text",
        "model": "gemini-2.0-flash",  // optional, defaults to gemini-2.0-flash
        "api_key": "your-gemini-api-key"  // optional, uses server's key if not provided
    }
    
    Note: If providing custom model, you must also provide custom api_key, and vice versa.
    """
    start_time = time.time()
    data = request.get_json() or {}
    
    # Extract parameters
    text = data.get("description", "").strip()
    custom_model = data.get("model")
    custom_api_key = data.get("api_key")
    
    # Validate description
    if not text:
        REQUEST_COUNT.labels('detect-country', 'error').inc()
        return api_response(False, errors=[{"code": "VALIDATION_ERROR", "message": "Missing description"}], status=400)
    
    # Validate custom params (model + api_key must be provided together)
    config_result = GeminiDetectorService.prepare_detector_config(
        model_name=custom_model,
        api_key=custom_api_key,
        fallback_api_key=os.getenv('GEMINI_API_KEY')
    )
    
    if not config_result["success"]:
        REQUEST_COUNT.labels('detect-country', 'error').inc()
        logger.warning(f"Validation failed: {config_result.get('error_message')}")
        return api_response(
            False, 
            errors=[{
                "code": config_result.get("error_code"),
                "message": config_result.get("error_message")
            }], 
            status=400
        )
    
    final_model = config_result["model"]
    final_api_key = config_result["api_key"]
    is_custom = config_result["is_custom"]
    
    # 1. Check Cache
    cached_data = result_cache.get(text)
    if cached_data:
        REQUEST_COUNT.labels('detect-country', 'success').inc()
        logger.info(f"Cache hit for: {text[:30]}...")
        return api_response(True, data=process_detection_result(text, cached_data, start_time, True))

    # 2. Create detector with appropriate config
    try:
        # Create new detector instance with custom or default config
        detector = GeminiDetector(api_key=final_api_key, model_name=final_model)
        
        log_msg = f"Processing AI (Gemini) for: {text[:50]}... [Model: {final_model}, Custom: {is_custom}]"
        logger.info(log_msg)
        
        ai_result = asyncio.run(detector.detect_country(text))
        
        # Handle AI errors
        if "error" in ai_result:
            error_code = ai_result.get("error_code", "INTERNAL_ERROR")
            error_message = ai_result.get("error")
            
            # Determine status code based on error type
            status_code = 503 if error_code in ["QUOTA_ERROR", "API_ERROR"] else 500
            
            REQUEST_COUNT.labels('detect-country', 'error').inc()
            logger.error(f"AI Error [{error_code}]: {error_message}")
            
            return api_response(
                False, 
                errors=[{
                    "code": error_code, 
                    "message": error_message
                }], 
                status=status_code
            )
            
        processed_data = process_detection_result(text, ai_result, start_time, False)
        processed_data["model"] = final_model
        processed_data["is_custom"] = is_custom
        
        REQUEST_COUNT.labels('detect-country', 'success').inc()
        logger.info(f"Request completed successfully in {processed_data['time']}ms")
        return api_response(True, data=processed_data)

    except ValueError as e:
        # Handle initialization errors (invalid API key format, etc.)
        REQUEST_COUNT.labels('detect-country', 'error').inc()
        logger.error(f"Detector initialization error: {str(e)}")
        return api_response(
            False, 
            errors=[{
                "code": "INIT_ERROR", 
                "message": f"Failed to initialize detector: {str(e)}"
            }], 
            status=400
        )
    
    except Exception as e:
        logger.error(f"Endpoint error: {traceback.format_exc()}")
        REQUEST_COUNT.labels('detect-country', 'error').inc()
        return api_response(False, errors=[{"code": "INTERNAL_ERROR", "message": str(e)}], status=500)

@app.route('/batch-detect', methods=['POST'])
@require_api_key
@REQUEST_LATENCY.time()
def batch_detect():
    """
    Batch detect countries and attributes from multiple product descriptions.
    
    Request body:
    {
        "descriptions": ["desc1", "desc2", ...],
        "model": "gemini-2.0-flash",  // optional, defaults to gemini-2.0-flash
        "api_key": "your-gemini-api-key"  // optional, uses server's key if not provided
    }
    
    Note: If providing custom model, you must also provide custom api_key, and vice versa.
    """
    start_time = time.time()
    data = request.get_json() or {}
    
    # Extract parameters
    descriptions = data.get("descriptions", [])
    custom_model = data.get("model")
    custom_api_key = data.get("api_key")

    # Validate descriptions
    if not descriptions or not isinstance(descriptions, list):
        REQUEST_COUNT.labels('batch-detect', 'error').inc()
        return api_response(False, errors=[{"code": "VALIDATION_ERROR", "message": "Invalid descriptions list"}], status=400)
    
    # Validate custom params (model + api_key must be provided together)
    config_result = GeminiDetectorService.prepare_detector_config(
        model_name=custom_model,
        api_key=custom_api_key,
        fallback_api_key=os.getenv('GEMINI_API_KEY')
    )
    
    if not config_result["success"]:
        REQUEST_COUNT.labels('batch-detect', 'error').inc()
        logger.warning(f"Validation failed: {config_result.get('error_message')}")
        return api_response(
            False, 
            errors=[{
                "code": config_result.get("error_code"),
                "message": config_result.get("error_message")
            }], 
            status=400
        )
    
    final_model = config_result["model"]
    final_api_key = config_result["api_key"]
    is_custom = config_result["is_custom"]

    async def _run_batch():
        """Inner async function to process batch requests."""
        tasks = []
        indices_needing_ai = []
        results = [None] * len(descriptions)
        
        # Create detector instance for batch processing
        try:
            detector = GeminiDetector(api_key=final_api_key, model_name=final_model)
        except ValueError as e:
            logger.error(f"Detector initialization error in batch: {str(e)}")
            raise
        
        for i, desc in enumerate(descriptions):
            text = desc.strip()
            cached = result_cache.get(text)
            if cached:
                results[i] = {"attributes": cached['attributes'], "cache": True}
            else:
                tasks.append(detector.detect_country(text))
                indices_needing_ai.append(i)

        if tasks:
            logger.info(f"Processing {len(tasks)} items with AI [Model: {final_model}, Custom: {is_custom}]")
            ai_outputs = await asyncio.gather(*tasks)
            
            for idx, output in zip(indices_needing_ai, ai_outputs):
                # Check for errors in AI output
                if "error" in output:
                    results[idx] = {
                        "attributes": detector._get_default_result()['attributes'],
                        "cache": False,
                        "error": {
                            "code": output.get("error_code"),
                            "message": output.get("error")
                        }
                    }
                    logger.warning(f"AI error for item {idx}: {output.get('error')}")
                    continue
                
                # Process successful result
                attributes = output.get('attributes') or detector._get_default_result()['attributes']
                raw_countries = attributes.get('country', {}).get('value', [UNKNOWN_COUNTRY_CODE])
                attributes['country']['value'] = validate_countries(raw_countries)
                
                # Cache Update
                conf = attributes.get('country', {}).get('confidence', 0.0)
                if any(c != UNKNOWN_COUNTRY_CODE for c in attributes['country']['value']) and conf > 0.5:
                     result_cache.set(descriptions[idx].strip(), {"attributes": attributes})

                results[idx] = {
                    "attributes": attributes,
                    "cache": False
                }
        
        return results, len(tasks)

    try:
        results, ai_calls = asyncio.run(_run_batch())
        processing_time = int((time.time() - start_time) * 1000)
        
        response_data = {
            "results": results,
            "total": len(results),
            "cache_hits": len(descriptions) - ai_calls,
            "ai_calls": ai_calls,
            "model": final_model,
            "is_custom": is_custom,
            "time": processing_time
        }
        
        REQUEST_COUNT.labels('batch-detect', 'success').inc()
        logger.info(f"Batch request completed: {len(results)} items in {processing_time}ms")
        return api_response(True, data=response_data)
    
    except ValueError as e:
        # Handle initialization errors
        REQUEST_COUNT.labels('batch-detect', 'error').inc()
        logger.error(f"Detector initialization error in batch: {str(e)}")
        return api_response(
            False, 
            errors=[{
                "code": "INIT_ERROR", 
                "message": f"Failed to initialize detector: {str(e)}"
            }], 
            status=400
        )

    except Exception as e:
        logger.error(f"Batch error: {traceback.format_exc()}")
        REQUEST_COUNT.labels('batch-detect', 'error').inc()
        return api_response(False, errors=[{"code": "INTERNAL_ERROR", "message": str(e)}], status=500)

@app.route('/metrics')
def metrics():
    return Response(generate_latest(REGISTRY), mimetype='text/plain')

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true')