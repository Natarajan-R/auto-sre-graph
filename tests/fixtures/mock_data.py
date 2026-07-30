# tests/fixtures/mock_data.py
from typing import Dict, Any, List, Optional
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import datetime
import json
from src.models.schemas import PipelineAlert, DiagnosticAnalysis, JiraTicketDraft
from tests.fixtures.sample_alerts import SampleAlerts

class MockData:
    """Mock data for testing."""
    
    @staticmethod
    def get_mock_jira_ticket() -> Dict[str, Any]:
        """Get a mock Jira ticket."""
        return {
            "id": "SRE-1042",
            "key": "SRE-1042",
            "url": "https://jira.example.com/browse/SRE-1042",
            "summary": "[AI Triage] SIT Alert: auth-service Failure",
            "description": "Root Cause: Database connection pool exhausted",
            "priority": "High",
            "status": "OPEN",
            "assignee": "john.doe@example.com",
            "created": "2024-01-15T10:30:00Z",
            "updated": "2024-01-15T10:30:00Z",
            "labels": ["auto-sre", "sit", "auth-service", "confidence-85"],
            "custom_fields": {
                "thread_id": "ADO-12345",
                "confidence_score": 0.85,
                "proposed_action": "ROLLBACK"
            }
        }
    
    @staticmethod
    def get_mock_graph_topology() -> Dict[str, Any]:
        """Get a mock graph topology."""
        return {
            "service": "auth-service",
            "upstream": ["auth-service", "user-service"],
            "downstream": ["payment-service", "order-service", "notification-service"],
            "dependencies": ["auth-service", "user-service", "payment-service", "order-service", "notification-service"],
            "dependency_graph": {
                "nodes": [
                    {"id": "auth-service", "type": "service", "status": "degraded"},
                    {"id": "user-service", "type": "service", "status": "healthy"},
                    {"id": "payment-service", "type": "service", "status": "healthy"},
                    {"id": "order-service", "type": "service", "status": "healthy"},
                    {"id": "notification-service", "type": "service", "status": "healthy"}
                ],
                "edges": [
                    {"source": "auth-service", "target": "user-service", "type": "DEPENDS_ON"},
                    {"source": "payment-service", "target": "auth-service", "type": "DEPENDS_ON"},
                    {"source": "order-service", "target": "auth-service", "type": "DEPENDS_ON"},
                    {"source": "notification-service", "target": "auth-service", "type": "DEPENDS_ON"}
                ]
            }
        }
    
    @staticmethod
    def get_mock_vector_context() -> List[Dict[str, Any]]:
        """Get a mock vector context (historical runbooks)."""
        return [
            {
                "id": "RUN-001",
                "title": "Auth Service Connection Pool Exhaustion",
                "content": "Auth service experienced connection pool exhaustion due to long-running queries.\nResolution: Increase connection pool size and optimize slow queries.",
                "service": "auth-service",
                "created_at": "2024-01-10T15:30:00Z",
                "tags": ["database", "connection", "pool"],
                "error_patterns": ["Connection timeout", "Connection refused", "Pool exhausted"],
                "resolution": "Increased max_connections from 100 to 200 and added query timeout",
                "severity": "HIGH",
                "score": 0.89
            },
            {
                "id": "RUN-002",
                "title": "Database High CPU Due to Inefficient Queries",
                "content": "Database CPU spiked to 95% due to missing indexes on order table.\nResolution: Created indexes on order.created_at and order.customer_id.",
                "service": "order-service",
                "created_at": "2024-01-08T12:00:00Z",
                "tags": ["database", "performance", "index"],
                "error_patterns": ["CPU high", "Slow query", "Response timeout"],
                "resolution": "Created indexes on order table",
                "severity": "HIGH",
                "score": 0.78
            },
            {
                "id": "RUN-003",
                "title": "Memory Leak in Payment Gateway",
                "content": "Payment service memory usage gradually increased over 48 hours.\nResolution: Fixed memory leak in payment processing loop.",
                "service": "payment-service",
                "created_at": "2024-01-05T09:00:00Z",
                "tags": ["memory", "leak", "performance"],
                "error_patterns": ["Memory error", "Out of memory"],
                "resolution": "Fixed memory leak in processing loop",
                "severity": "HIGH",
                "score": 0.75
            }
        ]
    
    @staticmethod
    def get_mock_workflow_state() -> Dict[str, Any]:
        """Get a mock workflow state."""
        return {
            "alert": SampleAlerts.get_basic_alert().model_dump(),
            "vector_context": MockData.get_mock_vector_context(),
            "graph_topology": MockData.get_mock_graph_topology(),
            "analysis": SampleDiagnosticAnalysis.get_high_confidence_analysis(),
            "jira_ticket_id": "SRE-1042",
            "human_approved": False,
            "final_status": "WAITING_ON_HUMAN",
            "error_count": 0,
            "error_messages": []
        }
    
    @staticmethod
    def get_mock_ado_webhook_payload() -> Dict[str, Any]:
        """Get a mock ADO webhook payload."""
        return {
            "eventType": "pipelineRunCompleted",
            "resource": {
                "runId": "12345",
                "runNumber": "42",
                "name": "deploy-auth-service",
                "status": "failed",
                "result": "failed",
                "createdDate": "2024-01-15T10:30:00Z",
                "finishedDate": "2024-01-15T10:35:00Z",
                "environment": "SIT",
                "service": "auth-service",
                "errorMessage": "Connection timeout to database: Connection refused",
                "stackTrace": "Traceback (most recent call last):\n  File \"/app/auth/service.py\", line 45, in connect_db\n    conn = psycopg2.connect(host='db.example.com')\n  File \"/app/auth/database.py\", line 89, in __init__\n    raise ConnectionError(\"Database connection refused\")\nConnectionError: Database connection refused",
                "commitHash": "abc123def456",
                "version": "v1.2.3",
                "severity": "HIGH",
                "pipelineId": "123",
                "buildId": "456"
            }
        }
    
    @staticmethod
    def get_mock_jira_webhook_payload(approved: bool = True) -> Dict[str, Any]:
        """Get a mock Jira webhook payload."""
        return {
            "event": "jira:issue_updated",
            "issue": {
                "key": "SRE-1042",
                "fields": {
                    "summary": "[AI Triage] SIT Alert: auth-service Failure",
                    "status": {
                        "name": "Approved" if approved else "Rejected"
                    },
                    "priority": {
                        "name": "High"
                    },
                    "description": "Root Cause: Database connection pool exhausted\n\nThread ID: ADO-12345\nConfidence Score: 0.85\nProposed Action: ROLLBACK"
                }
            },
            "user": {
                "displayName": "John Doe",
                "email": "john.doe@example.com"
            },
            "timestamp": "2024-01-15T11:00:00Z"
        }
    
    @staticmethod
    def get_mock_env_vars() -> Dict[str, str]:
        """Get mock environment variables for testing."""
        return {
            "ENVIRONMENT": "DEV",
            "LOG_LEVEL": "DEBUG",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DATABASE": "test_sre_workflows",
            "POSTGRES_USER": "test_user",
            "POSTGRES_PASSWORD": "test_password",
            "NEO4J_HOST": "localhost",
            "NEO4J_PORT": "7687",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": "test_password",
            "QDRANT_HOST": "localhost",
            "QDRANT_PORT": "6333",
            "OPENAI_API_KEY": "test-openai-key",
            "JIRA_URL": "https://test-jira.atlassian.net",
            "JIRA_USERNAME": "test-user",
            "JIRA_API_TOKEN": "test-jira-token"
        }

class MockClients:
    """Mock clients for testing."""
    
    @staticmethod
    def get_mock_qdrant_client():
        """Get a mock Qdrant client."""
        client = Mock()
        
        # Mock search method
        search_result = Mock()
        search_result.id = "test-id"
        search_result.score = 0.89
        search_result.payload = {
            "title": "Test Runbook",
            "content": "Test content",
            "service": "auth-service"
        }
        
        client.search = AsyncMock(return_value=[search_result])
        client.upsert = AsyncMock(return_value=None)
        client.delete = AsyncMock(return_value=None)
        client.retrieve = AsyncMock(return_value=[search_result])
        client.close = AsyncMock(return_value=None)
        
        return client
    
    @staticmethod
    def get_mock_neo4j_client():
        """Get a mock Neo4j client."""
        client = Mock()
        
        # Mock session as async context manager
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.run = AsyncMock()
        session.close = AsyncMock()
        
        # Mock query results
        result = AsyncMock()
        result.single = AsyncMock(return_value={
            "service": "auth-service",
            "all_services": [["auth-service", "user-service", "payment-service"]],
            "all_relations": [["DEPENDS_ON"]]
        })
        result.data = AsyncMock(return_value=[
            {"impacted_service": "payment-service"},
            {"impacted_service": "order-service"}
        ])
        
        session.run.return_value = result
        client.session = MagicMock(return_value=session)
        client.close = AsyncMock(return_value=None)
        
        return client
    
    @staticmethod
    def get_mock_jira_client():
        """Get a mock Jira client."""
        client = Mock()
        
        # Mock create_issue
        issue = Mock()
        issue.key = "SRE-1042"
        issue.fields = Mock()
        issue.fields.summary = "Test ticket"
        issue.fields.priority = Mock()
        issue.fields.priority.name = "High"
        issue.fields.status = Mock()
        issue.fields.status.name = "Open"
        
        client.create_issue = Mock(return_value=issue)
        client.issue = Mock(return_value=issue)
        client.transitions = Mock(return_value=[
            {"id": "11", "name": "In Progress"},
            {"id": "21", "name": "Resolved"},
            {"id": "31", "name": "Closed"}
        ])
        client.transition_issue = Mock(return_value=None)
        client.assign_issue = Mock(return_value=None)
        client.add_comment = Mock(return_value=None)
        
        return client
    
    @staticmethod
    def get_mock_llm_client():
        """Get a mock LLM client."""
        client = Mock()
        
        # Mock completion
        def mock_completion(*args, **kwargs):
            return {
                "choices": [{
                    "message": {
                        "content": json.dumps(SampleDiagnosticAnalysis.get_high_confidence_analysis())
                    }
                }],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150
                }
            }
        
        client.create = Mock(side_effect=mock_completion)
        client.embedding = AsyncMock(return_value={
            "data": [{"embedding": [0.1] * 1536}]
        })
        
        return client
    
    @staticmethod
    def get_mock_redis_client():
        """Get a mock Redis client."""
        client = Mock()
        client.get = Mock(return_value=None)
        client.setex = Mock(return_value=True)
        client.incr = Mock(return_value=1)
        client.expire = Mock(return_value=True)
        client.delete = Mock(return_value=1)
        client.keys = Mock(return_value=["test_key_1", "test_key_2"])
        
        return client
    
    @staticmethod
    def get_mock_aiohttp_session():
        """Get a mock aiohttp session."""
        session = AsyncMock()
        
        # Mock response
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(return_value={"id": "test-id"})
        response.text = AsyncMock(return_value="Success")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        
        session.get = AsyncMock(return_value=response)
        session.post = AsyncMock(return_value=response)
        session.patch = AsyncMock(return_value=response)
        session.delete = AsyncMock(return_value=response)
        session.close = AsyncMock(return_value=None)
        
        return session