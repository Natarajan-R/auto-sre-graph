# tests/unit/test_schemas.py
"""
Unit tests for Pydantic schemas.
Tests all schema validation, constraints, and custom validators.
"""

import pytest
from datetime import datetime, timedelta
from pydantic import ValidationError
from typing import Dict, Any

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


class TestPipelineAlert:
    """Tests for PipelineAlert schema."""
    
    def test_valid_alert(self):
        """Test that a valid alert passes validation."""
        alert = SampleAlerts.get_basic_alert()
        assert alert.alert_id == "ADO-12345"
        assert alert.environment == Environment.SIT
        assert alert.service_name == "auth-service"
        assert alert.severity == AlertSeverity.HIGH
        assert alert.git_commit_hash == "abc123def456"
        assert alert.error_message == "Connection timeout to database: Connection refused"
        assert alert.additional_context is not None
        assert "pipeline_id" in alert.additional_context
    
    def test_alert_with_minimal_fields(self):
        """Test alert with only required fields."""
        alert = PipelineAlert(
            alert_id="MINIMAL-001",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="Test error message"
        )
        assert alert.alert_id == "MINIMAL-001"
        assert alert.stack_trace is None
        assert alert.git_commit_hash is None
        assert alert.severity == AlertSeverity.HIGH  # Default
        assert alert.service_version is None
        assert alert.additional_context is None
    
    def test_alert_with_all_fields(self):
        """Test alert with all fields populated."""
        timestamp = datetime.utcnow()
        alert = PipelineAlert(
            alert_id="FULL-001",
            environment=Environment.PROD,
            service_name="payment-service",
            timestamp=timestamp,
            error_message="Payment processing failed: Timeout after 30s",
            stack_trace="Traceback: TimeoutError at payment/processor.py:234",
            git_commit_hash="abc123def4567890",
            severity=AlertSeverity.CRITICAL,
            service_version="v2.0.1",
            additional_context={
                "pipeline_id": "789",
                "build_id": "101",
                "impact": "All payment transactions failing",
                "affected_customers": "~5000"
            }
        )
        assert alert.alert_id == "FULL-001"
        assert alert.timestamp == timestamp
        assert alert.severity == AlertSeverity.CRITICAL
        assert alert.service_version == "v2.0.1"
        assert "impact" in alert.additional_context
    
    def test_invalid_environment(self):
        """Test that invalid environment raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="INVALID-001",
                environment="INVALID_ENV",  # type: ignore
                service_name="test-service",
                error_message="Test error"
            )
        assert "environment" in str(exc_info.value)
    
    def test_invalid_alert_id_empty(self):
        """Test that empty alert_id raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="",
                environment=Environment.DEV,
                service_name="test-service",
                error_message="Test error"
            )
        assert "alert_id" in str(exc_info.value)
    
    def test_alert_id_max_length(self):
        """Test that alert_id exceeds max length raises error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="a" * 101,  # Max 100
                environment=Environment.DEV,
                service_name="test-service",
                error_message="Test error"
            )
        assert "alert_id" in str(exc_info.value)
    
    def test_error_message_min_length(self):
        """Test that error message shorter than min length raises error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="MIN-LENGTH-001",
                environment=Environment.DEV,
                service_name="test-service",
                error_message="short"  # Less than min_length=10
            )
        assert "error_message" in str(exc_info.value)
    
    def test_error_message_max_length(self):
        """Test that error message exceeds max length raises error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="MAX-LENGTH-001",
                environment=Environment.DEV,
                service_name="test-service",
                error_message="x" * 10001  # Max 10000
            )
        assert "error_message" in str(exc_info.value)
    
    def test_error_message_whitespace_cleaning(self):
        """Test that excessive whitespace is removed from error message."""
        alert = PipelineAlert(
            alert_id="WHITESPACE-001",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="This   has    multiple     spaces    and\nnewlines\n\n"
        )
        # Should be cleaned
        assert "  " not in alert.error_message
        assert "\n" not in alert.error_message
    
    def test_invalid_git_commit_hash(self):
        """Test that invalid git commit hash raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="GIT-001",
                environment=Environment.DEV,
                service_name="test-service",
                error_message="Test error message",
                git_commit_hash="abc"  # Too short
            )
        assert "git_commit_hash" in str(exc_info.value)
    
    def test_git_commit_hash_valid_format(self):
        """Test that valid git commit hash passes validation."""
        alert = PipelineAlert(
            alert_id="GIT-002",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="Test error",
            git_commit_hash="abc123def4567890"
        )
        assert alert.git_commit_hash == "abc123def4567890"
    
    def test_git_commit_hash_with_invalid_characters(self):
        """Test that invalid characters in git commit hash raise error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="GIT-003",
                environment=Environment.DEV,
                service_name="test-service",
                error_message="Test error",
                git_commit_hash="abc123!@#$"  # Invalid characters
            )
        assert "git_commit_hash" in str(exc_info.value)
    
    def test_ansi_escape_removal(self):
        """Test that ANSI escape codes are removed from stack trace."""
        alert = SampleAlerts.get_alert_with_ansi_codes()
        # ANSI codes should be removed by validator
        assert "\x1B" not in alert.stack_trace
        assert "Connection failed" in alert.stack_trace
        assert "Retrying..." in alert.stack_trace
    
    def test_additional_context_validation(self):
        """Test additional context field."""
        alert = SampleAlerts.get_basic_alert()
        assert alert.additional_context is not None
        assert "pipeline_id" in alert.additional_context
        assert alert.additional_context["pipeline_id"] == "123"
    
    def test_additional_context_with_sensitive_data(self):
        """Test additional context with sensitive data."""
        alert = SampleAlerts.get_alert_with_sensitive_data()
        assert alert.additional_context is not None
        # Note: The validator removes ANSI codes but doesn't redact sensitive data
        # This is handled by WebhookValidation
        assert "user" in alert.additional_context
    
    def test_service_name_validation(self):
        """Test service name validation."""
        # Valid service name
        alert = PipelineAlert(
            alert_id="SERVICE-001",
            environment=Environment.DEV,
            service_name="auth-service",
            error_message="Test error"
        )
        assert alert.service_name == "auth-service"
        
        # Service name with underscores
        alert = PipelineAlert(
            alert_id="SERVICE-002",
            environment=Environment.DEV,
            service_name="auth_service",
            error_message="Test error"
        )
        assert alert.service_name == "auth_service"
    
    def test_service_name_max_length(self):
        """Test that service name exceeds max length raises error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="SERVICE-001",
                environment=Environment.DEV,
                service_name="a" * 101,  # Max 100
                error_message="Test error"
            )
        assert "service_name" in str(exc_info.value)
    
    def test_stack_trace_max_length(self):
        """Test that stack trace exceeds max length raises error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="STACK-001",
                environment=Environment.DEV,
                service_name="test-service",
                error_message="Test error",
                stack_trace="x" * 100001  # Max 100000
            )
        assert "stack_trace" in str(exc_info.value)
    
    def test_timestamp_default(self):
        """Test that timestamp defaults to current UTC time."""
        alert = PipelineAlert(
            alert_id="TIME-001",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="Test error"
        )
        now = datetime.utcnow()
        # Allow small time difference
        assert (now - alert.timestamp).total_seconds() < 5
    
    def test_service_version_validation(self):
        """Test service version validation."""
        alert = PipelineAlert(
            alert_id="VERSION-001",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="Test error",
            service_version="v1.2.3"
        )
        assert alert.service_version == "v1.2.3"
    
    def test_service_version_max_length(self):
        """Test that service version exceeds max length raises error."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineAlert(
                alert_id="VERSION-002",
                environment=Environment.DEV,
                service_name="test-service",
                error_message="Test error",
                service_version="a" * 51  # Max 50
            )
        assert "service_version" in str(exc_info.value)


class TestDiagnosticAnalysis:
    """Tests for DiagnosticAnalysis schema."""
    
    def test_valid_analysis(self):
        """Test that a valid analysis passes validation."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Test root cause",
            historical_matches_found=True,
            confidence_score=0.85,
            proposed_action=ActionType.ROLLBACK,
            remediation_script="kubectl rollout undo deployment/test"
        )
        assert analysis.root_cause_summary == "Test root cause"
        assert analysis.confidence_score == 0.85
        assert analysis.proposed_action == ActionType.ROLLBACK
        assert analysis.historical_matches_found is True
    
    def test_analysis_with_all_fields(self):
        """Test analysis with all fields populated."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Database connection pool exhausted due to slow queries",
            detailed_analysis="Analysis shows 95% of database connections are held by long-running queries.",
            historical_matches_found=True,
            historical_match_ids=["RUN-001", "RUN-002"],
            upstream_dependencies=["auth-service", "user-service"],
            downstream_dependencies=["payment-service", "order-service"],
            confidence_score=0.92,
            proposed_action=ActionType.ROLLBACK,
            remediation_script="kubectl rollout undo deployment/auth-service -n production",
            estimated_impact="Service will be unavailable for approximately 2-3 minutes",
            alternative_actions=["SCALE_UP", "CONFIG_UPDATE"]
        )
        assert analysis.root_cause_summary == "Database connection pool exhausted due to slow queries"
        assert len(analysis.historical_match_ids) == 2
        assert len(analysis.upstream_dependencies) == 2
        assert len(analysis.downstream_dependencies) == 2
        assert analysis.confidence_score == 0.92
        assert analysis.estimated_impact is not None
        assert len(analysis.alternative_actions) == 2
    
    def test_confidence_score_bounds(self):
        """Test that confidence score must be between 0 and 1."""
        with pytest.raises(ValidationError):
            DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=False,
                confidence_score=1.5,  # > 1
                proposed_action=ActionType.ESCALATE_ONLY
            )
        
        with pytest.raises(ValidationError):
            DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=False,
                confidence_score=-0.5,  # < 0
                proposed_action=ActionType.ESCALATE_ONLY
            )
    
    def test_confidence_score_rounding(self):
        """Test that confidence score is rounded to 4 decimal places."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Test",
            historical_matches_found=False,
            confidence_score=0.123456789,
            proposed_action=ActionType.ESCALATE_ONLY
        )
        assert analysis.confidence_score == 0.1235
    
    def test_root_cause_summary_max_length(self):
        """Test that root cause summary exceeds max length raises error."""
        with pytest.raises(ValidationError):
            DiagnosticAnalysis(
                root_cause_summary="x" * 251,  # Max 250
                historical_matches_found=False,
                confidence_score=0.5,
                proposed_action=ActionType.ESCALATE_ONLY
            )
    
    def test_detailed_analysis_max_length(self):
        """Test that detailed analysis exceeds max length raises error."""
        with pytest.raises(ValidationError):
            DiagnosticAnalysis(
                root_cause_summary="Test",
                detailed_analysis="x" * 2001,  # Max 2000
                historical_matches_found=False,
                confidence_score=0.5,
                proposed_action=ActionType.ESCALATE_ONLY
            )
    
    def test_remediation_script(self):
        """Test remediation script field."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Test",
            historical_matches_found=False,
            confidence_score=0.5,
            proposed_action=ActionType.ROLLBACK,
            remediation_script="kubectl rollout undo deployment/test"
        )
        assert analysis.remediation_script == "kubectl rollout undo deployment/test"
        
        # Test with None
        analysis2 = DiagnosticAnalysis(
            root_cause_summary="Test",
            historical_matches_found=False,
            confidence_score=0.5,
            proposed_action=ActionType.ESCALATE_ONLY
        )
        assert analysis2.remediation_script is None
    
    def test_remediation_script_max_length(self):
        """Test that remediation script exceeds max length raises error."""
        with pytest.raises(ValidationError):
            DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=False,
                confidence_score=0.5,
                proposed_action=ActionType.ROLLBACK,
                remediation_script="x" * 5001  # Max 5000
            )
    
    def test_estimated_impact_max_length(self):
        """Test that estimated impact exceeds max length raises error."""
        with pytest.raises(ValidationError):
            DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=False,
                confidence_score=0.5,
                proposed_action=ActionType.ROLLBACK,
                estimated_impact="x" * 501  # Max 500
            )
    
    def test_proposed_action_validation(self):
        """Test proposed action validation."""
        # Valid actions
        for action in ActionType:
            analysis = DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=False,
                confidence_score=0.5,
                proposed_action=action
            )
            assert analysis.proposed_action == action
        
        # Invalid action should fail at type level
        with pytest.raises(ValidationError):
            DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=False,
                confidence_score=0.5,
                proposed_action="INVALID_ACTION"  # type: ignore
            )
    
    def test_alternative_actions_type(self):
        """Test alternative actions type."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Test",
            historical_matches_found=False,
            confidence_score=0.5,
            proposed_action=ActionType.ROLLBACK,
            alternative_actions=["SCALE_UP", "CONFIG_UPDATE"]
        )
        assert isinstance(analysis.alternative_actions, list)
        assert len(analysis.alternative_actions) == 2
    
    def test_default_field_values(self):
        """Test default field values."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Test",
            historical_matches_found=False,
            confidence_score=0.5,
            proposed_action=ActionType.ESCALATE_ONLY
        )
        assert analysis.upstream_dependencies == []
        assert analysis.downstream_dependencies == []
        assert analysis.alternative_actions == []
        assert analysis.historical_match_ids == []
        assert analysis.remediation_script is None
        assert analysis.detailed_analysis is None


class TestJiraTicketDraft:
    """Tests for JiraTicketDraft schema."""
    
    def test_valid_ticket(self):
        """Test that a valid ticket passes validation."""
        ticket = JiraTicketDraft(
            summary="Test ticket",
            description="Test description",
            priority="High"
        )
        assert ticket.summary == "Test ticket"
        assert ticket.priority == "High"
        assert ticket.project_key == "SRE"  # Default
    
    def test_ticket_with_all_fields(self):
        """Test ticket with all fields populated."""
        ticket = JiraTicketDraft(
            project_key="SRE",
            issue_type="Incident",
            summary="[AI Triage] PROD: auth-service - Connection timeout",
            description="Root Cause Analysis: Database connection pool exhausted",
            priority="Critical",
            labels=["auto-sre", "prod", "auth-service"],
            assignee_id="john.doe@example.com",
            environment="PROD",
            affected_service="auth-service",
            confidence_score=0.92,
            proposed_action="ROLLBACK"
        )
        assert ticket.project_key == "SRE"
        assert ticket.issue_type == "Incident"
        assert ticket.summary.startswith("[AI Triage]")
        assert ticket.priority == "Critical"
        assert len(ticket.labels) == 3
        assert ticket.assignee_id == "john.doe@example.com"
        assert ticket.environment == "PROD"
        assert ticket.confidence_score == 0.92
    
    def test_priority_validation(self):
        """Test priority validation."""
        valid_priorities = ['Blocker', 'Critical', 'High', 'Medium', 'Low']
        for priority in valid_priorities:
            ticket = JiraTicketDraft(
                summary="Test",
                description="Test",
                priority=priority
            )
            assert ticket.priority == priority
        
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="Test",
                description="Test",
                priority="InvalidPriority"
            )
    
    def test_label_cleaning(self):
        """Test that labels are cleaned and deduplicated."""
        ticket = JiraTicketDraft(
            summary="Test",
            description="Test",
            priority="High",
            labels=["Test Label!", "test-label", "Test_Label!", "duplicate", "duplicate"]
        )
        # Labels should be lowercased, cleaned, and deduplicated
        assert "testlabel" in ticket.labels
        assert "test-label" in ticket.labels
        assert "test_label" in ticket.labels
        assert "duplicate" in ticket.labels
        assert ticket.labels.count("duplicate") == 1
    
    def test_labels_max_items(self):
        """Test that labels exceed max items raises error."""
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="Test",
                description="Test",
                priority="High",
                labels=["label-{}".format(i) for i in range(21)]  # Max 20
            )
    
    def test_project_key_validation(self):
        """Test project key validation."""
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="Test",
                description="Test",
                priority="High",
                project_key="A"  # Too short (min 2)
            )
        
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="Test",
                description="Test",
                priority="High",
                project_key="x" * 11  # Too long (max 10)
            )
    
    def test_summary_max_length(self):
        """Test that summary exceeds max length raises error."""
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="x" * 256,  # Max 255
                description="Test",
                priority="High"
            )
    
    def test_description_max_length(self):
        """Test that description exceeds max length raises error."""
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="Test",
                description="x" * 65536,  # Max 65535
                priority="High"
            )
    
    def test_confidence_score_bounds(self):
        """Test that confidence score must be between 0 and 1."""
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="Test",
                description="Test",
                priority="High",
                confidence_score=1.5
            )
        
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="Test",
                description="Test",
                priority="High",
                confidence_score=-0.5
            )
    
    def test_assignee_id_max_length(self):
        """Test that assignee ID exceeds max length raises error."""
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="Test",
                description="Test",
                priority="High",
                assignee_id="a" * 101  # Max 100
            )
    
    def test_proposed_action_max_length(self):
        """Test that proposed action exceeds max length raises error."""
        with pytest.raises(ValidationError):
            JiraTicketDraft(
                summary="Test",
                description="Test",
                priority="High",
                proposed_action="a" * 51  # Max 50
            )
    
    def test_environment_field(self):
        """Test environment field."""
        ticket = JiraTicketDraft(
            summary="Test",
            description="Test",
            priority="High",
            environment="PROD"
        )
        assert ticket.environment == "PROD"
    
    def test_affected_service_field(self):
        """Test affected service field."""
        ticket = JiraTicketDraft(
            summary="Test",
            description="Test",
            priority="High",
            affected_service="auth-service"
        )
        assert ticket.affected_service == "auth-service"


class TestWebhookValidation:
    """Tests for WebhookValidation model."""
    
    def test_default_values(self):
        """Test default values."""
        validator = WebhookValidation()
        assert validator.allowed_services == []
        assert validator.allowed_environments == []
        assert validator.min_error_length == 10
        assert validator.max_error_length == 10000
        assert validator.require_stack_trace is False
    
    def test_validate_payload_basic(self):
        """Test basic payload validation."""
        validator = WebhookValidation()
        payload = SampleAlerts.get_basic_alert().model_dump()
        result = validator.validate_payload(payload)
        assert result is not None
    
    def test_validate_payload_sensitive_data(self):
        """Test that sensitive data is redacted at the top level."""
        validator = WebhookValidation()
        payload = {
            "alert_id": "SENSITIVE-001",
            "environment": "SIT",
            "service_name": "auth-service",
            "error_message": "Test error",
            "password": "secret123",
            "token": "sk-123456"
        }
        result = validator.validate_payload(payload)
        
        assert result["password"] == "***REDACTED***"
        assert result["token"] == "***REDACTED***"
    
    def test_validate_payload_allowed_services(self):
        """Test allowed services validation."""
        validator = WebhookValidation(
            allowed_services=["auth-service", "payment-service"]
        )
        payload = SampleAlerts.get_basic_alert().model_dump()
        result = validator.validate_payload(payload)
        assert result is not None
        
        # Test with disallowed service
        validator2 = WebhookValidation(allowed_services=["payment-service"])
        with pytest.raises(ValueError):
            validator2.validate_payload(payload)
    
    def test_validate_payload_allowed_environments(self):
        """Test allowed environments accessor."""
        validator = WebhookValidation(
            allowed_environments=["SIT", "UAT"]
        )
        assert validator.allowed_environments == ["SIT", "UAT"]
    
    def test_validate_payload_with_extra_fields(self):
        """Test payload validation with extra fields."""
        validator = WebhookValidation()
        payload = SampleAlerts.get_basic_alert().model_dump()
        payload["extra_field"] = "extra_value"
        result = validator.validate_payload(payload)
        # Extra fields should be preserved
        assert result.get("extra_field") == "extra_value"


class TestAlertFilter:
    """Tests for AlertFilter."""
    
    def test_default_values(self):
        """Test default values."""
        filter_rules = AlertFilter()
        assert filter_rules.keywords_to_drop == []
        assert filter_rules.services_to_ignore == []
        assert filter_rules.min_confidence == 0.3
    
    def test_filter_by_keywords(self):
        """Test filtering alerts by keywords."""
        filter_rules = AlertFilter(
            keywords_to_drop=["DEBUG", "disk space"]
        )
        alert = SampleAlerts.get_low_severity_alert()
        # Alert contains "disk space 85% full"
        assert filter_rules.should_filter(alert) is True
        
        # Alert without filtered keywords
        alert2 = SampleAlerts.get_basic_alert()
        assert filter_rules.should_filter(alert2) is False
    
    def test_filter_by_service(self):
        """Test filtering alerts by service."""
        filter_rules = AlertFilter(
            services_to_ignore=["logging-service"]
        )
        alert = SampleAlerts.get_low_severity_alert()  # logging-service
        assert filter_rules.should_filter(alert) is True
        
        alert2 = SampleAlerts.get_basic_alert()  # auth-service
        assert filter_rules.should_filter(alert2) is False
    
    def test_filter_by_keywords_case_insensitive(self):
        """Test that keyword filtering is case insensitive."""
        filter_rules = AlertFilter(
            keywords_to_drop=["connection timeout"]
        )
        alert = SampleAlerts.get_basic_alert()
        # Alert contains "Connection timeout to database"
        assert filter_rules.should_filter(alert) is True
    
    def test_multiple_filter_rules(self):
        """Test multiple filter rules together."""
        filter_rules = AlertFilter(
            keywords_to_drop=["DEBUG"],
            services_to_ignore=["logging-service"],
            min_confidence=0.5
        )
        
        alert1 = SampleAlerts.get_low_severity_alert()
        assert filter_rules.should_filter(alert1) is True
        
        alert2 = SampleAlerts.get_basic_alert()
        assert filter_rules.should_filter(alert2) is False
    
    def test_no_filter_rules(self):
        """Test with no filter rules (should not filter anything)."""
        filter_rules = AlertFilter()
        
        alert1 = SampleAlerts.get_basic_alert()
        assert filter_rules.should_filter(alert1) is False
        
        alert2 = SampleAlerts.get_low_severity_alert()
        assert filter_rules.should_filter(alert2) is False
    
    def test_min_confidence_filter(self):
        """Test min confidence filter (for future use)."""
        # This test ensures the min_confidence field exists
        filter_rules = AlertFilter(min_confidence=0.3)
        assert filter_rules.min_confidence == 0.3


class TestSchemaIntegrations:
    """Integration tests between schemas."""
    
    def test_alert_to_analysis_flow(self):
        """Test that alert can be used to generate analysis."""
        alert = SampleAlerts.get_basic_alert()
        
        analysis = DiagnosticAnalysis(
            root_cause_summary=f"Error in {alert.service_name}: {alert.error_message[:50]}",
            historical_matches_found=False,
            confidence_score=0.5,
            proposed_action=ActionType.ESCALATE_ONLY
        )
        
        assert analysis.root_cause_summary.startswith("Error in auth-service")
    
    def test_analysis_to_ticket_flow(self):
        """Test that analysis can be used to create a ticket."""
        analysis = DiagnosticAnalysis(
            root_cause_summary="Database connection pool exhausted",
            historical_matches_found=True,
            confidence_score=0.92,
            proposed_action=ActionType.ROLLBACK
        )
        
        ticket = JiraTicketDraft(
            summary=f"[AI Triage] {analysis.proposed_action.value}: {analysis.root_cause_summary[:50]}",
            description=analysis.root_cause_summary,
            priority="Critical" if analysis.confidence_score > 0.8 else "High",
            confidence_score=analysis.confidence_score,
            proposed_action=analysis.proposed_action
        )
        
        assert ticket.summary.startswith("[AI Triage] ROLLBACK")
        assert ticket.priority == "Critical"
        assert ticket.confidence_score == 0.92