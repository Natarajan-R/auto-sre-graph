# src/api/dependencies.py
from typing import Optional, Dict, Any, Callable
from fastapi import Request, HTTPException, Depends, Header, Security
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
import logging
import hashlib
import hmac
import jwt
from src.config.settings import settings
from src.models.schemas import PipelineAlert
from src.models.validators import AlertFilter, WebhookValidation

logger = logging.getLogger(__name__)

# Security
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
security = HTTPBearer(auto_error=False)

class SecurityDependencies:
    """Security dependencies for API endpoints."""
    
    @staticmethod
    async def validate_api_key(
        request: Request,
        api_key: Optional[str] = Depends(api_key_header)
    ) -> bool:
        """Validate API key from header."""
        if not settings.API_KEY:
            logger.warning("No API key configured - allowing all requests")
            return True
        
        if not api_key:
            raise HTTPException(status_code=401, detail="API key required")
        
        if api_key != settings.API_KEY.get_secret_value():
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        return True
    
    @staticmethod
    async def validate_jwt(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
    ) -> Dict[str, Any]:
        """Validate JWT token."""
        if not credentials:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            token = credentials.credentials
            payload = jwt.decode(
                token,
                settings.JWT_SECRET.get_secret_value() if settings.JWT_SECRET else "secret",
                algorithms=[settings.JWT_ALGORITHM]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    @staticmethod
    async def validate_webhook_secret(
        request: Request,
        x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
    ) -> bool:
        """Validate webhook secret."""
        if not settings.JIRA_WEBHOOK_SECRET:
            logger.warning("No webhook secret configured - allowing all webhooks")
            return True
        
        if not x_webhook_secret:
            raise HTTPException(status_code=401, detail="Webhook secret required")
        
        if x_webhook_secret != settings.JIRA_WEBHOOK_SECRET.get_secret_value():
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        return True
    
    @staticmethod
    async def validate_signature(
        request: Request,
        x_signature: Optional[str] = Header(None, alias="X-Signature")
    ) -> bool:
        """Validate HMAC signature for webhook payloads."""
        if not settings.WEBHOOK_SIGNING_SECRET:
            return True
        
        if not x_signature:
            raise HTTPException(status_code=401, detail="Signature required")
        
        # Get raw body
        body = await request.body()
        
        # Compute signature
        secret = settings.WEBHOOK_SIGNING_SECRET.get_secret_value()
        computed_signature = hmac.new(
            secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(x_signature, computed_signature):
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        return True

class RateLimiter:
    """Rate limiting dependency with in-memory store."""
    
    def __init__(self):
        self._requests: Dict[str, list] = {}
    
    async def __call__(self, request: Request) -> bool:
        """Check if request is within rate limits."""
        if not settings.RATE_LIMIT_ENABLED:
            return True
        
        limit = settings.RATE_LIMIT_REQUESTS
        period = settings.RATE_LIMIT_PERIOD
        
        # Get client identifier (IP + API key or IP alone)
        client_id = self._get_client_id(request)
        
        # Clean old requests
        now = datetime.utcnow().timestamp()
        if client_id in self._requests:
            self._requests[client_id] = [
                t for t in self._requests[client_id]
                if now - t < period
            ]
        else:
            self._requests[client_id] = []
        
        # Check limit
        if len(self._requests[client_id]) >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Maximum {limit} requests per {period} seconds."
            )
        
        # Add current request
        self._requests[client_id].append(now)
        return True
    
    def _get_client_id(self, request: Request) -> str:
        """Get unique client identifier."""
        # Try API key first
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"key:{api_key}"
        
        # Fall back to IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip:{ip}"

class ValidationDependencies:
    """Validation dependencies for request payloads."""
    
    @staticmethod
    async def validate_pipeline_alert(
        payload: PipelineAlert,
        validation: WebhookValidation = Depends()
    ) -> PipelineAlert:
        """Validate pipeline alert payload."""
        # Additional validation beyond Pydantic
        if payload.service_name and not payload.service_name.isalnum():
            # Service names should be alphanumeric with hyphens/underscores
            if not all(c.isalnum() or c in ['-', '_'] for c in payload.service_name):
                raise HTTPException(
                    status_code=400,
                    detail="Service name contains invalid characters"
                )
        
        # Check environment constraints
        if payload.environment.value in ["PROD"] and payload.severity.value not in ["CRITICAL", "HIGH"]:
            # In production, only critical/high alerts are processed
            logger.info(f"Low severity alert in PROD: {payload.alert_id}")
            # Could still process but log it
        
        return payload
    
    @staticmethod
    async def validate_content_type(request: Request) -> bool:
        """Validate content type."""
        content_type = request.headers.get("content-type")
        if content_type not in settings.ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported content type. Allowed: {settings.ALLOWED_CONTENT_TYPES}"
            )
        return True
    
    @staticmethod
    async def validate_payload_size(request: Request) -> bool:
        """Validate payload size."""
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > settings.MAX_PAYLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Payload too large. Maximum: {settings.MAX_PAYLOAD_SIZE} bytes"
                    )
            except ValueError:
                pass
        return True

class ContextDependencies:
    """Context dependencies for request handling."""
    
    @staticmethod
    async def get_alert_filter() -> AlertFilter:
        """Get alert filter instance."""
        return AlertFilter()
    
    @staticmethod
    async def get_validation_rules() -> WebhookValidation:
        """Get validation rules for webhooks."""
        return WebhookValidation(
            allowed_services=settings.ALLOWED_SERVICES,
            allowed_environments=settings.ALLOWED_ENVIRONMENTS,
            min_error_length=10,
            max_error_length=10000,
            require_stack_trace=settings.REQUIRE_STACK_TRACE
        )

# Dependency instances
security_deps = SecurityDependencies()
rate_limiter = RateLimiter()
validation_deps = ValidationDependencies()
context_deps = ContextDependencies()

# Common dependencies
async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
) -> Dict[str, Any]:
    """Get current user from JWT token."""
    if not credentials:
        return {"role": "anonymous", "authenticated": False}
    
    try:
        payload = await security_deps.validate_jwt(credentials)
        return {
            "authenticated": True,
            "user_id": payload.get("sub"),
            "role": payload.get("role", "user"),
            "email": payload.get("email")
        }
    except:
        return {"role": "anonymous", "authenticated": False}

async def require_role(role: str) -> Callable:
    """Dependency factory for role-based access control."""
    async def dependency(user: Dict[str, Any] = Depends(get_current_user)):
        if not user.get("authenticated"):
            raise HTTPException(status_code=401, detail="Authentication required")
        if user.get("role") != role and user.get("role") != "admin":
            raise HTTPException(status_code=403, detail=f"Role '{role}' required")
        return user
    return dependency