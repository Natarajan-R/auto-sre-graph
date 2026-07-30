# tests/unit/test_models.py
"""
Unit tests for data models and utilities.
Tests model behaviors, helper functions, and data transformations.
"""

import pytest
from datetime import datetime, timedelta
from typing import Dict, Any
import json
from decimal import Decimal

from src.models.schemas import (
    PipelineAlert,
    DiagnosticAnalysis,
    JiraTicketDraft,
    Environment,
    AlertSeverity,
    ActionType,
)
from src.models.validators import (
    WebhookValidation,
    AlertFilter,
)

from tests.fixtures.sample_alerts import SampleAlerts
from tests.fixtures.mock_data import MockData


class TestModelSerialization:
    """Tests for model serialization/deserialization."""
    
    def test_pipeline_alert_to_dict(self):
        """Test converting PipelineAlert to dict."""
        alert = SampleAlerts.get_basic_alert()
        alert_dict = alert.model_dump()
        
        assert isinstance(alert_dict, dict)
        assert alert_dict["alert_id"] == "ADO-12345"
        assert alert_dict["environment"] == "SIT"
        assert alert_dict["service_name"] == "auth-service"
        assert "timestamp" in alert_dict
    
    def test_pipeline_alert_to_json(self):
        """Test converting PipelineAlert to JSON."""
        alert = SampleAlerts.get_basic_alert()
        alert_json = alert.model_dump_json()
        
        assert isinstance(alert_json, str)
        parsed = json.loads(alert_json)
        assert parsed["alert_id"] == "ADO-12345"
        assert parsed["environment"] == "SIT"
    
    def test_diagnostic_analysis_to_dict(self):
        """Test converting DiagnosticAnalysis to dict."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Test root cause",
            historical_matches_found=True,
            confidence_score=0.85,
            proposed_action=ActionType.ROLLBACK,
            remediation_script="kubectl rollout undo"
        )
        analysis_dict = analysis.model_dump()
        
        assert isinstance(analysis_dict, dict)
        assert analysis_dict["root_cause_summary"] == "Test root cause"
        assert analysis_dict["confidence_score"] == 0.85
        assert analysis_dict["proposed_action"] == "ROLLBACK"
    
    def test_diagnostic_analysis_to_json(self):
        """Test converting DiagnosticAnalysis to JSON."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Test root cause",
            historical_matches_found=True,
            confidence_score=0.85,
            proposed_action=ActionType.ROLLBACK
        )
        analysis_json = analysis.model_dump_json()
        
        assert isinstance(analysis_json, str)
        parsed = json.loads(analysis_json)
        assert parsed["root_cause_summary"] == "Test root cause"
        assert parsed["confidence_score"] == 0.85
    
    def test_jira_ticket_to_dict(self):
        """Test converting JiraTicketDraft to dict."""
        ticket = JiraTicketDraft(
            summary="Test ticket",
            description="Test description",
            priority="High"
        )
        ticket_dict = ticket.model_dump()
        
        assert isinstance(ticket_dict, dict)
        assert ticket_dict["summary"] == "Test ticket"
        assert ticket_dict["priority"] == "High"
        assert ticket_dict["project_key"] == "SRE"


class TestModelComparison:
    """Tests for model comparison operations."""
    
    def test_alert_equality(self):
        """Test alert equality comparison."""
        alert1 = SampleAlerts.get_basic_alert()
        alert2 = SampleAlerts.get_basic_alert()
        
        # Same data should be equal (compare model_dump to ignore timestamp microsecond drift)
        assert alert1.model_dump(exclude={"timestamp"}) == alert2.model_dump(exclude={"timestamp"})
        
        # Different alert_id should not be equal
        alert3 = PipelineAlert(
            alert_id="DIFFERENT-001",
            environment=Environment.SIT,
            service_name="auth-service",
            error_message="Connection timeout"
        )
        assert alert1 != alert3
    
    def test_analysis_equality(self):
        """Test analysis equality comparison."""
        analysis1 = DiagnosticAnalysis(
            root_cause_summary="Test",
            historical_matches_found=True,
            confidence_score=0.85,
            proposed_action=ActionType.ROLLBACK
        )
        analysis2 = DiagnosticAnalysis(
            root_cause_summary="Test",
            historical_matches_found=True,
            confidence_score=0.85,
            proposed_action=ActionType.ROLLBACK
        )
        analysis3 = DiagnosticAnalysis(
            root_cause_summary="Different",
            historical_matches_found=False,
            confidence_score=0.5,
            proposed_action=ActionType.ESCALATE_ONLY
        )
        
        assert analysis1 == analysis2
        assert analysis1 != analysis3


class TestModelValidationHelpers:
    """Tests for validation helper functions."""
    
    def test_validate_error_message(self):
        """Test error message validation."""
        from src.models.schemas import PipelineAlert
        
        # Valid error message
        alert = PipelineAlert(
            alert_id="TEST-001",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="This is a valid error message"
        )
        assert alert.error_message == "This is a valid error message"
    
    def test_validate_stack_trace(self):
        """Test stack trace validation."""
        from src.models.schemas import PipelineAlert
        
        # Stack trace with ANSI codes should be cleaned
        alert = PipelineAlert(
            alert_id="TEST-002",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="Test error",
            stack_trace="\x1B[31mError:\x1B[0m Connection failed"
        )
        assert "\x1B" not in alert.stack_trace
        assert "Error: Connection failed" in alert.stack_trace
    
    def test_validate_confidence_score(self):
        """Test confidence score validation."""
        from src.models.schemas import DiagnosticAnalysis
        
        # Valid scores
        for score in [0.0, 0.5, 1.0]:
            analysis = DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=False,
                confidence_score=score,
                proposed_action=ActionType.ESCALATE_ONLY
            )
            assert analysis.confidence_score == score
        
        # Invalid scores should raise validation error
        with pytest.raises(ValidationError):
            DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=False,
                confidence_score=1.5,
                proposed_action=ActionType.ESCALATE_ONLY
            )


class TestModelFactories:
    """Tests for model factory functions."""
    
    def test_sample_alerts_factory(self):
        """Test SampleAlerts factory methods."""
        alert = SampleAlerts.get_basic_alert()
        assert isinstance(alert, PipelineAlert)
        assert alert.alert_id == "ADO-12345"
        
        alert2 = SampleAlerts.get_critical_prod_alert()
        assert alert2.environment == Environment.PROD
        assert alert2.severity == AlertSeverity.CRITICAL
        
        alert3 = SampleAlerts.get_low_severity_alert()
        assert alert3.severity == AlertSeverity.LOW
        
        all_alerts = SampleAlerts.get_all_sample_alerts()
        assert len(all_alerts) == 6
        assert all(isinstance(a, PipelineAlert) for a in all_alerts)
    
    def test_sample_diagnostic_analysis(self):
        """Test sample diagnostic analysis fixtures."""
        from tests.fixtures.sample_alerts import SampleDiagnosticAnalysis
        
        high_conf = SampleDiagnosticAnalysis.get_high_confidence_analysis()
        assert high_conf["confidence_score"] == 0.92
        assert high_conf["proposed_action"] == "ROLLBACK"
        
        medium_conf = SampleDiagnosticAnalysis.get_medium_confidence_analysis()
        assert medium_conf["confidence_score"] == 0.75
        
        low_conf = SampleDiagnosticAnalysis.get_low_confidence_analysis()
        assert low_conf["confidence_score"] == 0.35
        assert low_conf["proposed_action"] == "ESCALATE_ONLY"


class TestModelCustomValidators:
    """Tests for custom validators on models."""
    
    def test_webhook_validation_validate_payload(self):
        """Test WebhookValidation.validate_payload."""
        validator = WebhookValidation()
        payload = {
            "alert_id": "TEST-001",
            "environment": "SIT",
            "service_name": "auth-service",
            "error_message": "Test error",
            "password": "secret123",
            "token": "sk-123456"
        }
        
        result = validator.validate_payload(payload)
        assert result["password"] == "***REDACTED***"
        assert result["token"] == "***REDACTED***"
        assert result["alert_id"] == "TEST-001"
    
    def test_alert_filter_should_filter(self):
        """Test AlertFilter.should_filter."""
        filter_rules = AlertFilter(
            keywords_to_drop=["DEBUG", "INFO"],
            services_to_ignore=["logging-service"]
        )
        
        alert1 = PipelineAlert(
            alert_id="TEST-001",
            environment=Environment.DEV,
            service_name="logging-service",
            error_message="DEBUG: This is a debug message"
        )
        assert filter_rules.should_filter(alert1) is True
        
        alert2 = PipelineAlert(
            alert_id="TEST-002",
            environment=Environment.DEV,
            service_name="auth-service",
            error_message="ERROR: Connection failed"
        )
        assert filter_rules.should_filter(alert2) is False
    
    def test_sensitive_data_redaction(self):
        """Test sensitive data redaction function."""
        data = {
            "password": "secret123",
            "api_key": "sk-123456",
            "token": "abc123",
            "username": "testuser"
        }
        redacted = redact_sensitive_data(data)
        assert redacted["password"] == "***REDACTED***"
        assert redacted["api_key"] == "***REDACTED***"
        assert redacted["token"] == "***REDACTED***"
        assert redacted["username"] == "testuser"


class TestModelEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_alert_with_empty_additional_context(self):
        """Test alert with empty additional context."""
        alert = PipelineAlert(
            alert_id="EDGE-001",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="Test error",
            additional_context={}
        )
        assert alert.additional_context == {}
    
    def test_alert_with_none_additional_context(self):
        """Test alert with None additional context."""
        alert = PipelineAlert(
            alert_id="EDGE-002",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="Test error",
            additional_context=None
        )
        assert alert.additional_context is None
    
    def test_diagnostic_analysis_with_empty_lists(self):
        """Test analysis with empty lists."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Test",
            historical_matches_found=False,
            confidence_score=0.5,
            proposed_action=ActionType.ESCALATE_ONLY,
            upstream_dependencies=[],
            downstream_dependencies=[],
            historical_match_ids=[],
            alternative_actions=[]
        )
        assert analysis.upstream_dependencies == []
        assert analysis.downstream_dependencies == []
        assert analysis.historical_match_ids == []
        assert analysis.alternative_actions == []
    
    def test_jira_ticket_with_empty_labels(self):
        """Test Jira ticket with empty labels."""
        ticket = JiraTicketDraft(
            summary="Test",
            description="Test",
            priority="High",
            labels=[]
        )
        assert ticket.labels == []
    
    def test_jira_ticket_with_duplicate_labels(self):
        """Test Jira ticket with duplicate labels (should be deduplicated)."""
        ticket = JiraTicketDraft(
            summary="Test",
            description="Test",
            priority="High",
            labels=["duplicate", "duplicate", "same", "same", "unique"]
        )
        # Should deduplicate
        assert len(ticket.labels) == 3
        assert ticket.labels.count("duplicate") == 1
        assert ticket.labels.count("same") == 1
        assert ticket.labels.count("unique") == 1


class TestModelPerformance:
    """Performance tests for models."""
    
    def test_alert_serialization_performance(self):
        """Test alert serialization performance with large data."""
        import time
        
        # Create alert with large stack trace
        large_stack_trace = "Line " + "\nLine ".join([str(i) for i in range(1000)])
        alert = PipelineAlert(
            alert_id="PERF-001",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="Test error",
            stack_trace=large_stack_trace
        )
        
        start = time.time()
        for _ in range(100):
            alert.model_dump()
        duration = time.time() - start
        
        # Should serialize quickly (< 1 second for 100 serializations)
        assert duration < 1.0
    
    def test_analysis_validation_performance(self):
        """Test analysis validation performance."""
        import time
        
        start = time.time()
        for _ in range(100):
            DiagnosticAnalysis(
                root_cause_summary="Test root cause with some detailed information",
                historical_matches_found=True,
                confidence_score=0.85,
                proposed_action=ActionType.ROLLBACK,
                remediation_script="kubectl rollout undo deployment/test-service -n production"
            )
        duration = time.time() - start
        
        # Should validate quickly (< 0.5 seconds for 100 validations)
        assert duration < 0.5


class TestModelIntegration:
    """Integration tests between multiple models."""
    
    def test_alert_to_diagnostic_to_ticket_flow(self):
        """Test full flow from alert to diagnosis to ticket."""
        # Create alert
        alert = SampleAlerts.get_basic_alert()
        
        # Create diagnosis based on alert
        analysis = DiagnosticAnalysis(
            root_cause_summary=f"{alert.service_name} failure: {alert.error_message[:50]}",
            historical_matches_found=True,
            confidence_score=0.85,
            proposed_action=ActionType.ROLLBACK,
            remediation_script=f"kubectl rollout undo deployment/{alert.service_name}"
        )
        
        # Create ticket based on diagnosis
        ticket = JiraTicketDraft(
            summary=f"[AI Triage] {alert.environment.value}: {alert.service_name} - {analysis.proposed_action.value}",
            description=f"Root Cause: {analysis.root_cause_summary}\n\nConfidence: {analysis.confidence_score:.2%}",
            priority="High" if analysis.confidence_score > 0.7 else "Medium",
            environment=alert.environment.value,
            affected_service=alert.service_name,
            confidence_score=analysis.confidence_score,
            proposed_action=analysis.proposed_action.value
        )
        
        # Verify the flow
        assert ticket.summary.startswith("[AI Triage] SIT: auth-service - ROLLBACK")
        assert ticket.priority == "High"
        assert ticket.environment == "SIT"
        assert ticket.affected_service == "auth-service"
        assert ticket.confidence_score == 0.85
    
    def test_alert_filter_and_validation_flow(self):
        """Test combined filter and validation flow."""
        # Create validator and filter
        validator = WebhookValidation(
            allowed_services=["auth-service", "payment-service"],
            allowed_environments=["SIT", "UAT", "PROD"]
        )
        filter_rules = AlertFilter(
            keywords_to_drop=["DEBUG", "INFO"],
            services_to_ignore=["logging-service"]
        )
        
        # Test with valid alert
        alert = SampleAlerts.get_basic_alert()
        payload = alert.model_dump()
        
        # Validate
        validated = validator.validate_payload(payload)
        assert validated["service_name"] == "auth-service"
        
        # Filter
        assert filter_rules.should_filter(alert) is False
        
        # Test with filtered alert
        filtered_alert = SampleAlerts.get_low_severity_alert()
        assert filter_rules.should_filter(filtered_alert) is True


# Helper functions for tests
def redact_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Helper function to redact sensitive data."""
    sensitive_keys = ['password', 'token', 'secret', 'api_key']
    result = data.copy()
    for key in sensitive_keys:
        if key in result:
            result[key] = '***REDACTED***'
    return result


# Import ValidationError for tests
from pydantic import ValidationError