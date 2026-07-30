# tests/integration/test_api.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock

# Patch SREWorkflow before importing app to prevent real connections at module level
import os
os.environ["OPENAI_API_KEY"] = "test-key"
import importlib
_sre_mod = importlib.import_module("src.orchestrator.graph")
_patcher = patch.object(_sre_mod, "SREWorkflow")
_patcher.start()
from src.api.webhooks import app
_patcher.stop()

from src.models.schemas import Environment, AlertSeverity
from tests.fixtures.sample_alerts import SampleAlerts
from tests.fixtures.mock_data import MockData

client = TestClient(app)

class TestAPIEndpoints:
    """Integration tests for API endpoints."""
    
    def test_health_check(self):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "environment" in data
        assert "version" in data
    
    @patch("src.api.webhooks.workflow.start_workflow")
    def test_ado_webhook(self, mock_start_workflow):
        """Test ADO webhook endpoint."""
        # Mock the workflow start
        mock_start_workflow.return_value = {
            "status": "WAITING_ON_HUMAN",
            "thread_id": "ADO-12345"
        }
        
        # Prepare payload
        payload = {
            "alert_id": "ADO-12345",
            "environment": "SIT",
            "service_name": "auth-service",
            "error_message": "Connection timeout to database",
            "stack_trace": "Traceback: Connection refused",
            "git_commit_hash": "abc123def456",
            "severity": "HIGH"
        }
        
        response = client.post("/webhooks/ado", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
        assert data["alert_id"] == "ADO-12345"
        
        # Verify workflow was called
        mock_start_workflow.assert_called_once()
    
    @patch("src.api.webhooks.workflow.start_workflow")
    def test_ado_webhook_with_filtered_alert(self, mock_start_workflow):
        """Test ADO webhook with a filtered alert."""
        # Mock alert filtering - patch the class method not the instance
        from src.api.webhooks import alert_filter
        with patch.object(type(alert_filter), "should_filter", return_value=True):
            payload = {
                "alert_id": "FILTERED-001",
                "environment": "DEV",
                "service_name": "logging-service",
                "error_message": "DEBUG: Test message",
                "severity": "LOW"
            }
            
            response = client.post("/webhooks/ado", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "filtered"
            
            # Workflow should not be started for filtered alerts
            mock_start_workflow.assert_not_called()
    
    def test_ado_webhook_invalid_payload(self):
        """Test ADO webhook with invalid payload."""
        payload = {
            "alert_id": "",  # Empty ID
            "environment": "INVALID",  # Invalid environment
            "service_name": "",  # Empty service name
            "error_message": "short"  # Too short
        }
        
        response = client.post("/webhooks/ado", json=payload)
        assert response.status_code == 422  # Validation error
    
    def test_ado_webhook_missing_fields(self):
        """Test ADO webhook with missing required fields."""
        payload = {
            "alert_id": "TEST-001",
            "environment": "SIT"
            # Missing service_name and error_message
        }
        
        response = client.post("/webhooks/ado", json=payload)
        assert response.status_code == 422
    
    @patch("src.api.webhooks.workflow.resume_workflow")
    def test_jira_webhook_approval(self, mock_resume_workflow):
        """Test Jira webhook for approval."""
        mock_resume_workflow.return_value = {
            "status": "COMPLETED",
            "thread_id": "ADO-12345"
        }
        
        payload = {
            "thread_id": "ADO-12345",
            "approved": True,
            "issue_key": "SRE-1042"
        }
        
        headers = {
            "X-Jira-Secret": "test-secret"
        }
        
        # Mock webhook secret validation
        with patch("src.api.webhooks.settings.JIRA_WEBHOOK_SECRET") as mock_secret:
            mock_secret.get_secret_value.return_value = "test-secret"
            response = client.post("/webhooks/jira", json=payload, headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
        assert data["thread_id"] == "ADO-12345"
        
        # Verify resume was called with correct parameters
        mock_resume_workflow.assert_called_with("ADO-12345", True, {"jira_data": payload})
    
    @patch("src.api.webhooks.workflow.resume_workflow")
    def test_jira_webhook_rejection(self, mock_resume_workflow):
        """Test Jira webhook for rejection."""
        mock_resume_workflow.return_value = {
            "status": "FAILED",
            "thread_id": "ADO-12345"
        }
        
        payload = {
            "thread_id": "ADO-12345",
            "approved": False,
            "issue_key": "SRE-1042"
        }
        
        headers = {
            "X-Jira-Secret": "test-secret"
        }
        
        with patch("src.api.webhooks.settings.JIRA_WEBHOOK_SECRET") as mock_secret:
            mock_secret.get_secret_value.return_value = "test-secret"
            response = client.post("/webhooks/jira", json=payload, headers=headers)
        
        assert response.status_code == 200
        mock_resume_workflow.assert_called_with("ADO-12345", False, {"jira_data": payload})
    
    def test_jira_webhook_invalid_secret(self):
        """Test Jira webhook with invalid secret."""
        payload = {"thread_id": "ADO-12345", "approved": True}
        
        headers = {
            "X-Jira-Secret": "wrong-secret"
        }
        
        with patch("src.api.webhooks.settings.JIRA_WEBHOOK_SECRET") as mock_secret:
            mock_secret.get_secret_value.return_value = "correct-secret"
            response = client.post("/webhooks/jira", json=payload, headers=headers)
        
        assert response.status_code == 401
    
    def test_workflow_status_endpoint(self):
        """Test workflow status endpoint."""
        with patch("src.api.webhooks.workflow.get_state", new_callable=AsyncMock) as mock_get_state:
            mock_get_state.return_value = {
                "values": {
                    "final_status": "WAITING_ON_HUMAN",
                    "jira_ticket_id": "SRE-1042",
                    "human_approved": False
                },
                "next": ["execute_remediation"],
                "config": {}
            }
            
            response = client.get("/status/ADO-12345")
            assert response.status_code == 200
            data = response.json()
            assert data["thread_id"] == "ADO-12345"
            assert data["status"] == "WAITING_ON_HUMAN"
            assert data["jira_ticket_id"] == "SRE-1042"
            assert data["human_approved"] is False
    
    def test_workflow_status_not_found(self):
        """Test workflow status endpoint for non-existent workflow."""
        with patch("src.api.webhooks.workflow.get_state", new_callable=AsyncMock) as mock_get_state:
            mock_get_state.return_value = None
            
            response = client.get("/status/UNKNOWN-123")
            assert response.status_code == 404
    
    def test_metrics_endpoint(self):
        """Test metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "alerts_processed" in data
        assert "agent_confidence" in data
        assert "workflow_status" in data
        assert "uptime" in data
    
    @patch("src.api.webhooks.workflow.start_workflow")
    def test_duplicate_alert_handling(self, mock_start_workflow):
        """Test duplicate alert handling."""
        # First request
        payload = {
            "alert_id": "DUPLICATE-001",
            "environment": "SIT",
            "service_name": "auth-service",
            "error_message": "Test error message"
        }
        
        response1 = client.post("/webhooks/ado", json=payload)
        assert response1.status_code == 200
        
        # Second identical request
        response2 = client.post("/webhooks/ado", json=payload)
        assert response2.status_code == 200
        data = response2.json()
        # Should be filtered as duplicate
        assert data["status"] == "filtered"
    
    @patch("src.api.webhooks.workflow.start_workflow")
    def test_rate_limiting(self, mock_start_workflow):
        """Test rate limiting."""
        # Make many requests quickly
        payload = {
            "alert_id": "RATE-001",
            "environment": "SIT",
            "service_name": "test-service",
            "error_message": "Test error message"
        }
        
        # Reset rate limiter state
        from src.api.webhooks import rate_limiter
        rate_limiter._requests.clear()
        
        # Set rate limit to 5 requests
        with patch("src.api.webhooks.settings.RATE_LIMIT_REQUESTS", 5):
            with patch("src.api.webhooks.settings.RATE_LIMIT_PERIOD", 60):
                for i in range(6):
                    response = client.post("/webhooks/ado", json=payload)
                    if i < 5:
                        assert response.status_code == 200
                    else:
                        # 6th request should be rate limited
                        assert response.status_code == 429