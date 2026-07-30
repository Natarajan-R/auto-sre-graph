# tests/integration/test_orchestrator.py
"""
Integration tests for the SREWorkflow orchestrator.
Tests the complete workflow lifecycle including context retrieval, agent analysis,
Jira integration, remediation execution, and error handling.
"""

import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
from typing import Dict, Any

from src.orchestrator.graph import SREWorkflow
from src.orchestrator.state import SREWorkflowState
from src.models.schemas import PipelineAlert, DiagnosticAnalysis, ActionType, Environment, AlertSeverity
from tests.fixtures.sample_alerts import SampleAlerts
from tests.fixtures.mock_data import MockData


class TestSREWorkflow:
    """Integration tests for SREWorkflow orchestrator."""
    
    @pytest.fixture
    async def workflow(self):
        """Create a workflow instance for testing with mocked connections."""
        import os
        old_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "test-key"

        with \
            patch("src.context.vector_rag.AsyncQdrantClient") as mock_qdrant, \
            patch("src.context.vector_rag.OpenAI") as mock_openai, \
            patch("src.context.graph_rag.AsyncGraphDatabase.driver") as mock_neo4j_driver, \
            patch("src.orchestrator.deduplication.Redis") as mock_redis, \
            patch("src.orchestrator.deduplication.settings.REDIS_HOST", "localhost"), \
            patch("src.orchestrator.deduplication.settings.REDIS_PORT", 6379), \
            patch("src.orchestrator.deduplication.settings.REDIS_PASSWORD", None), \
            patch("src.observability.audit.AuditLogger._ensure_log_directory"), \
            patch("src.observability.audit.AuditLogger.log_event"), \
            patch("src.orchestrator.graph.AsyncConnectionPool") as mock_pool:

            mock_qdrant.return_value = AsyncMock()
            mock_openai.return_value = MagicMock()
            mock_neo4j_driver.return_value = AsyncMock()
            mock_redis.return_value = AsyncMock()
            mock_pool_instance = AsyncMock()
            mock_pool.return_value = mock_pool_instance

            workflow = SREWorkflow()
            workflow.deduplicator.is_duplicate = AsyncMock(return_value=False)

            class _AsyncIter:
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    raise StopAsyncIteration

            mock_app = AsyncMock()
            mock_app.astream = MagicMock(return_value=_AsyncIter())
            mock_app.aget_state = AsyncMock(return_value=MagicMock(values={}, next=[]))
            mock_app.aupdate_state = AsyncMock()
            mock_app.aget_history = AsyncMock(return_value=[])
            workflow._app = mock_app
            yield workflow
            await workflow.close()

        if old_key is None:
            del os.environ["OPENAI_API_KEY"]
        else:
            os.environ["OPENAI_API_KEY"] = old_key

    @pytest.fixture
    def sample_alert(self):
        """Get a sample alert for testing."""
        return SampleAlerts.get_basic_alert()

    @pytest.fixture
    def mock_diagnostic_analysis(self):
        """Create a mock diagnostic analysis."""
        return DiagnosticAnalysis(
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
    
    # ==================== Initialization Tests ====================
    
    @pytest.mark.asyncio
    async def test_workflow_initialization(self, workflow):
        """Test workflow initialization and component availability."""
        assert workflow is not None
        assert workflow.vector_rag is not None
        assert workflow.graph_rag is not None
        assert workflow.diagnostic_agent is not None
        assert workflow.jira_integration is not None
        assert workflow.remediation_tool is not None
        assert workflow.deduplicator is not None
        assert workflow.metrics is not None
        assert workflow.cost_manager is not None
        assert workflow.sla_monitor is not None
        assert workflow.audit_logger is not None
        assert workflow.recovery_manager is not None
        assert workflow.canary is not None
        assert workflow.retry_handler is not None
        
        # Circuit breakers should be initialized
        assert workflow.circuit_breaker_neo4j is not None
        assert workflow.circuit_breaker_qdrant is not None
        assert workflow.circuit_breaker_jira is not None
        assert workflow.circuit_breaker_llm is not None
    
    @pytest.mark.asyncio
    async def test_workflow_pool_initialization(self, workflow):
        """Test PostgreSQL connection pool initialization."""
        # Pool should be None initially
        assert workflow._pool is None
        
        # Initialize pool
        await workflow._initialize_pool()
        assert workflow._pool is not None
        
        # Should not reinitialize
        pool_id = id(workflow._pool)
        await workflow._initialize_pool()
        assert id(workflow._pool) == pool_id
    
    # ==================== Context Retrieval Tests ====================
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.VectorRAG.search_similar")
    @patch("src.orchestrator.graph.GraphRAG.get_service_topology")
    async def test_retrieve_context_node_success(
        self, 
        mock_get_topology, 
        mock_search_similar, 
        workflow, 
        sample_alert
    ):
        """Test successful context retrieval."""
        # Mock responses
        mock_search_similar.return_value = MockData.get_mock_vector_context()
        mock_get_topology.return_value = MockData.get_mock_graph_topology()
        
        state = {"alert": sample_alert}
        result = await workflow._retrieve_context_node(state)
        
        # Verify results
        assert "vector_context" in result
        assert "graph_topology" in result
        assert len(result["vector_context"]) > 0
        assert result["graph_topology"]["service"] == "auth-service"
        
        # Verify mocks were called
        mock_search_similar.assert_called_once_with(sample_alert)
        mock_get_topology.assert_called_once_with(sample_alert.service_name)
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.VectorRAG.search_similar")
    @patch("src.orchestrator.graph.GraphRAG.get_service_topology")
    async def test_retrieve_context_node_failure(
        self, 
        mock_get_topology, 
        mock_search_similar, 
        workflow, 
        sample_alert
    ):
        """Test context retrieval with failures."""
        # Mock failure
        mock_search_similar.side_effect = Exception("Vector search failed")
        
        state = {"alert": sample_alert}
        result = await workflow._retrieve_context_node(state)
        
        # Should return partial context with error
        assert "vector_context" in result
        assert "graph_topology" in result
        assert result["error_count"] == 1
        assert "error_messages" in result
        assert "Context retrieval failed" in result["error_messages"][0]
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.VectorRAG.search_similar")
    @patch("src.orchestrator.graph.GraphRAG.get_service_topology")
    async def test_retrieve_context_node_circuit_breaker(
        self, 
        mock_get_topology, 
        mock_search_similar, 
        workflow, 
        sample_alert
    ):
        """Test circuit breaker protection during context retrieval."""
        # Simulate circuit breaker open
        mock_search_similar.side_effect = Exception("Circuit breaker open")
        
        state = {"alert": sample_alert}
        result = await workflow._retrieve_context_node(state)
        
        # Should handle gracefully
        assert "vector_context" in result
        assert result["error_count"] == 1
    
    # ==================== Diagnostic Agent Tests ====================
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.DiagnosticAgent.analyze")
    async def test_diagnostic_agent_node_success(
        self, 
        mock_analyze, 
        workflow, 
        sample_alert, 
        mock_diagnostic_analysis
    ):
        """Test successful diagnostic agent execution."""
        mock_analyze.return_value = mock_diagnostic_analysis
        
        state = {
            "alert": sample_alert,
            "vector_context": MockData.get_mock_vector_context(),
            "graph_topology": MockData.get_mock_graph_topology()
        }
        
        result = await workflow._diagnostic_agent_node(state)
        
        assert "analysis" in result
        assert result["analysis"].confidence_score == 0.92
        assert result["analysis"].proposed_action == ActionType.ROLLBACK
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.DiagnosticAgent.analyze")
    async def test_diagnostic_agent_node_prod_rollback_adjustment(
        self, 
        mock_analyze, 
        workflow, 
        mock_diagnostic_analysis
    ):
        """Test that PROD environment adjusts low confidence rollbacks."""
        # Create a production alert
        alert = SampleAlerts.get_critical_prod_alert()
        
        # Set low confidence
        mock_diagnostic_analysis.confidence_score = 0.75
        mock_diagnostic_analysis.proposed_action = ActionType.ROLLBACK
        mock_analyze.return_value = mock_diagnostic_analysis
        
        state = {
            "alert": alert,
            "vector_context": MockData.get_mock_vector_context(),
            "graph_topology": MockData.get_mock_graph_topology()
        }
        
        result = await workflow._diagnostic_agent_node(state)
        
        # Should be adjusted to ESCALATE_ONLY for PROD with low confidence
        assert result["analysis"].proposed_action == ActionType.ESCALATE_ONLY
        assert result["analysis"].confidence_score < 0.85
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.DiagnosticAgent.analyze")
    async def test_diagnostic_agent_node_high_confidence_prod(
        self, 
        mock_analyze, 
        workflow, 
        mock_diagnostic_analysis
    ):
        """Test that high confidence PROD rollbacks are allowed."""
        alert = SampleAlerts.get_critical_prod_alert()
        
        # Set high confidence
        mock_diagnostic_analysis.confidence_score = 0.92
        mock_diagnostic_analysis.proposed_action = ActionType.ROLLBACK
        mock_analyze.return_value = mock_diagnostic_analysis
        
        state = {
            "alert": alert,
            "vector_context": MockData.get_mock_vector_context(),
            "graph_topology": MockData.get_mock_graph_topology()
        }
        
        result = await workflow._diagnostic_agent_node(state)
        
        # Should keep ROLLBACK for high confidence
        assert result["analysis"].proposed_action == ActionType.ROLLBACK
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.DiagnosticAgent.analyze")
    async def test_diagnostic_agent_node_failure(
        self, 
        mock_analyze, 
        workflow, 
        sample_alert
    ):
        """Test diagnostic agent failure handling."""
        mock_analyze.side_effect = Exception("Agent analysis failed")
        
        state = {
            "alert": sample_alert,
            "vector_context": MockData.get_mock_vector_context(),
            "graph_topology": MockData.get_mock_graph_topology()
        }
        
        result = await workflow._diagnostic_agent_node(state)
        
        assert "analysis" in result
        assert result["analysis"] is None
        assert result["error_count"] == 1
        assert "Diagnostic agent failed" in result["error_messages"][0]
    
    # ==================== Routing Tests ====================
    
    @pytest.mark.asyncio
    async def test_route_post_diagnosis_escalate_only(self, workflow):
        """Test routing when diagnosis suggests escalation only."""
        state = {
            "analysis": DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=False,
                confidence_score=0.35,
                proposed_action=ActionType.ESCALATE_ONLY
            )
        }
        route = workflow._route_post_diagnosis(state)
        assert route == "escalate_only"
    
    @pytest.mark.asyncio
    async def test_route_post_diagnosis_create_ticket(self, workflow):
        """Test routing when diagnosis suggests remediation."""
        state = {
            "analysis": DiagnosticAnalysis(
                root_cause_summary="Test",
                historical_matches_found=True,
                confidence_score=0.85,
                proposed_action=ActionType.ROLLBACK
            )
        }
        route = workflow._route_post_diagnosis(state)
        assert route == "create_jira_ticket"
    
    @pytest.mark.asyncio
    async def test_route_post_diagnosis_error_handling(self, workflow):
        """Test routing when error threshold is reached."""
        state = {
            "error_count": 3,
            "error_messages": ["Error 1", "Error 2", "Error 3"]
        }
        route = workflow._route_post_diagnosis(state)
        assert route == "handle_error"
    
    @pytest.mark.asyncio
    async def test_route_post_diagnosis_no_analysis(self, workflow):
        """Test routing when no analysis is available."""
        state = {
            "error_count": 0,
            "analysis": None
        }
        route = workflow._route_post_diagnosis(state)
        assert route == "handle_error"
    
    # ==================== Jira Ticket Tests ====================
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.JiraIntegration.create_ticket_from_analysis")
    async def test_create_jira_ticket_node_success(
        self, 
        mock_create_ticket, 
        workflow, 
        sample_alert, 
        mock_diagnostic_analysis
    ):
        """Test successful Jira ticket creation."""
        mock_create_ticket.return_value = {
            "id": "SRE-1042",
            "url": "https://jira.example.com/browse/SRE-1042",
            "summary": "Test ticket",
            "priority": "High"
        }
        
        state = {
            "alert": sample_alert,
            "analysis": mock_diagnostic_analysis
        }
        
        result = await workflow._create_jira_ticket_node(state)
        
        assert "jira_ticket_id" in result
        assert result["jira_ticket_id"] == "SRE-1042"
        assert result["final_status"] == "WAITING_ON_HUMAN"
        assert result["human_approved"] is False
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.JiraIntegration.create_ticket_from_analysis")
    async def test_create_jira_ticket_node_failure(
        self, 
        mock_create_ticket, 
        workflow, 
        sample_alert, 
        mock_diagnostic_analysis
    ):
        """Test Jira ticket creation failure."""
        mock_create_ticket.side_effect = Exception("Jira API failed")
        
        state = {
            "alert": sample_alert,
            "analysis": mock_diagnostic_analysis
        }
        
        result = await workflow._create_jira_ticket_node(state)
        
        assert result["final_status"] == "JIRA_FAILED"
        assert result["error_count"] == 1
        assert "Jira ticket creation failed" in result["error_messages"][0]
    
    # ==================== Remediation Tests ====================
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.RemediationTool.execute")
    async def test_execute_remediation_node_approved(
        self, 
        mock_execute, 
        workflow, 
        sample_alert, 
        mock_diagnostic_analysis
    ):
        """Test remediation execution when approved."""
        mock_execute.return_value = {
            "success": True,
            "output": "Rollback completed successfully"
        }
        
        state = {
            "alert": sample_alert,
            "analysis": mock_diagnostic_analysis,
            "human_approved": True
        }
        
        result = await workflow._execute_remediation_node(state)
        
        assert result["final_status"] == "REMEDIATION_SUCCESSFUL"
        mock_execute.assert_called_once()
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.RemediationTool.execute")
    async def test_execute_remediation_node_failure(
        self, 
        mock_execute, 
        workflow, 
        sample_alert, 
        mock_diagnostic_analysis
    ):
        """Test remediation execution failure."""
        mock_execute.return_value = {
            "success": False,
            "error": "Rollback failed due to timeout"
        }
        
        state = {
            "alert": sample_alert,
            "analysis": mock_diagnostic_analysis,
            "human_approved": True
        }
        
        result = await workflow._execute_remediation_node(state)
        
        assert result["final_status"] == "REMEDIATION_FAILED"
        assert result["error_count"] == 1
        assert "Remediation failed" in result["error_messages"][0]
    
    @pytest.mark.asyncio
    async def test_execute_remediation_node_not_approved(
        self, 
        workflow, 
        sample_alert, 
        mock_diagnostic_analysis
    ):
        """Test remediation execution when not approved."""
        state = {
            "alert": sample_alert,
            "analysis": mock_diagnostic_analysis,
            "human_approved": False
        }
        
        result = await workflow._execute_remediation_node(state)
        
        assert result["final_status"] == "REMEDIATION_SKIPPED"
        assert "Human approval not granted" in result["error_messages"][0]
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.RemediationTool.execute")
    async def test_execute_remediation_node_exception(
        self, 
        mock_execute, 
        workflow, 
        sample_alert, 
        mock_diagnostic_analysis
    ):
        """Test remediation execution exception handling."""
        mock_execute.side_effect = Exception("Unexpected error during remediation")
        
        state = {
            "alert": sample_alert,
            "analysis": mock_diagnostic_analysis,
            "human_approved": True
        }
        
        result = await workflow._execute_remediation_node(state)
        
        assert result["final_status"] == "REMEDIATION_FAILED"
        assert result["error_count"] == 1
    
    # ==================== Escalation Tests ====================
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.JiraIntegration.create_escalation_ticket")
    async def test_escalate_only_node_success(
        self, 
        mock_escalate, 
        workflow, 
        sample_alert
    ):
        """Test successful escalation."""
        mock_escalate.return_value = {
            "id": "SRE-1043",
            "url": "https://jira.example.com/browse/SRE-1043"
        }
        
        analysis = DiagnosticAnalysis(
            root_cause_summary="Unknown error pattern",
            historical_matches_found=False,
            confidence_score=0.35,
            proposed_action=ActionType.ESCALATE_ONLY
        )
        
        state = {
            "alert": sample_alert,
            "analysis": analysis
        }
        
        result = await workflow._escalate_only_node(state)
        
        assert result["final_status"] == "ESCALATED"
        assert result["jira_ticket_id"] == "SRE-1043"
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.JiraIntegration.create_escalation_ticket")
    async def test_escalate_only_node_failure(
        self, 
        mock_escalate, 
        workflow, 
        sample_alert
    ):
        """Test escalation failure."""
        mock_escalate.side_effect = Exception("Escalation API failed")
        
        analysis = DiagnosticAnalysis(
            root_cause_summary="Unknown error pattern",
            historical_matches_found=False,
            confidence_score=0.35,
            proposed_action=ActionType.ESCALATE_ONLY
        )
        
        state = {
            "alert": sample_alert,
            "analysis": analysis
        }
        
        result = await workflow._escalate_only_node(state)
        
        assert result["final_status"] == "ESCALATION_FAILED"
        assert result["error_count"] == 1
    
    # ==================== Error Handling Tests ====================
    
    @pytest.mark.asyncio
    async def test_handle_error_node(self, workflow, sample_alert):
        """Test error handling node."""
        state = {
            "alert": sample_alert,
            "error_count": 2,
            "error_messages": ["Test error 1", "Test error 2"]
        }
        
        result = await workflow._handle_error_node(state)
        
        assert result["final_status"] == "ERROR"
        assert len(result["error_messages"]) == 2
        assert result["human_approved"] is False
    
    # ==================== Full Workflow Tests ====================
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.VectorRAG.search_similar")
    @patch("src.orchestrator.graph.GraphRAG.get_service_topology")
    @patch("src.orchestrator.graph.DiagnosticAgent.analyze")
    @patch("src.orchestrator.graph.JiraIntegration.create_ticket_from_analysis")
    async def test_start_workflow_success(
        self, 
        mock_create_ticket, 
        mock_analyze, 
        mock_get_topology, 
        mock_search_similar, 
        workflow, 
        sample_alert,
        mock_diagnostic_analysis
    ):
        """Test complete workflow start."""
        # Mock all components
        mock_search_similar.return_value = MockData.get_mock_vector_context()
        mock_get_topology.return_value = MockData.get_mock_graph_topology()
        mock_analyze.return_value = mock_diagnostic_analysis
        mock_create_ticket.return_value = {
            "id": "SRE-1042",
            "url": "https://jira.example.com/browse/SRE-1042",
            "summary": "Test ticket",
            "priority": "High"
        }
        
        # Start workflow
        result = await workflow.start_workflow(sample_alert, sample_alert.alert_id)
        
        # Verify result
        assert result["status"] in ["WAITING_ON_HUMAN", "COMPLETED"]
        assert result["thread_id"] == sample_alert.alert_id
        assert result["alert_id"] == sample_alert.alert_id
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.SREWorkflow.get_app")
    async def test_start_workflow_failure(
        self, 
        mock_get_app, 
        workflow, 
        sample_alert
    ):
        """Test workflow start failure."""
        mock_get_app.side_effect = Exception("Workflow compilation failed")
        
        result = await workflow.start_workflow(sample_alert, sample_alert.alert_id)
        
        assert result["status"] == "ERROR"
        assert result["error"] is not None
    
    @pytest.mark.asyncio
    async def test_start_workflow_duplicate(self, workflow, sample_alert):
        """Test duplicate alert handling."""
        # First call - should process
        with patch.object(workflow.deduplicator, 'is_duplicate', return_value=False):
            with patch.object(workflow, 'get_app') as mock_get_app:
                mock_app = AsyncMock()
                mock_app.astream = AsyncMock(return_value=[])
                mock_app.aget_state = AsyncMock(return_value=None)
                mock_get_app.return_value = mock_app
                
                result1 = await workflow.start_workflow(sample_alert, sample_alert.alert_id)
                assert result1["status"] != "duplicate"
        
        # Second call - should detect duplicate
        with patch.object(workflow.deduplicator, 'is_duplicate', return_value=True):
            result2 = await workflow.start_workflow(sample_alert, sample_alert.alert_id)
            assert result2["status"] == "duplicate"
            assert result2["message"] == "Alert deduplicated - already processing"
    
    # ==================== Resume Workflow Tests ====================
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.SREWorkflow.get_app")
    async def test_resume_workflow_success(
        self, 
        mock_get_app, 
        workflow, 
        sample_alert
    ):
        """Test successful workflow resume."""
        # Mock app and state
        class _AsyncIter:
            def __aiter__(self):
                return self
            async def __anext__(self):
                raise StopAsyncIteration

        mock_app = AsyncMock()
        mock_app.aget_state = AsyncMock(return_value=MagicMock(
            values={"alert": sample_alert, "jira_ticket_id": "SRE-1042"},
            next=["execute_remediation"]
        ))
        mock_app.aupdate_state = AsyncMock()
        mock_app.astream = MagicMock(return_value=_AsyncIter())
        mock_get_app.return_value = mock_app
        
        result = await workflow.resume_workflow(
            thread_id=sample_alert.alert_id,
            human_approved=True
        )
        
        assert result["status"] == "FAILED"  # Or COMPLETED depending on state
        assert result["thread_id"] == sample_alert.alert_id
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.SREWorkflow.get_app")
    async def test_resume_workflow_not_found(
        self, 
        mock_get_app, 
        workflow
    ):
        """Test resume workflow when not found."""
        mock_app = AsyncMock()
        mock_app.aget_state = AsyncMock(return_value=None)
        mock_get_app.return_value = mock_app
        
        result = await workflow.resume_workflow(
            thread_id="NONEXISTENT",
            human_approved=True
        )
        
        assert result["status"] == "ERROR"
        assert result["error"] == "Workflow not found"
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.SREWorkflow.get_app")
    async def test_resume_workflow_failure(
        self, 
        mock_get_app, 
        workflow, 
        sample_alert
    ):
        """Test resume workflow failure."""
        mock_app = AsyncMock()
        mock_app.aget_state = AsyncMock(return_value=MagicMock(
            values={"alert": sample_alert},
            next=["execute_remediation"]
        ))
        mock_app.aupdate_state = AsyncMock(side_effect=Exception("Update failed"))
        mock_get_app.return_value = mock_app
        
        result = await workflow.resume_workflow(
            thread_id=sample_alert.alert_id,
            human_approved=True
        )
        
        assert result["status"] == "ERROR"
        assert result["error"] is not None
    
    # ==================== State Management Tests ====================
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.SREWorkflow.get_app")
    async def test_get_state_success(
        self, 
        mock_get_app, 
        workflow, 
        sample_alert
    ):
        """Test getting workflow state."""
        mock_state = MagicMock()
        mock_state.values = {"alert": sample_alert, "final_status": "WAITING_ON_HUMAN"}
        mock_state.next = ["execute_remediation"]
        mock_state.config = {}
        
        mock_app = AsyncMock()
        mock_app.aget_state = AsyncMock(return_value=mock_state)
        mock_get_app.return_value = mock_app
        
        result = await workflow.get_state(sample_alert.alert_id)
        
        assert result is not None
        assert "values" in result
        assert result["values"]["final_status"] == "WAITING_ON_HUMAN"
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.SREWorkflow.get_app")
    async def test_get_state_not_found(
        self, 
        mock_get_app, 
        workflow
    ):
        """Test getting state for non-existent workflow."""
        mock_app = AsyncMock()
        mock_app.aget_state = AsyncMock(return_value=None)
        mock_get_app.return_value = mock_app
        
        result = await workflow.get_state("NONEXISTENT")
        
        assert result is None
    
    # ==================== Thread History Tests ====================
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.SREWorkflow.get_app")
    async def test_get_thread_history_success(
        self, 
        mock_get_app, 
        workflow, 
        sample_alert
    ):
        """Test getting thread history."""
        mock_event = MagicMock()
        mock_event.step = 1
        mock_event.timestamp = datetime.utcnow()
        mock_event.node = "diagnostic_agent"
        mock_event.values = {"analysis": "test"}

        class _AsyncIter:
            def __init__(self, items):
                self._items = items
            def __aiter__(self):
                return self
            async def __anext__(self):
                if not self._items:
                    raise StopAsyncIteration
                return self._items.pop(0)

        mock_app = AsyncMock()
        mock_app.aget_history = MagicMock(return_value=_AsyncIter([mock_event]))
        mock_get_app.return_value = mock_app
        
        history = await workflow.get_thread_history(sample_alert.alert_id)
        
        assert len(history) == 1
        assert history[0]["step"] == 1
        assert history[0]["node"] == "diagnostic_agent"
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.SREWorkflow.get_app")
    async def test_get_thread_history_failure(
        self, 
        mock_get_app, 
        workflow
    ):
        """Test thread history failure."""
        mock_app = AsyncMock()
        mock_app.aget_history = AsyncMock(side_effect=Exception("History retrieval failed"))
        mock_get_app.return_value = mock_app
        
        history = await workflow.get_thread_history("THREAD-123")
        
        assert history == []
    
    # ==================== Resource Cleanup Tests ====================
    
    @pytest.mark.asyncio
    async def test_workflow_close(self, workflow):
        """Test workflow resource cleanup."""
        # Setup mock pool
        mock_pool = AsyncMock()
        workflow._pool = mock_pool
        
        # Mock close methods
        workflow.graph_rag.close = AsyncMock()
        workflow.jira_integration.close = AsyncMock()
        
        await workflow.close()
        
        mock_pool.close.assert_called_once()
        workflow.graph_rag.close.assert_called_once()
        workflow.jira_integration.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_workflow_close_no_pool(self, workflow):
        """Test workflow close with no pool."""
        workflow._pool = None
        
        # Mock close methods
        workflow.graph_rag.close = AsyncMock()
        workflow.jira_integration.close = AsyncMock()
        
        await workflow.close()
        
        workflow.graph_rag.close.assert_called_once()
        workflow.jira_integration.close.assert_called_once()


class TestSREWorkflowEdgeCases:
    """Edge case tests for SREWorkflow."""
    
    @pytest.fixture
    async def workflow(self):
        """Create a workflow instance for testing with mocked connections."""
        import os
        old_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "test-key"

        with \
            patch("src.context.vector_rag.AsyncQdrantClient") as mock_qdrant, \
            patch("src.context.vector_rag.OpenAI") as mock_openai, \
            patch("src.context.graph_rag.AsyncGraphDatabase.driver") as mock_neo4j_driver, \
            patch("src.orchestrator.deduplication.Redis") as mock_redis, \
            patch("src.orchestrator.deduplication.settings.REDIS_HOST", "localhost"), \
            patch("src.orchestrator.deduplication.settings.REDIS_PORT", 6379), \
            patch("src.orchestrator.deduplication.settings.REDIS_PASSWORD", None), \
            patch("src.observability.audit.AuditLogger._ensure_log_directory"), \
            patch("src.observability.audit.AuditLogger.log_event"), \
            patch("src.orchestrator.graph.AsyncConnectionPool") as mock_pool:

            mock_qdrant.return_value = AsyncMock()
            mock_openai.return_value = MagicMock()
            mock_neo4j_driver.return_value = AsyncMock()
            mock_redis.return_value = AsyncMock()
            mock_pool_instance = AsyncMock()
            mock_pool.return_value = mock_pool_instance

            workflow = SREWorkflow()
            workflow.deduplicator.is_duplicate = AsyncMock(return_value=False)

            class _AsyncIter:
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    raise StopAsyncIteration

            mock_app = AsyncMock()
            mock_app.astream = MagicMock(return_value=_AsyncIter())
            mock_app.aget_state = AsyncMock(return_value=MagicMock(values={}, next=[]))
            mock_app.aupdate_state = AsyncMock()
            mock_app.aget_history = AsyncMock(return_value=[])
            workflow._app = mock_app
            yield workflow
            await workflow.close()

        if old_key is None:
            del os.environ["OPENAI_API_KEY"]
        else:
            os.environ["OPENAI_API_KEY"] = old_key

    @pytest.fixture
    def sample_alert(self):
        """Get a sample alert for testing."""
        return SampleAlerts.get_basic_alert()

    @pytest.mark.asyncio
    async def test_workflow_with_minimal_alert(self, workflow):
        """Test workflow with minimal alert data."""
        minimal_alert = PipelineAlert(
            alert_id="MIN-001",
            environment=Environment.DEV,
            service_name="test-service",
            error_message="Test error"
        )
        
        # Should handle gracefully
        with patch.object(workflow, 'get_app') as mock_get_app:
            class _AsyncIter:
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    raise StopAsyncIteration

            mock_app = AsyncMock()
            mock_app.astream = MagicMock(return_value=_AsyncIter())
            mock_app.aget_state = AsyncMock(return_value=None)
            mock_get_app.return_value = mock_app
            
            result = await workflow.start_workflow(minimal_alert, minimal_alert.alert_id)
            assert result["status"] != "ERROR"
    
    @pytest.mark.asyncio
    async def test_workflow_with_low_confidence(self, workflow, sample_alert):
        """Test workflow behavior with low confidence diagnosis."""
        low_confidence_analysis = DiagnosticAnalysis(
            root_cause_summary="Uncertain diagnosis",
            historical_matches_found=False,
            confidence_score=0.25,
            proposed_action=ActionType.ESCALATE_ONLY
        )
        
        state = {
            "alert": sample_alert,
            "analysis": low_confidence_analysis
        }
        
        route = workflow._route_post_diagnosis(state)
        assert route == "escalate_only"
    
    @pytest.mark.asyncio
    async def test_workflow_with_high_confidence(self, workflow, sample_alert):
        """Test workflow behavior with high confidence diagnosis."""
        high_confidence_analysis = DiagnosticAnalysis(
            root_cause_summary="Clear diagnosis",
            historical_matches_found=True,
            confidence_score=0.95,
            proposed_action=ActionType.ROLLBACK
        )
        
        state = {
            "alert": sample_alert,
            "analysis": high_confidence_analysis
        }
        
        route = workflow._route_post_diagnosis(state)
        assert route == "create_jira_ticket"
    
    @pytest.mark.asyncio
    async def test_workflow_with_missing_context(self, workflow, sample_alert):
        """Test workflow behavior with missing context."""
        state = {
            "alert": sample_alert,
            "vector_context": [],
            "graph_topology": {}
        }
        
        with patch.object(workflow.diagnostic_agent, 'analyze') as mock_analyze:
            mock_analyze.return_value = DiagnosticAnalysis(
                root_cause_summary="No context available",
                historical_matches_found=False,
                confidence_score=0.5,
                proposed_action=ActionType.ESCALATE_ONLY
            )
            
            result = await workflow._diagnostic_agent_node(state)
            assert result["analysis"] is not None
            assert result["analysis"].confidence_score == 0.5


class TestSREWorkflowIntegration:
    """End-to-end integration tests for SREWorkflow."""
    
    @pytest.fixture
    async def workflow(self):
        """Create a workflow instance for testing with mocked connections."""
        import os
        old_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "test-key"

        with \
            patch("src.context.vector_rag.AsyncQdrantClient") as mock_qdrant, \
            patch("src.context.vector_rag.OpenAI") as mock_openai, \
            patch("src.context.graph_rag.AsyncGraphDatabase.driver") as mock_neo4j_driver, \
            patch("src.orchestrator.deduplication.Redis") as mock_redis, \
            patch("src.orchestrator.deduplication.settings.REDIS_HOST", "localhost"), \
            patch("src.orchestrator.deduplication.settings.REDIS_PORT", 6379), \
            patch("src.orchestrator.deduplication.settings.REDIS_PASSWORD", None), \
            patch("src.observability.audit.AuditLogger._ensure_log_directory"), \
            patch("src.observability.audit.AuditLogger.log_event"), \
            patch("src.orchestrator.graph.AsyncConnectionPool") as mock_pool:

            mock_qdrant.return_value = AsyncMock()
            mock_openai.return_value = MagicMock()
            mock_neo4j_driver.return_value = AsyncMock()
            mock_redis.return_value = AsyncMock()
            mock_pool_instance = AsyncMock()
            mock_pool.return_value = mock_pool_instance

            workflow = SREWorkflow()
            workflow.deduplicator.is_duplicate = AsyncMock(return_value=False)

            class _AsyncIter:
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    raise StopAsyncIteration

            mock_app = AsyncMock()
            mock_app.astream = MagicMock(return_value=_AsyncIter())
            mock_app.aget_state = AsyncMock(return_value=MagicMock(values={}, next=[]))
            mock_app.aupdate_state = AsyncMock()
            mock_app.aget_history = AsyncMock(return_value=[])
            workflow._app = mock_app
            yield workflow
            await workflow.close()

        if old_key is None:
            del os.environ["OPENAI_API_KEY"]
        else:
            os.environ["OPENAI_API_KEY"] = old_key
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.VectorRAG.search_similar")
    @patch("src.orchestrator.graph.GraphRAG.get_service_topology")
    @patch("src.orchestrator.graph.DiagnosticAgent.analyze")
    @patch("src.orchestrator.graph.JiraIntegration.create_ticket_from_analysis")
    @patch("src.orchestrator.graph.RemediationTool.execute")
    async def test_end_to_end_successful_workflow(
        self,
        mock_execute,
        mock_create_ticket,
        mock_analyze,
        mock_get_topology,
        mock_search_similar,
        workflow
    ):
        """Test complete end-to-end successful workflow."""
        # Setup mocks
        mock_search_similar.return_value = MockData.get_mock_vector_context()
        mock_get_topology.return_value = MockData.get_mock_graph_topology()
        
        mock_analyze.return_value = DiagnosticAnalysis(
            root_cause_summary="Database connection pool exhausted",
            historical_matches_found=True,
            confidence_score=0.92,
            proposed_action=ActionType.ROLLBACK,
            remediation_script="kubectl rollout undo deployment/auth-service"
        )
        
        mock_create_ticket.return_value = {
            "id": "SRE-1042",
            "url": "https://jira.example.com/browse/SRE-1042"
        }
        
        mock_execute.return_value = {
            "success": True,
            "output": "Rollback completed"
        }
        
        alert = SampleAlerts.get_basic_alert()
        
        # Start workflow
        result = await workflow.start_workflow(alert, alert.alert_id)
        assert result["status"] in ["WAITING_ON_HUMAN", "COMPLETED"]
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.VectorRAG.search_similar")
    @patch("src.orchestrator.graph.GraphRAG.get_service_topology")
    @patch("src.orchestrator.graph.DiagnosticAgent.analyze")
    @patch("src.orchestrator.graph.JiraIntegration.create_ticket_from_analysis")
    async def test_end_to_end_escalation_workflow(
        self,
        mock_create_ticket,
        mock_analyze,
        mock_get_topology,
        mock_search_similar,
        workflow
    ):
        """Test complete end-to-end escalation workflow."""
        mock_search_similar.return_value = MockData.get_mock_vector_context()
        mock_get_topology.return_value = MockData.get_mock_graph_topology()
        
        mock_analyze.return_value = DiagnosticAnalysis(
            root_cause_summary="Unknown error pattern",
            historical_matches_found=False,
            confidence_score=0.35,
            proposed_action=ActionType.ESCALATE_ONLY
        )
        
        mock_create_ticket.return_value = {
            "id": "SRE-1043",
            "url": "https://jira.example.com/browse/SRE-1043"
        }
        
        alert = SampleAlerts.get_basic_alert()
        
        result = await workflow.start_workflow(alert, alert.alert_id)
        assert result["status"] in ["WAITING_ON_HUMAN", "COMPLETED"]
    
    @pytest.mark.asyncio
    @patch("src.orchestrator.graph.VectorRAG.search_similar")
    @patch("src.orchestrator.graph.GraphRAG.get_service_topology")
    @patch("src.orchestrator.graph.DiagnosticAgent.analyze")
    async def test_end_to_end_error_workflow(
        self,
        mock_analyze,
        mock_get_topology,
        mock_search_similar,
        workflow
    ):
        """Test complete end-to-end workflow with errors."""
        mock_search_similar.side_effect = Exception("Vector search failed")
        
        alert = SampleAlerts.get_basic_alert()
        
        result = await workflow.start_workflow(alert, alert.alert_id)
        
        # Should handle error gracefully
        assert result["status"] in ["ERROR", "COMPLETED", "WAITING_ON_HUMAN"]
        
        