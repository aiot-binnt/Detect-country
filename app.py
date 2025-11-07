
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import time
from dotenv import load_dotenv
from utils.validator import validate_countries
from utils.openai_detector import OpenAIDetector
import asyncio 


import logging
from logging.handlers import RotatingFileHandler
log_level = os.getenv('LOG_LEVEL', 'INFO')
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, log_level))
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
file_handler = RotatingFileHandler('app.log', maxBytes=10*1024*1024, backupCount=5)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)
logger.addHandler(file_handler)


from prometheus_client import Counter, Histogram, generate_latest, REGISTRY
REQUEST_COUNT = Counter('api_requests_total', 'Total API requests', ['endpoint', 'status'])
REQUEST_LATENCY = Histogram('api_request_duration_seconds', 'API request latency')

load_dotenv()

app = Flask(__name__)
CORS(app)


try:
    openai_detector = OpenAIDetector(api_key=os.getenv('OPENAI_API_KEY'))
    logger.info("✓ OpenAI Detector initialized successfully (Async)")
except ValueError as e:
    logger.error(f"Failed to initialize OpenAI Detector: {e}")
    openai_detector = None


from collections import OrderedDict
MAX_CACHE_SIZE = 1000
cache = OrderedDict()

@app.route('/health', methods=['GET'])
@REQUEST_LATENCY.time()
def health_check():
    try:
        start_time = time.time()
        result = {
            "status": "healthy",
            "service": "AI Country Detector",
            "version": "1.4.1"  
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
@REQUEST_LATENCY.time()
def detect_country():
    """
    Detect countries and attributes from product description
    Request body: {"description": "text"}
    Response format: {result: "OK"|"Failed", data: {...}, errors?: [...]}
    """
    start_time = time.time()
    processing_time = 0
    
    try:
        data = request.get_json()
        if not data or 'description' not in data:
            logger.warning("Missing 'description' field in request")
            REQUEST_COUNT.labels(endpoint='detect-country', status='error').inc()
            error_response = {"result": "Failed", "errors": [{"code": "VALIDATION_ERROR", "message": "Missing 'description' field"}]}
            return jsonify(error_response), 400
        
        text = data.get("description", "").strip()
        
        if not text:
            logger.warning("Empty description in request")
            REQUEST_COUNT.labels(endpoint='detect-country', status='error').inc()
            error_response = {"result": "Failed", "errors": [{"code": "VALIDATION_ERROR", "message": "Empty description"}]}
            return jsonify(error_response), 400
        
        if text in cache:
            cached_result = cache[text].copy()
            processing_time = 0
            logger.info(f"Cache hit for text: {text[:50]}...")
            REQUEST_COUNT.labels(endpoint='detect-country', status='success').inc()
            
            success_response = {
                "result": "OK",
                "data": {
                    "attributes": cached_result['attributes'],
                    "cache": True,
                    "time": processing_time
                }
            }
            return jsonify(success_response)
        
        logger.info(f"Calling AI for: {text[:100]}...")
        if not openai_detector:
            raise ValueError("OpenAI Detector not initialized")
            

        ai_result = asyncio.run(openai_detector.detect_country(text))
        logger.info(f"AI result: {ai_result}")
        

        if 'attributes' not in ai_result:
            logger.error(f"AI result missing 'attributes' key: {ai_result}")
            attributes = openai_detector._fallback_result()['attributes']
        else:
            attributes = ai_result['attributes']
        
        country_confidence = attributes.get('country', {}).get('confidence', 0.0)
        country_value_list = attributes.get('country', {}).get('value', ["ZZ"])
        valid_country_list = validate_countries(country_value_list)
        
        if 'country' not in attributes:
            attributes['country'] = {"value": ["ZZ"], "evidence": "none", "confidence": 0.0}
            
        attributes['country']['value'] = valid_country_list
        
        result_data = {
            "attributes": attributes,
            "cache": False,
            "time": processing_time
        }
        
        if any(c != "ZZ" for c in valid_country_list) and country_confidence > 0.5:
            cache_entry = {"attributes": attributes, "source": "AI"}
            if len(cache) >= MAX_CACHE_SIZE:
                cache.popitem(last=False)
            cache[text] = cache_entry
            logger.info(f"Successful detection: {valid_country_list} (conf: {country_confidence:.2f}) for {text[:50]}...")
        else:
            logger.warning(f"Detection failed (ZZ) or low confidence for: {text[:50]}...")
        
        processing_time = int((time.time() - start_time) * 1000)
        result_data["time"] = processing_time
        
        REQUEST_COUNT.labels(endpoint='detect-country', status='success').inc()
        success_response = {"result": "OK", "data": result_data}
        return jsonify(success_response)
    
    except Exception as e:
        import traceback
        logger.error(f"Unexpected error in detect-country: {str(e)}")
        logger.error(traceback.format_exc())
        REQUEST_COUNT.labels(endpoint='detect-country', status='error').inc()
        error_response = {"result": "Failed", "errors": [{"code": "INTERNAL_ERROR", "message": str(e)}]}
        return jsonify(error_response), 500


@app.route('/batch-detect', methods=['POST'])
@REQUEST_LATENCY.time()
def batch_detect():
    """
    Batch detection for multiple descriptions (Concurrent)
    Request body: {"descriptions": ["text1", "text2", ...]}
    Response format: {result: "OK"|"Failed", data: {results: [...], total: N}, errors?: [...]}
    """
    start_time = time.time()
    
    try:
        data = request.get_json()
        descriptions = data.get("descriptions", [])
        
        if not descriptions or not isinstance(descriptions, list):
            logger.warning("Invalid 'descriptions' field in batch request")
            REQUEST_COUNT.labels(endpoint='batch-detect', status='error').inc()
            error_response = {"result": "Failed", "errors": [{"code": "VALIDATION_ERROR", "message": "Invalid 'descriptions' field"}]}
            return jsonify(error_response), 400
        

        async def _process_batch():
            results_dict = {}
            tasks_to_run = []
            texts_to_fetch = []
            cache_hits = 0
            ai_calls = 0


            for i, desc in enumerate(descriptions):
                text = desc.strip()
                if text in cache:
                    cached = cache[text].copy()
                    results_dict[i] = {"attributes": cached['attributes'], "cache": True}
                    cache_hits += 1
                else:
                    if openai_detector:
                        tasks_to_run.append(openai_detector.detect_country(text))
                        texts_to_fetch.append((i, text))
                        ai_calls += 1
                    else:
                         results_dict[i] = {"attributes": openai_detector._fallback_result()['attributes'], "cache": False}
            

            if tasks_to_run:
                logger.info(f"Running {len(tasks_to_run)} AI calls concurrently...")
                ai_results = await asyncio.gather(*tasks_to_run)
                logger.info("Concurrent AI calls finished.")
                

                for (i, text), ai_result in zip(texts_to_fetch, ai_results):
                    if 'attributes' not in ai_result:
                        attributes = openai_detector._fallback_result()['attributes']
                    else:
                        attributes = ai_result['attributes']

                    country_confidence = attributes.get('country', {}).get('confidence', 0.0)
                    country_value_list = attributes.get('country', {}).get('value', ["ZZ"])
                    valid_country_list = validate_countries(country_value_list)
                    
                    if 'country' not in attributes:
                        attributes['country'] = {"value": ["ZZ"], "evidence": "none", "confidence": 0.0}
                    attributes['country']['value'] = valid_country_list
                    
                    result_item = {"attributes": attributes, "cache": False}
                    results_dict[i] = result_item
                    
                    # Cache
                    if any(c != "ZZ" for c in valid_country_list) and country_confidence > 0.5:
                        cache_entry = {"attributes": attributes, "source": "AI"}
                        if len(cache) >= MAX_CACHE_SIZE:
                            cache.popitem(last=False)
                        cache[text] = cache_entry
                        logger.info(f"Batch success: {valid_country_list} for {text[:50]}...")
                    else:
                        logger.warning(f"Batch failed (ZZ) or low conf for: {text[:50]}...")

            results = [results_dict[i] for i in range(len(descriptions))]
            return results, cache_hits, ai_calls
        
        results, cache_hits, ai_calls = asyncio.run(_process_batch())
        
        processing_time = int((time.time() - start_time) * 1000)
        
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
        error_response = {"result": "Failed", "errors": [{"code": "INTERNAL_ERROR", "message": str(e)}]}
        return jsonify(error_response), 500

@app.route('/metrics', methods=['GET'])
def metrics():
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