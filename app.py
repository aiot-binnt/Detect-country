# File: app.py (Flask main app with new response format - evidence + nested country)
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import time
from dotenv import load_dotenv
from utils.validator import validate_countries
from utils.openai_detector import OpenAIDetector

# Logging setup
import logging
from logging.handlers import RotatingFileHandler

log_level = os.getenv('LOG_LEVEL', 'INFO')
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, log_level))

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# File handler (rotate at 10MB, keep 5 backups)
file_handler = RotatingFileHandler('app.log', maxBytes=10*1024*1024, backupCount=5)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Prometheus metrics
from prometheus_client import Counter, Histogram, generate_latest, REGISTRY

# Metrics definitions
REQUEST_COUNT = Counter('api_requests_total', 'Total API requests', ['endpoint', 'status'])
REQUEST_LATENCY = Histogram('api_request_duration_seconds', 'API request latency')

load_dotenv()

app = Flask(__name__)
CORS(app)

# Initialize components
try:
    openai_detector = OpenAIDetector(api_key=os.getenv('OPENAI_API_KEY'))
    logger.info("✓ OpenAI Detector initialized successfully")
except ValueError as e:
    logger.error(f"Failed to initialize OpenAI Detector: {e}")
    openai_detector = None

# Simple in-memory cache: {text: result} with LRU-like limit
from collections import OrderedDict
MAX_CACHE_SIZE = 1000
cache = OrderedDict()

@app.route('/health', methods=['GET'])
@REQUEST_LATENCY.time()  # Measure latency
def health_check():
    """Health check endpoint"""
    try:
        start_time = time.time()
        result = {
            "status": "healthy",
            "service": "AI Country Detector",
            "version": "1.2.0"  # Updated version for new structure
        }
        processing_time = int((time.time() - start_time) * 1000)
        logger.info(f"Health check completed in {processing_time}ms")
        REQUEST_COUNT.labels(endpoint='health', status='success').inc()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        REQUEST_COUNT.labels(endpoint='health', status='error').inc()
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

@app.route('/detect-country', methods=['POST'])
@REQUEST_LATENCY.time()  # Measure latency
def detect_country():
    """
    Detect countries and attributes from product description
    Request body: {"description": "text"}
    Response format: {result: "OK"|"Failed", data: {...}, errors?: [...]}
    """
    start_time = time.time()
    from_cache = False
    processing_time = 0  # Init
    
    try:
        # Get request data
        data = request.get_json()
        if not data or 'description' not in data:
            logger.warning("Missing 'description' field in request")
            REQUEST_COUNT.labels(endpoint='detect-country', status='error').inc()
            error_response = {
                "result": "Failed",
                "errors": [
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "Missing 'description' field"
                    }
                ]
            }
            return jsonify(error_response), 400
        
        text = data.get("description", "").strip()
        
        if not text:
            logger.warning("Empty description in request")
            REQUEST_COUNT.labels(endpoint='detect-country', status='error').inc()
            error_response = {
                "result": "Failed",
                "errors": [
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "Empty description"
                    }
                ]
            }
            return jsonify(error_response), 400
        
        # Check cache first
        if text in cache:
            cached_result = cache[text].copy()
            from_cache = True
            processing_time = 0  # Cache instant
            logger.info(f"Cache hit for text: {text[:50]}...")
            REQUEST_COUNT.labels(endpoint='detect-country', status='success').inc()
            
            success_response = {
                "result": "OK",
                "data": {
                    # NEW STRUCTURE: Read from cache
                    "confidence": cached_result['confidence'],
                    "attributes": cached_result['attributes'],
                    "cache": True,
                    "time": processing_time
                }
            }
            return jsonify(success_response)
        
        # Step 1: Call AI
        logger.info(f"Calling AI for: {text[:100]}...")
        if not openai_detector:
            raise ValueError("OpenAI Detector not initialized")
            
        # AI result now contains {"confidence": ..., "attributes": {...}}
        ai_result = openai_detector.detect_country(text)
        logger.info(f"AI result: {ai_result}")
        
        # Validate and prepare result
        confidence = ai_result['confidence']
        attributes = ai_result['attributes']
        
        # Extract country value list for validation
        country_value_list = attributes.get('country', {}).get('value', ["ZZ"])
        
        # Validate the list of country codes
        valid_country_list = validate_countries(country_value_list)
        
        # Update the attributes dict with the validated list
        attributes['country']['value'] = valid_country_list
        
        result_data = {
            "confidence": confidence,
            "attributes": attributes,
            "cache": False,
            "time": processing_time  # Will be set below
        }
        
        # Cache if any valid country (not all ZZ) and confidence > 0.5
        if any(c != "ZZ" for c in valid_country_list) and confidence > 0.5:
            # NEW STRUCTURE: Cache entry
            cache_entry = {
                "confidence": confidence,
                "attributes": attributes,
                "source": "AI"  # For internal use
            }
            if len(cache) >= MAX_CACHE_SIZE:
                cache.popitem(last=False)  # LRU evict oldest
            cache[text] = cache_entry
            logger.info(f"Successful detection: {valid_country_list} (conf: {confidence:.2f}) for {text[:50]}...")
        else:
            logger.warning(f"Detection failed (ZZ) for: {text[:50]}...")
        
        processing_time = int((time.time() - start_time) * 1000)  # Calculate after all
        result_data["time"] = processing_time
        
        REQUEST_COUNT.labels(endpoint='detect-country', status='success').inc()
        success_response = {
            "result": "OK",
            "data": result_data
        }
        return jsonify(success_response)
    
    except Exception as e:
        import traceback
        logger.error(f"Unexpected error in detect-country: {str(e)}")
        logger.error(traceback.format_exc())
        REQUEST_COUNT.labels(endpoint='detect-country', status='error').inc()
        error_response = {
            "result": "Failed",
            "errors": [
                {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            ]
        }
        return jsonify(error_response), 500

@app.route('/batch-detect', methods=['POST'])
@REQUEST_LATENCY.time()  # Measure latency
def batch_detect():
    """
    Batch detection for multiple descriptions
    Request body: {"descriptions": ["text1", "text2", ...]}
    Response format: {result: "OK"|"Failed", data: {results: [...], total: N}, errors?: [...]}
    """
    start_time = time.time()
    processing_time = 0  # Init
    
    try:
        data = request.get_json()
        descriptions = data.get("descriptions", [])
        
        if not descriptions or not isinstance(descriptions, list):
            logger.warning("Invalid 'descriptions' field in batch request")
            REQUEST_COUNT.labels(endpoint='batch-detect', status='error').inc()
            error_response = {
                "result": "Failed",
                "errors": [
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "Invalid 'descriptions' field"
                    }
                ]
            }
            return jsonify(error_response), 400
        
        results = []
        cache_hits = 0
        ai_calls = 0
        for desc in descriptions:
            text = desc.strip()
            
            # Check cache first
            if text in cache:
                cached = cache[text].copy()
                # NEW STRUCTURE: Append cached result
                results.append({
                    "confidence": cached['confidence'],
                    "attributes": cached['attributes'],
                    "cache": True
                })
                cache_hits += 1
                continue
            
            # AI detection
            ai_calls += 1
            logger.info(f"Batch AI call {ai_calls} for: {text[:50]}...")
            if not openai_detector:
                raise ValueError("OpenAI Detector not initialized")
                
            ai_result = openai_detector.detect_country(text)
            
            confidence = ai_result['confidence']
            attributes = ai_result['attributes']
            
            # Validate countries
            country_value_list = attributes.get('country', {}).get('value', ["ZZ"])
            valid_country_list = validate_countries(country_value_list)
            attributes['country']['value'] = valid_country_list
            
            result_item = {
                "confidence": confidence,
                "attributes": attributes,
                "cache": False
            }
            results.append(result_item)
            
            # Cache if any valid
            if any(c != "ZZ" for c in valid_country_list) and confidence > 0.5:
                # NEW STRUCTURE: Cache entry
                cache_entry = {
                    "confidence": confidence,
                    "attributes": attributes,
                    "source": "AI"
                }
                if len(cache) >= MAX_CACHE_SIZE:
                    cache.popitem(last=False)
                cache[text] = cache_entry
                logger.info(f"Batch success: {valid_country_list} for {text[:50]}...")
            else:
                logger.warning(f"Batch failed (ZZ) for: {text[:50]}...")
        
        processing_time = int((time.time() - start_time) * 1000)  # Total batch time
        
        response_data = {
            "result": "OK",
            "data": {
                "results": results,
                "total": len(results),
                "cache_hits": cache_hits,
                "ai_calls": ai_calls,
                "time": processing_time
            }
        }
        logger.info(f"Batch completed: {len(results)} items, {cache_hits} cache hits, {ai_calls} AI calls in {processing_time}ms")
        REQUEST_COUNT.labels(endpoint='batch-detect', status='success').inc()
        return jsonify(response_data)
    
    except Exception as e:
        import traceback
        logger.error(f"Unexpected error in batch-detect: {str(e)}")
        logger.error(traceback.format_exc())
        REQUEST_COUNT.labels(endpoint='batch-detect', status='error').inc()
        error_response = {
            "result": "Failed",
            "errors": [
                {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            ]
        }
        return jsonify(error_response), 500

@app.route('/metrics', methods=['GET'])
def metrics():
    """Prometheus metrics endpoint"""
    try:
        logger.debug("Serving Prometheus metrics")
        return Response(generate_latest(REGISTRY), mimetype='text/plain')
    except Exception as e:
        logger.error(f"Error serving metrics: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true')