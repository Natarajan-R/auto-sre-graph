# src/models/validators.py
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, validator
import re
from src.models.schemas import PipelineAlert

class WebhookValidation(BaseModel):
    """Validation rules for incoming webhooks."""
    allowed_services: List[str] = Field(default_factory=list)
    allowed_environments: List[str] = Field(default_factory=list)
    min_error_length: int = 10
    max_error_length: int = 10000
    require_stack_trace: bool = False
    
    def validate_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize the webhook payload."""
        # Filter out sensitive data
        sensitive_keys = ['password', 'token', 'secret', 'api_key']
        for key in sensitive_keys:
            if key in payload:
                payload[key] = '***REDACTED***'
        
        # Also redact sensitive data inside additional_context
        if 'additional_context' in payload and isinstance(payload['additional_context'], dict):
            for key in sensitive_keys:
                if key in payload['additional_context']:
                    payload['additional_context'][key] = '***REDACTED***'
        
        # Validate service name
        if self.allowed_services and payload.get('service_name'):
            if payload['service_name'] not in self.allowed_services:
                raise ValueError(f"Service {payload['service_name']} not in allowed list")
        
        # Validate environment
        if self.allowed_environments and payload.get('environment'):
            if payload['environment'] not in self.allowed_environments:
                raise ValueError(f"Environment {payload['environment']} not in allowed list")
        
        return payload

class AlertFilter(BaseModel):
    """Filter rules for dropping noisy alerts."""
    keywords_to_drop: List[str] = Field(default_factory=list)
    services_to_ignore: List[str] = Field(default_factory=list)
    min_confidence: float = 0.3
    
    def should_filter(self, alert: PipelineAlert) -> bool:
        """Determine if alert should be filtered out."""
        # Check if service is in ignore list
        if alert.service_name in self.services_to_ignore:
            return True
        
        # Check for keywords
        for keyword in self.keywords_to_drop:
            if keyword.lower() in alert.error_message.lower():
                return True
        
        return False