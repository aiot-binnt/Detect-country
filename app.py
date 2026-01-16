import os
import time
import asyncio
import logging
import traceback
from collections import OrderedDict
from typing import Dict, Any, List
from functools import wraps
from logging.handlers import RotatingFileHandler

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv
from prometheus_client import Counter, Histogram, generate_latest, REGISTRY

from utils.validator import validate_countries, UNKNOWN_COUNTRY_CODE
from utils.gemini_detector import GeminiDetector

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

def process_detection_result(cache_key: str, ai_result: Dict, start_time: float, is_cache: bool, detector: GeminiDetector = None) -> Dict[str, Any]:
    """Process raw AI result into final response format and handle caching."""
    # Use the default result from the detector instance if result is missing
    default_attrs = (detector._get_default_result()['attributes'] if detector 
                     else ai_detector._get_default_result()['attributes'] if ai_detector 
                     else {})
    attributes = ai_result.get('attributes') or default_attrs
    
    # Validation - validate country codes
    raw_countries = attributes.get('country', {}).get('value', [])
    valid_countries = validate_countries(raw_countries)
    attributes['country']['value'] = valid_countries
    
    # Caching logic - only cache if we have meaningful results
    conf = attributes.get('country', {}).get('confidence', 0.0)
    hscode_conf = attributes.get('hscode', {}).get('confidence', 0.0)
    
    if not is_cache and (any(c != UNKNOWN_COUNTRY_CODE for c in valid_countries) and conf > 0.5) or hscode_conf > 0.5:
        result_cache.set(cache_key, {"attributes": attributes})
        logger.info(f"Cached result for: {cache_key[:50]}...")

    return {
        "attributes": attributes,
        "cache": is_cache,
        "time": int((time.time() - start_time) * 1000)
    }

def _generate_cache_key(title: str, description: str) -> str:
    """Generate a cache key from title and description."""
    return f"{title.strip()}||{description.strip()}"

# --- Routes ---
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy", 
        "service": "Product Detector with HS Code", 
        "version": "3.0.0"
    })

@app.route('/clear-cache', methods=['POST'])
@require_api_key
def clear_cache():
    """Clear all cached results."""
    items_count = len(result_cache.cache)
    result_cache.cache.clear()
    logger.info(f"Cache cleared: {items_count} items removed")
    return jsonify({
        "result": "OK",
        "message": "Cache cleared successfully",
        "items_cleared": items_count
    })

# --- NEW ENDPOINTS ---

@app.route('/detect-product', methods=['POST'])
@require_api_key
@REQUEST_LATENCY.time()
def detect_product():
    """
    Detect product attributes and HS Code from title and description.
    
    Request body:
    {
        "title": "Product title",
        "description": "Product description text",
        "model": "gemini-2.0-flash"  // optional
    }
    
    Response:
    {
        "result": "OK",
        "data": {
            "attributes": {
                "country": {"value": ["JPN"], "evidence": "...", "confidence": 0.9},
                "material": {"value": "cotton", "evidence": "...", "confidence": 0.8},
                "size": {"value": "M", "evidence": "...", "confidence": 0.8},
                "target_user": {"value": ["women"], "evidence": "...", "confidence": 0.7},
                "hscode": {"value": "620442", "evidence": "...", "confidence": 0.75}
            },
            "cache": false,
            "time": 1234,
            "model": "gemini-2.0-flash-exp"
        }
    }
    """
    start_time = time.time()
    data = request.get_json() or {}
    
    # Extract parameters
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    custom_model = data.get("model")
    
    # Validate input - at least one of title or description is required
    if not title and not description:
        REQUEST_COUNT.labels('detect-product', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "VALIDATION_ERROR", 
                "message": "At least one of 'title' or 'description' is required"
            }], 
            status=400
        )
    
    # Reject empty model string
    if custom_model is not None and not custom_model.strip():
        REQUEST_COUNT.labels('detect-product', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "VALIDATION_ERROR", 
                "message": "Parameter 'model' cannot be empty. Provide a valid model name or omit the parameter."
            }], 
            status=400
        )
    
    # Generate cache key
    cache_key = _generate_cache_key(title, description)
    
    # Check Cache
    cached_data = result_cache.get(cache_key)
    if cached_data:
        REQUEST_COUNT.labels('detect-product', 'success').inc()
        logger.info(f"Cache hit for: {cache_key[:50]}...")
        return api_response(True, data=process_detection_result(cache_key, cached_data, start_time, True))

    # Process with AI
    try:
        detector = GeminiDetector(model_name=custom_model)
        
        log_msg = f"Processing: title='{title[:30]}...', desc='{description[:30]}...' [Model: {detector.model_name}]"
        logger.info(log_msg)
        
        ai_result = asyncio.run(detector.detect_product(title=title, description=description))
        
        # Handle AI errors
        if "error" in ai_result:
            error_code = ai_result.get("error_code", "INTERNAL_ERROR")
            error_message = ai_result.get("error")
            
            # Determine status code based on error type
            status_map = {
                "QUOTA_ERROR": 503,
                "API_ERROR": 503,
                "AUTH_ERROR": 401,
                "CONFIG_ERROR": 500,
                "VALIDATION_ERROR": 400,
                "PARSE_ERROR": 500,
                "MODEL_ERROR": 400
            }
            status_code = status_map.get(error_code, 500)
            
            REQUEST_COUNT.labels('detect-product', 'error').inc()
            logger.error(f"AI Error [{error_code}]: {error_message}")
            
            # Return partial result with error info
            return api_response(
                False, 
                data={
                    "attributes": ai_result.get("attributes", {}),
                    "time": int((time.time() - start_time) * 1000)
                },
                errors=[{
                    "code": error_code, 
                    "message": error_message
                }], 
                status=status_code
            )
            
        processed_data = process_detection_result(cache_key, ai_result, start_time, False, detector)
        processed_data["model"] = detector.model_name
        
        REQUEST_COUNT.labels('detect-product', 'success').inc()
        logger.info(f"Request completed successfully in {processed_data['time']}ms")
        return api_response(True, data=processed_data)

    except ValueError as e:
        REQUEST_COUNT.labels('detect-product', 'error').inc()
        logger.error(f"Detector initialization error: {str(e)}")
        return api_response(
            False, 
            errors=[{
                "code": "INIT_ERROR", 
                "message": f"Failed to initialize detector: {str(e)}"
            }], 
            status=500
        )
    
    except Exception as e:
        logger.error(f"Endpoint error: {traceback.format_exc()}")
        REQUEST_COUNT.labels('detect-product', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "INTERNAL_ERROR", 
                "message": f"An unexpected error occurred: {str(e)}"
            }], 
            status=500
        )


@app.route('/batch-detect-product', methods=['POST'])
@require_api_key
@REQUEST_LATENCY.time()
def batch_detect_product():
    """
    Batch detect product attributes and HS Code from multiple items.
    
    Request body:
    {
        "items": [
            {"title": "Product 1", "description": "Description 1"},
            {"title": "Product 2", "description": "Description 2"}
        ],
        "model": "gemini-2.0-flash"  // optional
    }
    
    Response:
    {
        "result": "OK",
        "data": {
            "results": [...],
            "total": 2,
            "cache_hits": 0,
            "ai_calls": 2,
            "model": "gemini-2.0-flash-exp",
            "time": 2500
        }
    }
    """
    start_time = time.time()
    data = request.get_json() or {}
    
    # Extract parameters
    items = data.get("items", [])
    custom_model = data.get("model")

    # Validate items
    if not items or not isinstance(items, list):
        REQUEST_COUNT.labels('batch-detect-product', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "VALIDATION_ERROR", 
                "message": "Parameter 'items' must be a non-empty list"
            }], 
            status=400
        )
    
    if len(items) == 0:
        REQUEST_COUNT.labels('batch-detect-product', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "VALIDATION_ERROR", 
                "message": "Items list cannot be empty"
            }], 
            status=400
        )
    
    # Validate each item structure
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            REQUEST_COUNT.labels('batch-detect-product', 'error').inc()
            return api_response(
                False, 
                errors=[{
                    "code": "VALIDATION_ERROR", 
                    "message": f"Item at index {idx} must be an object with 'title' and/or 'description'"
                }], 
                status=400
            )
        
        title = item.get("title", "").strip() if isinstance(item.get("title"), str) else ""
        desc = item.get("description", "").strip() if isinstance(item.get("description"), str) else ""
        
        if not title and not desc:
            REQUEST_COUNT.labels('batch-detect-product', 'error').inc()
            return api_response(
                False, 
                errors=[{
                    "code": "VALIDATION_ERROR", 
                    "message": f"Item at index {idx} must have at least 'title' or 'description'"
                }], 
                status=400
            )
    
    # Reject empty model string
    if custom_model is not None and not custom_model.strip():
        REQUEST_COUNT.labels('batch-detect-product', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "VALIDATION_ERROR", 
                "message": "Parameter 'model' cannot be empty. Provide a valid model name or omit the parameter."
            }], 
            status=400
        )

    async def _run_batch():
        """Inner async function to process batch requests."""
        tasks = []
        indices_needing_ai = []
        results = [None] * len(items)
        
        # Create detector instance for batch processing
        try:
            detector = GeminiDetector(model_name=custom_model)
        except ValueError as e:
            logger.error(f"Detector initialization error in batch: {str(e)}")
            raise
        
        for i, item in enumerate(items):
            title = item.get("title", "").strip() if isinstance(item.get("title"), str) else ""
            desc = item.get("description", "").strip() if isinstance(item.get("description"), str) else ""
            cache_key = _generate_cache_key(title, desc)
            
            cached = result_cache.get(cache_key)
            if cached:
                results[i] = {"attributes": cached['attributes'], "cache": True}
            else:
                tasks.append(detector.detect_product(title=title, description=desc))
                indices_needing_ai.append((i, cache_key))

        if tasks:
            logger.info(f"Processing {len(tasks)} items with Vertex AI [Model: {detector.model_name}]")
            ai_outputs = await asyncio.gather(*tasks)
            
            for (idx, cache_key), output in zip(indices_needing_ai, ai_outputs):
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
                raw_countries = attributes.get('country', {}).get('value', [])
                attributes['country']['value'] = validate_countries(raw_countries)
                
                # Cache Update
                conf = attributes.get('country', {}).get('confidence', 0.0)
                hscode_conf = attributes.get('hscode', {}).get('confidence', 0.0)
                
                if (any(c != UNKNOWN_COUNTRY_CODE for c in attributes['country']['value']) and conf > 0.5) or hscode_conf > 0.5:
                    result_cache.set(cache_key, {"attributes": attributes})

                results[idx] = {
                    "attributes": attributes,
                    "cache": False
                }
        
        return results, len(tasks), detector.model_name

    try:
        results, ai_calls, model_name = asyncio.run(_run_batch())
        processing_time = int((time.time() - start_time) * 1000)
        
        response_data = {
            "results": results,
            "total": len(results),
            "cache_hits": len(items) - ai_calls,
            "ai_calls": ai_calls,
            "model": model_name,
            "time": processing_time
        }
        
        REQUEST_COUNT.labels('batch-detect-product', 'success').inc()
        logger.info(f"Batch request completed: {len(results)} items in {processing_time}ms")
        return api_response(True, data=response_data)
    
    except ValueError as e:
        REQUEST_COUNT.labels('batch-detect-product', 'error').inc()
        logger.error(f"Detector initialization error in batch: {str(e)}")
        return api_response(
            False, 
            errors=[{
                "code": "INIT_ERROR", 
                "message": f"Failed to initialize detector: {str(e)}"
            }], 
            status=500
        )

    except Exception as e:
        logger.error(f"Batch error: {traceback.format_exc()}")
        REQUEST_COUNT.labels('batch-detect-product', 'error').inc()
        return api_response(
            False, 
            errors=[{
                "code": "INTERNAL_ERROR", 
                "message": f"An unexpected error occurred: {str(e)}"
            }], 
            status=500
        )


@app.route('/metrics')
def metrics():
    return Response(generate_latest(REGISTRY), mimetype='text/plain')

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true')