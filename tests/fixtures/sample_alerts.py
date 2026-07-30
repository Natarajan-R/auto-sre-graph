# tests/fixtures/sample_alerts.py
from datetime import datetime, timedelta
from typing import Dict, Any, List
from src.models.schemas import PipelineAlert, Environment, AlertSeverity

class SampleAlerts:
    """Sample alert fixtures for testing."""
    
    @staticmethod
    def get_basic_alert() -> PipelineAlert:
        """Get a basic pipeline alert."""
        return PipelineAlert(
            alert_id="ADO-12345",
            environment=Environment.SIT,
            service_name="auth-service",
            error_message="Connection timeout to database: Connection refused",
            stack_trace="""Traceback (most recent call last):
  File "/app/auth/service.py", line 45, in connect_db
    conn = psycopg2.connect(host='db.example.com')
  File "/app/auth/database.py", line 89, in __init__
    raise ConnectionError("Database connection refused")
ConnectionError: Database connection refused""",
            git_commit_hash="abc123def456",
            severity=AlertSeverity.HIGH,
            service_version="v1.2.3",
            additional_context={
                "pipeline_id": "123",
                "build_id": "456",
                "agent": "ubuntu-latest"
            }
        )
    
    @staticmethod
    def get_critical_prod_alert() -> PipelineAlert:
        """Get a critical production alert."""
        return PipelineAlert(
            alert_id="PROD-99999",
            environment=Environment.PROD,
            service_name="payment-gateway",
            error_message="CRITICAL: Payment processing service is down. Connection timeout after 30s",
            stack_trace="""Traceback (most recent call last):
  File "/app/payment/processor.py", line 234, in process_payment
    response = await client.post('/api/process', timeout=30)
  File "/app/payment/client.py", line 67, in post
    raise TimeoutError("Request timed out after 30s")
TimeoutError: Request timed out after 30s""",
            git_commit_hash="abc789def123",
            severity=AlertSeverity.CRITICAL,
            service_version="v2.0.1",
            additional_context={
                "pipeline_id": "789",
                "build_id": "101",
                "impact": "All payment transactions failing",
                "affected_customers": "~5000"
            }
        )
    
    @staticmethod
    def get_low_severity_alert() -> PipelineAlert:
        """Get a low severity alert."""
        return PipelineAlert(
            alert_id="DEV-11111",
            environment=Environment.DEV,
            service_name="logging-service",
            error_message="WARNING: disk space 85% full",
            stack_trace=None,
            git_commit_hash="def456abc789",
            severity=AlertSeverity.LOW,
            service_version="v0.1.0",
            additional_context={
                "pipeline_id": "111",
                "build_id": "222"
            }
        )
    
    @staticmethod
    def get_complex_alert() -> PipelineAlert:
        """Get a complex alert with multiple issues."""
        return PipelineAlert(
            alert_id="COMPLEX-77777",
            environment=Environment.UAT,
            service_name="order-service",
            error_message="Multiple errors: Database connection failed, Redis timeout, and API 500 errors",
            stack_trace="""Error 1 - Database:
  File "/app/order/db.py", line 56, in get_order
    cursor.execute("SELECT * FROM orders WHERE id = %s")
  psycopg2.OperationalError: connection to server at "db.postgres.svc" failed

Error 2 - Redis:
  File "/app/order/cache.py", line 23, in get_cache
    response = redis_client.get(key)
  redis.exceptions.TimeoutError: Timeout reading from socket

Error 3 - API:
  File "/app/order/api.py", line 123, in call_payment
    response = requests.post(payment_url, json=data)
  requests.exceptions.HTTPError: 500 Server Error: Internal Server Error""",
            git_commit_hash="aaa111bbb222",
            severity=AlertSeverity.CRITICAL,
            service_version="v1.5.0",
            additional_context={
                "pipeline_id": "555",
                "build_id": "666",
                "dependencies": ["auth-service", "payment-service", "inventory-service"]
            }
        )
    
    @staticmethod
    def get_malformed_alert_data() -> Dict[str, Any]:
        """Get malformed alert data for validation testing."""
        return {
            "alert_id": "",  # Empty ID
            "environment": "INVALID",  # Invalid environment
            "service_name": "!!@@invalid@@!!",  # Invalid service name
            "error_message": "short",  # Too short
            "stack_trace": None,
            "git_commit_hash": "abc",  # Too short
            "severity": "INVALID",
            "service_version": "x" * 100  # Too long
        }
    
    @staticmethod
    def get_alert_with_ansi_codes() -> PipelineAlert:
        """Get an alert with ANSI escape codes in stack trace."""
        return PipelineAlert(
            alert_id="ANSI-12345",
            environment=Environment.SIT,
            service_name="ansi-service",
            error_message="Error with ANSI codes",
            stack_trace="\x1B[31mError:\x1B[0m Connection failed\n\x1B[33mWarning:\x1B[0m Retrying...\n\x1B[32mSuccess:\x1B[0m Connected",
            git_commit_hash="abc1234567",
            severity=AlertSeverity.MEDIUM,
            service_version="v1.0.0"
        )
    
    @staticmethod
    def get_alert_with_sensitive_data() -> PipelineAlert:
        """Get an alert with sensitive data."""
        return PipelineAlert(
            alert_id="SENSITIVE-12345",
            environment=Environment.SIT,
            service_name="auth-service",
            error_message="Authentication failed for user admin",
            stack_trace="""File "/app/auth.py", line 45:
    auth_token = "sk-1234567890abcdef"
    password = "Admin@123"
    connection_string = "postgresql://user:pass@localhost:5432/db"
    api_key = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ123456789" """,
            git_commit_hash="abc123def789",
            severity=AlertSeverity.HIGH,
            service_version="v1.0.0",
            additional_context={
                "user": "admin",
                "token": "sk-1234567890abcdef",
                "password": "Admin@123"
            }
        )
    
    @staticmethod
    def get_all_sample_alerts() -> List[PipelineAlert]:
        """Get all sample alerts."""
        return [
            SampleAlerts.get_basic_alert(),
            SampleAlerts.get_critical_prod_alert(),
            SampleAlerts.get_low_severity_alert(),
            SampleAlerts.get_complex_alert(),
            SampleAlerts.get_alert_with_ansi_codes(),
            SampleAlerts.get_alert_with_sensitive_data()
        ]

class SampleDiagnosticAnalysis:
    """Sample diagnostic analysis fixtures."""
    
    @staticmethod
    def get_high_confidence_analysis() -> Dict[str, Any]:
        """Get a high confidence diagnostic analysis."""
        return {
            "root_cause_summary": "Database connection pool exhausted due to slow queries during peak load",
            "detailed_analysis": "Analysis shows 95% of database connections are held by long-running queries. The auth service is experiencing increased latency due to connection pool saturation.",
            "historical_matches_found": True,
            "historical_match_ids": ["RUN-001", "RUN-002"],
            "upstream_dependencies": ["auth-service", "user-service"],
            "downstream_dependencies": ["payment-service", "order-service"],
            "confidence_score": 0.92,
            "proposed_action": "ROLLBACK",
            "remediation_script": "kubectl rollout undo deployment/auth-service -n production",
            "estimated_impact": "Service will be unavailable for approximately 2-3 minutes during rollback",
            "alternative_actions": ["SCALE_UP", "CONFIG_UPDATE"]
        }
    
    @staticmethod
    def get_medium_confidence_analysis() -> Dict[str, Any]:
        """Get a medium confidence diagnostic analysis."""
        return {
            "root_cause_summary": "Possible memory leak in payment processing service",
            "detailed_analysis": "Memory usage has been steadily increasing over the last 24 hours. This pattern matches previous incidents involving the payment gateway.",
            "historical_matches_found": True,
            "historical_match_ids": ["RUN-003"],
            "upstream_dependencies": ["payment-gateway"],
            "downstream_dependencies": ["notification-service"],
            "confidence_score": 0.75,
            "proposed_action": "RESTART_SERVICE",
            "remediation_script": "kubectl rollout restart deployment/payment-gateway -n production",
            "estimated_impact": "Service restart will cause ~1 minute of downtime",
            "alternative_actions": ["ESCALATE_ONLY"]
        }
    
    @staticmethod
    def get_low_confidence_analysis() -> Dict[str, Any]:
        """Get a low confidence diagnostic analysis."""
        return {
            "root_cause_summary": "Unknown error pattern - manual investigation required",
            "detailed_analysis": "The error pattern does not match any historical incidents. Additional context is needed to determine the root cause.",
            "historical_matches_found": False,
            "historical_match_ids": [],
            "upstream_dependencies": ["unknown"],
            "downstream_dependencies": ["unknown"],
            "confidence_score": 0.35,
            "proposed_action": "ESCALATE_ONLY",
            "remediation_script": None,
            "estimated_impact": "Manual investigation required - estimated time: 2-4 hours",
            "alternative_actions": []
        }