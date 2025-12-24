"""
Gemini Proxy Service
Handles proxy requests to Google Gemini API with security validations.
"""

import logging
import google.generativeai as genai
from typing import Dict, Any, Optional
from google.api_core.exceptions import GoogleAPIError, ResourceExhausted, Unauthenticated

logger = logging.getLogger(__name__)

# Security: Whitelist of allowed models
ALLOWED_MODELS = {
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.0-pro"
}

# Security: Maximum prompt length to prevent abuse
MAX_PROMPT_LENGTH = 10000  # 10k characters
DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiProxyService:
    """Service to handle Gemini API proxy requests with validation and error handling."""
    
    @staticmethod
    def validate_model(model_name: str) -> tuple[bool, Optional[str]]:
        """
        Validate model name against whitelist.
        
        Args:
            model_name: The model name to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not model_name:
            return False, "Model name is required"
        
        if model_name not in ALLOWED_MODELS:
            return False, f"Model '{model_name}' not allowed. Allowed models: {', '.join(ALLOWED_MODELS)}"
        
        return True, None
    
    @staticmethod
    def validate_prompt(prompt: str) -> tuple[bool, Optional[str]]:
        """
        Validate prompt for security and length.
        
        Args:
            prompt: The prompt text to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not prompt or not prompt.strip():
            return False, "Prompt is required"
        
        if len(prompt) > MAX_PROMPT_LENGTH:
            return False, f"Prompt too long. Maximum {MAX_PROMPT_LENGTH} characters allowed"
        
        return True, None
    
    @staticmethod
    def validate_api_key(api_key: str) -> tuple[bool, Optional[str]]:
        """
        Validate API key format.
        
        Args:
            api_key: The API key to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not api_key:
            return False, "Gemini API key is required"
        
        # Basic validation: API keys should be reasonable length
        if len(api_key) < 20:
            return False, "Invalid API key format"
        
        return True, None
    
    @staticmethod
    def call_gemini_api(
        prompt: str,
        model_name: str,
        api_key: str
    ) -> Dict[str, Any]:
        """
        Call Gemini API with error handling.
        
        Args:
            prompt: The prompt text
            model_name: The model to use
            api_key: The Gemini API key
            
        Returns:
            Dict with 'success', 'response' (if success), 'error_code', 'error_message'
        """
        try:
            # Configure Gemini with the API key
            genai.configure(api_key=api_key)
            
            # Create model instance
            model = genai.GenerativeModel(model_name=model_name)
            
            # Generate content
            logger.info(f"Calling Gemini API: model={model_name}, prompt_length={len(prompt)}")
            response = model.generate_content(prompt)
            
            # Extract response text
            response_text = response.text if hasattr(response, 'text') else str(response)
            
            return {
                "success": True,
                "response": response_text
            }
            
        except ResourceExhausted as e:
            logger.warning(f"Gemini quota exhausted: {str(e)}")
            return {
                "success": False,
                "error_code": "QUOTA_ERROR",
                "error_message": "Gemini API quota exceeded. Please try again later."
            }
            
        except Unauthenticated as e:
            logger.error(f"Gemini authentication failed: {str(e)}")
            return {
                "success": False,
                "error_code": "AUTH_ERROR",
                "error_message": "Invalid Gemini API key. Please check your credentials."
            }
            
        except GoogleAPIError as e:
            logger.error(f"Gemini API error: {str(e)}")
            error_msg = str(e)
            
            # Check for model not found
            if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                return {
                    "success": False,
                    "error_code": "MODEL_NOT_FOUND",
                    "error_message": f"Model '{model_name}' not found or not accessible."
                }
            
            return {
                "success": False,
                "error_code": "API_ERROR",
                "error_message": f"Gemini API error: {error_msg}"
            }
            
        except Exception as e:
            logger.error(f"Unexpected error calling Gemini API: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error_code": "INTERNAL_ERROR",
                "error_message": f"Internal error: {str(e)}"
            }
    
    @classmethod
    def process_proxy_request(
        cls,
        prompt: str,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        fallback_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a complete proxy request with all validations.
        
        Args:
            prompt: The prompt text
            model_name: Optional model name (defaults to gemini-2.0-flash)
            api_key: Optional custom API key
            fallback_api_key: Fallback API key from server config
            
        Returns:
            Dict with 'success', 'data' or 'error_code', 'error_message'
        """
        # Use default model if not provided
        model = (model_name or DEFAULT_MODEL).strip()
        
        # Validate prompt
        valid_prompt, prompt_error = cls.validate_prompt(prompt)
        if not valid_prompt:
            return {
                "success": False,
                "error_code": "VALIDATION_ERROR",
                "error_message": prompt_error
            }
        
        # Validate model
        valid_model, model_error = cls.validate_model(model)
        if not valid_model:
            return {
                "success": False,
                "error_code": "VALIDATION_ERROR",
                "error_message": model_error
            }
        
        # Determine which API key to use
        key_to_use = (api_key or fallback_api_key or "").strip()
        
        # Validate API key
        valid_key, key_error = cls.validate_api_key(key_to_use)
        if not valid_key:
            return {
                "success": False,
                "error_code": "CONFIG_ERROR",
                "error_message": key_error
            }
        
        # Call Gemini API
        result = cls.call_gemini_api(prompt, model, key_to_use)
        
        return result
