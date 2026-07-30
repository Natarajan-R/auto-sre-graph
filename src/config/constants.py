# src/config/constants.py
from enum import Enum
from typing import Dict, Any, List

class Constants:
    """Application constants."""
    
    # Application
    APP_NAME = "Auto-SRE-Graph"
    APP_VERSION = "1.0.0"
    
    # HTTP Status Codes
    HTTP_200_OK = 200
    HTTP_201_CREATED = 201
    HTTP_202_ACCEPTED = 202
    HTTP_204_NO_CONTENT = 204
    HTTP_400_BAD_REQUEST = 400
    HTTP_401_UNAUTHORIZED = 401
    HTTP_403_FORBIDDEN = 403
    HTTP_404_NOT_FOUND = 404
    HTTP_413_PAYLOAD_TOO_LARGE = 413
    HTTP_415_UNSUPPORTED_MEDIA_TYPE = 415
    HTTP_429_TOO_MANY_REQUESTS = 429
    HTTP_500_INTERNAL_ERROR = 500
    
    # Workflow Status
    WORKFLOW_STATUS = {
        'PENDING': 'PENDING',
        'PROCESSING': 'PROCESSING',
        'WAITING_ON_HUMAN': 'WAITING_ON_HUMAN',
        'APPROVAL_PROCESSED': 'APPROVAL_PROCESSED',
        'REMEDIATION_SUCCESSFUL': 'REMEDIATION_SUCCESSFUL',
        'REMEDIATION_FAILED': 'REMEDIATION_FAILED',
        'REMEDIATION_SKIPPED': 'REMEDIATION_SKIPPED',
        'ESCALATED': 'ESCALATED',
        'ERROR': 'ERROR',
        'COMPLETED': 'COMPLETED'
    }
    
    # Alert Severity
    ALERT_SEVERITY = {
        'CRITICAL': 'CRITICAL',
        'HIGH': 'HIGH',
        'MEDIUM': 'MEDIUM',
        'LOW': 'LOW',
        'INFO': 'INFO'
    }
    
    # Action Types
    ACTION_TYPES = {
        'ROLLBACK': 'ROLLBACK',
        'RESTART_SERVICE': 'RESTART_SERVICE',
        'ESCALATE_ONLY': 'ESCALATE_ONLY',
        'SCALE_UP': 'SCALE_UP',
        'CONFIG_UPDATE': 'CONFIG_UPDATE'
    }
    
    # Environment
    ENVIRONMENTS = {
        'DEV': 'DEV',
        'SIT': 'SIT',
        'UAT': 'UAT',
        'PROD': 'PROD'
    }
    
    # Error Codes
    ERROR_CODES = {
        'VALIDATION_ERROR': 'VALIDATION_ERROR',
        'CONTEXT_RETRIEVAL_ERROR': 'CONTEXT_RETRIEVAL_ERROR',
        'AGENT_ERROR': 'AGENT_ERROR',
        'JIRA_ERROR': 'JIRA_ERROR',
        'REMEDIATION_ERROR': 'REMEDIATION_ERROR',
        'DATABASE_ERROR': 'DATABASE_ERROR',
        'RATE_LIMIT_ERROR': 'RATE_LIMIT_ERROR',
        'AUTHENTICATION_ERROR': 'AUTHENTICATION_ERROR',
        'AUTHORIZATION_ERROR': 'AUTHORIZATION_ERROR',
        'TIMEOUT_ERROR': 'TIMEOUT_ERROR'
    }

class LogLevels:
    """Log level constants."""
    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'
    CRITICAL = 'CRITICAL'

class TimeConstants:
    """Time-related constants."""
    SECOND = 1
    MINUTE = 60
    HOUR = 3600
    DAY = 86400
    WEEK = 604800
    MONTH = 2592000

class ResponseMessages:
    """API response messages."""
    SUCCESS = "Operation completed successfully"
    CREATED = "Resource created successfully"
    UPDATED = "Resource updated successfully"
    DELETED = "Resource deleted successfully"
    VALIDATION_ERROR = "Validation error occurred"
    NOT_FOUND = "Resource not found"
    UNAUTHORIZED = "Authentication required"
    FORBIDDEN = "Access denied"
    RATE_LIMIT = "Rate limit exceeded"
    INTERNAL_ERROR = "Internal server error"
    WORKFLOW_STARTED = "Workflow started successfully"
    WORKFLOW_RESUMED = "Workflow resumed successfully"

class WorkflowConfig:
    """Workflow configuration constants."""
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 2.0
    MAX_RETRY_DELAY = 60.0
    DEFAULT_TIMEOUT = 300
    CHECKPOINT_INTERVAL = 30
    MAX_PARALLEL_WORKFLOWS = 10

class SecurityConfig:
    """Security configuration constants."""
    TOKEN_EXPIRY_HOURS = 24
    REFRESH_TOKEN_EXPIRY_DAYS = 7
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION_MINUTES = 15
    PASSWORD_MIN_LENGTH = 8

class DatabaseConstants:
    """Database-related constants."""
    CONNECTION_POOL_MIN = 5
    CONNECTION_POOL_MAX = 50
    CONNECTION_TIMEOUT = 30
    QUERY_TIMEOUT = 60
    TRANSACTION_TIMEOUT = 120

# Error message templates
ERROR_MESSAGES = {
    Constants.ERROR_CODES['VALIDATION_ERROR']: "Invalid payload: {details}",
    Constants.ERROR_CODES['CONTEXT_RETRIEVAL_ERROR']: "Failed to retrieve context: {details}",
    Constants.ERROR_CODES['AGENT_ERROR']: "AI agent error: {details}",
    Constants.ERROR_CODES['JIRA_ERROR']: "Jira integration error: {details}",
    Constants.ERROR_CODES['REMEDIATION_ERROR']: "Remediation failed: {details}",
    Constants.ERROR_CODES['DATABASE_ERROR']: "Database error: {details}",
    Constants.ERROR_CODES['RATE_LIMIT_ERROR']: "Rate limit exceeded. Try again in {retry_after} seconds",
    Constants.ERROR_CODES['AUTHENTICATION_ERROR']: "Authentication failed: {details}",
    Constants.ERROR_CODES['AUTHORIZATION_ERROR']: "Authorization failed: {details}",
    Constants.ERROR_CODES['TIMEOUT_ERROR']: "Operation timed out after {timeout} seconds"
}

# Default values
DEFAULTS = {
    'environment': Constants.ENVIRONMENTS['DEV'],
    'log_level': LogLevels.INFO,
    'rate_limit_requests': 100,
    'rate_limit_period': 60,
    'max_payload_size': 1048576,  # 1MB
    'api_timeout': 60,
    'agent_timeout': 60,
    'remediation_timeout': 300
}

# Feature flags
FEATURE_FLAGS = {
    'enable_auto_remediation': False,
    'enable_llm_caching': True,
    'enable_audit_logging': True,
    'enable_sla_monitoring': True,
    'enable_canary': True,
    'enable_cost_optimization': True,
    'enable_telemetry': True,
    'enable_profiling': False
}