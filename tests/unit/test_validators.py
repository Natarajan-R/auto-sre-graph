# tests/unit/test_validators.py
import pytest
from src.models.validators import WebhookValidation, AlertFilter
from src.models.schemas import PipelineAlert, Environment, AlertSeverity
from tests.fixtures.sample_alerts import SampleAlerts

class TestWebhookValidation:
    """Tests for WebhookValidation."""
    
    def test_validate_payload_basic(self):
        """Test basic payload validation."""
        validator = WebhookValidation()
        payload = SampleAlerts.get_basic_alert().model_dump()
        result = validator.validate_payload(payload)
        assert result is not None
    
    def test_validate_payload_sensitive_data(self):
        """Test that sensitive data is redacted."""
        validator = WebhookValidation()
        alert = SampleAlerts.get_alert_with_sensitive_data()
        payload = alert.model_dump()
        result = validator.validate_payload(payload)
        
        # Check that sensitive fields are redacted in additional_context
        if 'additional_context' in result:
            for key in ['password', 'token']:
                if key in result['additional_context']:
                    assert result['additional_context'][key] == '***REDACTED***'
    
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
        """Test allowed environments validation."""
        validator = WebhookValidation(
            allowed_environments=["SIT", "UAT"]
        )
        # Should pass for SIT
        payload = SampleAlerts.get_basic_alert().model_dump()
        result = validator.validate_payload(payload)
        assert result is not None
        
        # Should fail for PROD
        payload2 = SampleAlerts.get_critical_prod_alert().model_dump()
        with pytest.raises(ValueError):
            validator.validate_payload(payload2)

class TestAlertFilter:
    """Tests for AlertFilter."""
    
    def test_filter_by_keywords(self):
        """Test filtering alerts by keywords."""
        filter_rules = AlertFilter(
            keywords_to_drop=["DEBUG", "WARNING: disk"]
        )
        alert = SampleAlerts.get_low_severity_alert()
        # Alert contains "WARNING: disk space 85% full"
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
