"""
Gemini Detector Service - Centralized service for validation and processing
Handles custom model and API key validation with detailed error handling.
"""

import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_MODEL = "gemini-2.0-flash"
VALID_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.5-flash", 
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-pro"
]


class GeminiDetectorService:
    """Service to handle Gemini detector requests with validation."""
    
    @staticmethod
    def validate_model(model_name: str) -> Tuple[bool, Optional[str]]:
        """
        Validate model name format.
        
        Args:
            model_name: The model name to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not model_name:
            return False, "Model name is required"
        
        model_name = model_name.strip()
        
        if len(model_name) < 3:
            return False, "Invalid model name format"
        
        # Optional: Check if model is in known list (can be disabled for flexibility)
        # if model_name not in VALID_MODELS:
        #     return False, f"Model '{model_name}' is not supported. Valid models: {', '.join(VALID_MODELS)}"
        
        return True, None
    
    @staticmethod
    def validate_api_key(api_key: str) -> Tuple[bool, Optional[str]]:
        """
        Validate API key format.
        
        Args:
            api_key: The API key to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not api_key:
            return False, "Gemini API key is required"
        
        api_key = api_key.strip()
        
        if len(api_key) < 20:
            return False, "Invalid API key format"
        
        return True, None
    
    @staticmethod
    def validate_description(description: str) -> Tuple[bool, Optional[str]]:
        """
        Validate product description.
        
        Args:
            description: The description to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not description or not description.strip():
            return False, "Description is required"
        
        return True, None
    
    @classmethod
    def validate_custom_params(
        cls,
        model_name: Optional[str],
        api_key: Optional[str]
    ) -> Dict[str, Any]:
        """
        Validate custom model and API key parameters.
        Ensures both are provided together or both are omitted.
        
        Args:
            model_name: Optional custom model name
            api_key: Optional custom API key
            
        Returns:
            Dict with 'success', and 'error_code'/'error_message' if validation fails
        """
        # Check if user is providing custom values
        has_custom_model = model_name is not None and model_name.strip() != ""
        has_custom_key = api_key is not None and api_key.strip() != ""
        
        # Validation: If providing custom model, must also provide custom key
        if has_custom_model and not has_custom_key:
            return {
                "success": False,
                "error_code": "VALIDATION_ERROR",
                "error_message": "Custom model requires custom api_key. Please provide both 'model' and 'api_key' together, or omit both to use defaults."
            }
        
        # Validation: If providing custom key, must also provide custom model
        if has_custom_key and not has_custom_model:
            return {
                "success": False,
                "error_code": "VALIDATION_ERROR",
                "error_message": "Custom api_key requires custom model. Please provide both 'model' and 'api_key' together, or omit both to use defaults."
            }
        
        # If custom params provided, validate them
        if has_custom_model and has_custom_key:
            # Validate model
            valid_model, model_error = cls.validate_model(model_name)
            if not valid_model:
                return {
                    "success": False,
                    "error_code": "VALIDATION_ERROR",
                    "error_message": model_error
                }
            
            # Validate API key format (not actual validity, that's checked when calling API)
            valid_key, key_error = cls.validate_api_key(api_key)
            if not valid_key:
                return {
                    "success": False,
                    "error_code": "VALIDATION_ERROR",
                    "error_message": key_error
                }
        
        return {"success": True}
    
    @classmethod
    def prepare_detector_config(
        cls,
        model_name: Optional[str],
        api_key: Optional[str],
        fallback_api_key: Optional[str]
    ) -> Dict[str, Any]:
        """
        Prepare configuration for detector with validation.
        
        Args:
            model_name: Optional custom model name
            api_key: Optional custom API key
            fallback_api_key: Fallback API key from server config
            
        Returns:
            Dict with 'success', 'model', 'api_key' or 'error_code', 'error_message'
        """
        # Validate custom params
        validation_result = cls.validate_custom_params(model_name, api_key)
        if not validation_result["success"]:
            return validation_result
        
        # Determine which model and key to use
        has_custom = model_name is not None and model_name.strip() != ""
        
        final_model = (model_name or DEFAULT_MODEL).strip()
        final_key = (api_key if has_custom else fallback_api_key or "").strip()
        
        # Validate final API key
        valid_key, key_error = cls.validate_api_key(final_key)
        if not valid_key:
            return {
                "success": False,
                "error_code": "CONFIG_ERROR",
                "error_message": key_error or "Gemini API key is not configured"
            }
        
        return {
            "success": True,
            "model": final_model,
            "api_key": final_key,
            "is_custom": has_custom
        }
