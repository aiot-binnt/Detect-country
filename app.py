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
    # Using GeminiDetector with Vertex AI Service Account
    ai_detector = GeminiDetector()
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

@app.route('/clear-cache', methods=['POST'])
@require_api_key
def clear_cache():
    """
    Clear all cached results.
    
    Returns:
        JSON with number of items cleared
    """
    items_count = len(result_cache.cache)
    result_cache.cache.clear()
    logger.info(f"Cache cleared: {items_count} items removed")
    return jsonify({
        "result": "OK",
        "message": "Cache cleared successfully",
        "items_cleared": items_count
    })

@app.route('/detect-country', methods=['POST'])
@require_api_key
@REQUEST_LATENCY.time()
def detect_country():
    """
    Detect country of origin and product attributes from description.
    
    Request body:
    {
        "description": "Product description text",
        "model": "gemini-2.0-flash"  // optional, defaults to gemini-2.0-flash-exp
    }
    
    Note: Always uses Vertex AI with service account authentication.
    """
    start_time = time.time()
    data = request.get_json() or {}
    
    # Extract parameters
    text = data.get("description", "").strip()
    custom_model = data.get("model")  # Optional model override
    
    # Validate description
    if not text:
        REQUEST_COUNT.labels('detect-country', 'error').inc()
        return api_response(False, errors=[{"code": "VALIDATION_ERROR", "message": "Missing description"}], status=400)
    
    # Reject empty model string (if you don't want to override, don't send the parameter)
    if custom_model is not None and not custom_model.strip():
        REQUEST_COUNT.labels('detect-country', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "VALIDATION_ERROR", 
                "message": "Parameter 'model' cannot be empty. Either provide a valid model name or omit the parameter to use the default model."
            }], 
            status=400
        )
    
    # Reject api_key parameter (no longer supported)
    if "api_key" in data:
        REQUEST_COUNT.labels('detect-country', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "VALIDATION_ERROR", 
                "message": "Parameter 'api_key' is not supported. This API uses Vertex AI with service account authentication. Only 'description' and optional 'model' parameters are accepted."
            }], 
            status=400
        )
    
    # 1. Check Cache
    cached_data = result_cache.get(text)
    if cached_data:
        REQUEST_COUNT.labels('detect-country', 'success').inc()
        logger.info(f"Cache hit for: {text[:30]}...")
        return api_response(True, data=process_detection_result(text, cached_data, start_time, True))

    # 2. Create detector with service account (optional model override)

    # 3. Create detector with service account (optional model override)
    try:
        # Create detector instance with optional model override
        detector = GeminiDetector(model_name=custom_model)
        
        log_msg = f"Processing with Vertex AI: {text[:50]}... [Model: {detector.model_name}]"
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
        processed_data["model"] = detector.model_name
        
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
        "model": "gemini-2.0-flash"  // optional, defaults to gemini-2.0-flash-exp
    }
    
    Note: Always uses Vertex AI with service account authentication.
    """
    start_time = time.time()
    data = request.get_json() or {}
    
    # Extract parameters
    descriptions = data.get("descriptions", [])
    custom_model = data.get("model")  # Optional model override

    # Validate descriptions
    if not descriptions or not isinstance(descriptions, list):
        REQUEST_COUNT.labels('batch-detect', 'error').inc()
        return api_response(False, errors=[{"code": "VALIDATION_ERROR", "message": "Invalid descriptions list"}], status=400)
    
    # Validate descriptions is not empty and contains valid items
    if len(descriptions) == 0:
        REQUEST_COUNT.labels('batch-detect', 'error').inc()
        return api_response(False, errors=[{"code": "VALIDATION_ERROR", "message": "Descriptions list cannot be empty"}], status=400)
    
    # Check if any description is not a string
    for idx, desc in enumerate(descriptions):
        if not isinstance(desc, str):
            REQUEST_COUNT.labels('batch-detect', 'error').inc()
            return api_response(
                False, 
                errors=[{"code": "VALIDATION_ERROR", "message": f"Description at index {idx} must be a string"}], 
                status=400
            )
    
    # Reject empty model string (if you don't want to override, don't send the parameter)
    if custom_model is not None and not custom_model.strip():
        REQUEST_COUNT.labels('batch-detect', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "VALIDATION_ERROR", 
                "message": "Parameter 'model' cannot be empty. Either provide a valid model name or omit the parameter to use the default model."
            }], 
            status=400
        )
    
    # Reject api_key parameter (no longer supported)
    if "api_key" in data:
        REQUEST_COUNT.labels('batch-detect', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "VALIDATION_ERROR", 
                "message": "Parameter 'api_key' is not supported. This API uses Vertex AI with service account authentication. Only 'descriptions' and optional 'model' parameters are accepted."
            }], 
            status=400
        )

    async def _run_batch():
        """Inner async function to process batch requests."""
        tasks = []
        indices_needing_ai = []
        results = [None] * len(descriptions)
        
        # Create detector instance for batch processing
        try:
            detector = GeminiDetector(model_name=custom_model)
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
            logger.info(f"Processing {len(tasks)} items with Vertex AI [Model: {detector.model_name}]")
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
        
        return results, len(tasks), detector.model_name  # Return model_name as well

    try:
        results, ai_calls, model_name = asyncio.run(_run_batch())  # Unpack model_name
        processing_time = int((time.time() - start_time) * 1000)
        
        response_data = {
            "results": results,
            "total": len(results),
            "cache_hits": len(descriptions) - ai_calls,
            "ai_calls": ai_calls,
            "model": model_name,  # Use returned model_name
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