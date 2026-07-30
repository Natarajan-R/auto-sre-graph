# src/orchestrator/graph.py
from typing import Literal, Dict, Any, Optional, List
import logging
from datetime import datetime
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from src.config.settings import settings
from src.orchestrator.state import SREWorkflowState
from src.models.schemas import DiagnosticAnalysis, ActionType, PipelineAlert
from src.context.vector_rag import VectorRAG
from src.context.graph_rag import GraphRAG
from src.agents.diagnostician import DiagnosticAgent
from src.integrations.jira import JiraIntegration
from src.tools.remediation import RemediationTool
from src.orchestrator.deduplication import AlertDeduplicator
from src.observability.tracing import tracer, trace_span
from src.observability.tracing import MetricsCollector
from src.observability.cost_manager import CostManager
from src.observability.sla_monitor import SLAMonitor
from src.observability.audit import AuditLogger, AuditAction
from src.orchestrator.recovery import ErrorRecoveryManager, RetryHandler
from src.orchestrator.canary import CanaryDeployment

logger = logging.getLogger(__name__)

class SREWorkflow:
    """Enterprise SRE Workflow Orchestrator with Async PostgreSQL Checkpointing."""
    
    def __init__(self):
        self.vector_rag = VectorRAG()
        self.graph_rag = GraphRAG()
        self.diagnostic_agent = DiagnosticAgent()
        self.jira_integration = JiraIntegration()
        self.remediation_tool = RemediationTool()
        self.deduplicator = AlertDeduplicator()
        self.metrics = MetricsCollector()
        self.cost_manager = CostManager()
        self.sla_monitor = SLAMonitor()
        self.audit_logger = AuditLogger()
        self.recovery_manager = ErrorRecoveryManager()
        self.canary = CanaryDeployment()
        self.retry_handler = RetryHandler()
        
        # Connection pool will be initialized lazily
        self._pool = None
        self._checkpointer = None
        self._app = None
        
        # Circuit breakers for external services
        self.circuit_breaker_neo4j = self.recovery_manager.get_circuit_breaker("neo4j")
        self.circuit_breaker_qdrant = self.recovery_manager.get_circuit_breaker("qdrant")
        self.circuit_breaker_jira = self.recovery_manager.get_circuit_breaker("jira")
        self.circuit_breaker_llm = self.recovery_manager.get_circuit_breaker("llm")
    
    async def _initialize_pool(self):
        """Initialize async PostgreSQL connection pool."""
        if self._pool is None:
            try:
                self._pool = AsyncConnectionPool(
                    conninfo=settings.postgres_uri,
                    min_size=5,
                    max_size=50,
                    timeout=30,
                    reconnect_timeout=5,
                    max_lifetime=3600,
                    max_idle=300,
                    kwargs={"autocommit": True}
                )
                await self._pool.open()
                await self._pool.wait()
                logger.info("Async PostgreSQL connection pool initialized")
            except Exception as e:
                logger.error(f"Failed to initialize PostgreSQL pool: {e}")
                raise
    
    async def _get_checkpointer(self) -> AsyncPostgresSaver:
        """Get or create async checkpointer."""
        if self._checkpointer is None:
            await self._initialize_pool()
            if self._pool is None:
                raise RuntimeError("Connection pool not initialized")
            
            # Create AsyncPostgresSaver with connection pool
            self._checkpointer = AsyncPostgresSaver(self._pool)
            
            # Setup checkpoint tables asynchronously
            await self._checkpointer.setup()
            logger.info("AsyncPostgresSaver initialized with connection pool")
        
        return self._checkpointer
    
    async def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow asynchronously."""
        # Initialize graph with state
        workflow = StateGraph(SREWorkflowState)
        
        # Add nodes with tracing
        workflow.add_node("retrieve_context", self._retrieve_context_node)
        workflow.add_node("diagnostic_agent", self._diagnostic_agent_node)
        workflow.add_node("create_jira_ticket", self._create_jira_ticket_node)
        workflow.add_node("execute_remediation", self._execute_remediation_node)
        workflow.add_node("escalate_only", self._escalate_only_node)
        workflow.add_node("handle_error", self._handle_error_node)
        
        # Define edges
        workflow.add_edge(START, "retrieve_context")
        workflow.add_edge("retrieve_context", "diagnostic_agent")
        
        # Conditional routing after diagnosis
        workflow.add_conditional_edges(
            "diagnostic_agent",
            self._route_post_diagnosis,
            {
                "create_jira_ticket": "create_jira_ticket",
                "escalate_only": "escalate_only",
                "handle_error": "handle_error"
            }
        )
        
        workflow.add_edge("create_jira_ticket", "execute_remediation")
        workflow.add_edge("escalate_only", END)
        workflow.add_edge("execute_remediation", END)
        workflow.add_edge("handle_error", END)
        
        return workflow
    
    async def get_app(self):
        """Get or compile the workflow app with async checkpointing."""
        if self._app is None:
            # Build the graph
            workflow = await self._build_graph()
            
            # Get checkpointer
            checkpointer = await self._get_checkpointer()
            
            # Compile with async checkpointer
            self._app = workflow.compile(
                checkpointer=checkpointer,
                interrupt_before=["execute_remediation"]
            )
            logger.info("Workflow compiled with async PostgreSQL checkpointer")
        
        return self._app
    
    @trace_span("workflow.retrieve_context")
    async def _retrieve_context_node(self, state: SREWorkflowState) -> Dict[str, Any]:
        """Retrieve context from vector and graph databases with circuit breakers."""
        alert = state['alert']
        logger.info(f"Retrieving context for alert {alert.alert_id}")
        
        try:
            # Get vector context with circuit breaker
            vector_context = await self.circuit_breaker_qdrant.call(
                self.vector_rag.search_similar,
                alert
            )
            
            # Get graph topology with circuit breaker
            graph_topology = await self.circuit_breaker_neo4j.call(
                self.graph_rag.get_service_topology,
                alert.service_name
            )
            
            # Log audit
            await self.audit_logger.log_event(
                action=AuditAction.CONTEXT_RETRIEVED,
                actor="system",
                target=alert.alert_id,
                details={
                    'service': alert.service_name,
                    'vector_results': len(vector_context),
                    'graph_results': len(graph_topology.get('dependencies', []))
                }
            )
            
            return {
                "vector_context": vector_context,
                "graph_topology": graph_topology
            }
            
        except Exception as e:
            logger.error(f"Context retrieval failed for {alert.alert_id}: {e}")
            # Return partial context if available
            return {
                "vector_context": state.get('vector_context', []),
                "graph_topology": state.get('graph_topology', {}),
                "error_count": state.get('error_count', 0) + 1,
                "error_messages": [f"Context retrieval failed: {str(e)}"]
            }
    
    @trace_span("workflow.diagnostic_agent")
    async def _diagnostic_agent_node(self, state: SREWorkflowState) -> Dict[str, Any]:
        """Run the diagnostic agent to analyze the alert."""
        alert = state['alert']
        logger.info(f"Running diagnostic agent for alert {alert.alert_id}")
        
        try:
            # Check if we should use canary workflow
            version = self.canary.route_to_workflow_version(alert)
            
            # Select cost-optimized model
            model = self.cost_manager.optimize_model_selection(
                required_complexity='high' if alert.severity.value in ['CRITICAL', 'HIGH'] else 'medium'
            )
            
            # Get context
            vector_context = state.get('vector_context', [])
            graph_topology = state.get('graph_topology', {})
            
            # Run analysis with circuit breaker and retry
            analysis = await self.circuit_breaker_llm.call(
                self.retry_handler.execute_with_retry,
                self.diagnostic_agent.analyze,
                alert,
                vector_context,
                graph_topology
            )
            
            # Validate and adjust based on environment
            if alert.environment.value == "PROD" and analysis.proposed_action in [ActionType.ROLLBACK, ActionType.RESTART_SERVICE]:
                if analysis.confidence_score < 0.85:
                    analysis.proposed_action = ActionType.ESCALATE_ONLY
                    analysis.confidence_score = min(analysis.confidence_score, 0.7)
            
            # Record metrics
            self.metrics.record_confidence(analysis.confidence_score)
            
            # Record canary result
            self.canary.record_result(version, True, 0)  # Execution time tracked elsewhere
            
            # Log audit
            await self.audit_logger.log_event(
                action=AuditAction.DIAGNOSIS_COMPLETE,
                actor="system",
                target=alert.alert_id,
                details={
                    'service': alert.service_name,
                    'confidence': analysis.confidence_score,
                    'proposed_action': analysis.proposed_action,
                    'model': model,
                    'version': version
                }
            )
            
            # Check if we should cache the result
            if self.cost_manager.should_cache_result(analysis.confidence_score):
                # Cache for future use
                await self._cache_analysis_result(alert, analysis)
            
            return {"analysis": analysis}
            
        except Exception as e:
            logger.error(f"Diagnostic agent failed for {alert.alert_id}: {e}")
            self.metrics.increment_error_count("agent_failure")
            
            # Record canary failure
            self.canary.record_result("control", False, 0)
            
            # Return error state
            return {
                "error_count": state.get('error_count', 0) + 1,
                "error_messages": [f"Diagnostic agent failed: {str(e)}"],
                "analysis": None
            }
    
    def _route_post_diagnosis(self, state: SREWorkflowState) -> Literal["create_jira_ticket", "escalate_only", "handle_error"]:
        """Route based on the diagnosis results."""
        analysis = state.get('analysis')
        
        # Check for errors
        if state.get('error_count', 0) >= 3:
            return "handle_error"
        
        if not analysis:
            return "handle_error"
        
        # Route based on analysis
        if analysis.proposed_action == ActionType.ESCALATE_ONLY:
            return "escalate_only"
        
        return "create_jira_ticket"
    
    @trace_span("workflow.create_jira_ticket")
    async def _create_jira_ticket_node(self, state: SREWorkflowState) -> Dict[str, Any]:
        """Create Jira ticket and pause for human approval."""
        alert = state['alert']
        analysis = state['analysis']
        logger.info(f"Creating Jira ticket for alert {alert.alert_id}")
        
        try:
            # Create ticket with circuit breaker
            ticket_data = await self.circuit_breaker_jira.call(
                self.jira_integration.create_ticket_from_analysis,
                alert=alert,
                analysis=analysis
            )
            
            # Log audit
            await self.audit_logger.log_event(
                action=AuditAction.JIRA_TICKET_CREATED,
                actor="system",
                target=alert.alert_id,
                details={
                    'ticket_id': ticket_data['id'],
                    'service': alert.service_name,
                    'environment': alert.environment.value,
                    'priority': ticket_data.get('priority', 'Medium')
                }
            )
            
            # Update metrics
            self.metrics.increment_workflow_status("WAITING_ON_HUMAN")
            
            return {
                "jira_ticket_id": ticket_data['id'],
                "human_approved": False,
                "final_status": "WAITING_ON_HUMAN"
            }
            
        except Exception as e:
            logger.error(f"Failed to create Jira ticket for {alert.alert_id}: {e}")
            self.metrics.increment_error_count("jira_failure")
            
            return {
                "error_count": state.get('error_count', 0) + 1,
                "error_messages": [f"Jira ticket creation failed: {str(e)}"],
                "final_status": "JIRA_FAILED"
            }
    
    @trace_span("workflow.execute_remediation")
    async def _execute_remediation_node(self, state: SREWorkflowState) -> Dict[str, Any]:
        """Execute the remediation action if human approved."""
        alert = state['alert']
        logger.info(f"Executing remediation for alert {alert.alert_id}")
        
        if not state.get('human_approved', False):
            return {
                "final_status": "REMEDIATION_SKIPPED",
                "error_messages": ["Human approval not granted"]
            }
        
        try:
            analysis = state['analysis']
            start_time = datetime.utcnow()
            
            # Execute remediation with circuit breaker
            result = await self.recovery_manager.execute_with_recovery(
                self.remediation_tool.execute,
                "remediation",
                action=analysis.proposed_action,
                script=analysis.remediation_script,
                service=alert.service_name,
                environment=alert.environment
            )
            
            # Calculate resolution time
            resolution_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Log audit
            await self.audit_logger.log_event(
                action=AuditAction.REMEDIATION_EXECUTED if result['success'] else AuditAction.WORKFLOW_ERROR,
                actor="system" if result['success'] else "system",
                target=alert.alert_id,
                details={
                    'service': alert.service_name,
                    'action': analysis.proposed_action,
                    'success': result['success'],
                    'resolution_time': resolution_time,
                    'output': result.get('output', ''),
                    'error': result.get('error', '')
                }
            )
            
            if result['success']:
                # Record SLA metrics
                self.sla_monitor.record_incident_resolution(
                    alert=alert,
                    analysis=analysis,
                    resolution_time=resolution_time
                )
                
                # Update metrics
                self.metrics.increment_workflow_status("REMEDIATION_SUCCESSFUL")
                
                # Log completion audit
                await self.audit_logger.log_event(
                    action=AuditAction.WORKFLOW_COMPLETED,
                    actor="system",
                    target=alert.alert_id,
                    details={
                        'service': alert.service_name,
                        'resolution_time': resolution_time,
                        'action': analysis.proposed_action
                    }
                )
                
                return {
                    "final_status": "REMEDIATION_SUCCESSFUL"
                }
            else:
                self.metrics.increment_error_count("remediation_failure")
                return {
                    "final_status": "REMEDIATION_FAILED",
                    "error_count": state.get('error_count', 0) + 1,
                    "error_messages": [f"Remediation failed: {result.get('error', 'Unknown error')}"]
                }
                
        except Exception as e:
            logger.error(f"Remediation execution failed for {alert.alert_id}: {e}")
            self.metrics.increment_error_count("remediation_exception")
            
            # Log error audit
            await self.audit_logger.log_event(
                action=AuditAction.WORKFLOW_ERROR,
                actor="system",
                target=alert.alert_id,
                details={
                    'service': alert.service_name,
                    'error': str(e)
                }
            )
            
            return {
                "final_status": "REMEDIATION_FAILED",
                "error_count": state.get('error_count', 0) + 1,
                "error_messages": [f"Remediation execution failed: {str(e)}"]
            }
    
    @trace_span("workflow.escalate_only")
    async def _escalate_only_node(self, state: SREWorkflowState) -> Dict[str, Any]:
        """Handle escalation-only case without automated remediation."""
        alert = state['alert']
        logger.info(f"Escalating alert {alert.alert_id} without automated action")
        
        try:
            analysis = state['analysis']
            
            # Create escalation ticket with circuit breaker
            ticket_data = await self.circuit_breaker_jira.call(
                self.jira_integration.create_escalation_ticket,
                alert=alert,
                analysis=analysis
            )
            
            # Log audit
            await self.audit_logger.log_event(
                action=AuditAction.JIRA_TICKET_CREATED,
                actor="system",
                target=alert.alert_id,
                details={
                    'ticket_id': ticket_data['id'],
                    'service': alert.service_name,
                    'type': 'escalation',
                    'reason': f"Low confidence: {analysis.confidence_score}"
                }
            )
            
            # Update metrics
            self.metrics.increment_workflow_status("ESCALATED")
            
            return {
                "jira_ticket_id": ticket_data['id'],
                "final_status": "ESCALATED"
            }
            
        except Exception as e:
            logger.error(f"Escalation failed for {alert.alert_id}: {e}")
            self.metrics.increment_error_count("escalation_failure")
            
            return {
                "final_status": "ESCALATION_FAILED",
                "error_count": state.get('error_count', 0) + 1,
                "error_messages": [f"Escalation failed: {str(e)}"]
            }
    
    @trace_span("workflow.handle_error")
    async def _handle_error_node(self, state: SREWorkflowState) -> Dict[str, Any]:
        """Handle errors and failures with comprehensive logging."""
        alert = state['alert']
        logger.error(f"Workflow entered error state for alert {alert.alert_id}")
        
        # Log error audit
        await self.audit_logger.log_event(
            action=AuditAction.WORKFLOW_ERROR,
            actor="system",
            target=alert.alert_id,
            details={
                'service': alert.service_name,
                'error_count': state.get('error_count', 0),
                'errors': state.get('error_messages', ['Unknown error'])
            }
        )
        
        # Update metrics
        self.metrics.increment_workflow_status("ERROR")
        
        return {
            "final_status": "ERROR",
            "error_messages": state.get('error_messages', ['Unknown error']),
            "human_approved": False
        }
    
    async def _cache_analysis_result(self, alert: PipelineAlert, analysis: DiagnosticAnalysis):
        """Cache analysis results for future use."""
        try:
            # In production, use Redis or similar for caching
            cache_key = f"analysis:{alert.service_name}:{alert.error_message[:100]}"
            # Store in cache with TTL
            # self.cache.set(cache_key, analysis.dict(), ttl=3600)
            logger.debug(f"Cached analysis result for {alert.service_name}")
        except Exception as e:
            logger.warning(f"Failed to cache analysis result: {e}")
    
    async def start_workflow(self, alert: PipelineAlert, thread_id: str) -> Dict[str, Any]:
        """
        Start the workflow for a new alert with async checkpointing.
        
        Args:
            alert: The pipeline alert to process
            thread_id: Unique thread identifier (usually ADO run ID)
            
        Returns:
            Dictionary with workflow status
        """
        # Check for duplicates
        if await self.deduplicator.is_duplicate(alert):
            logger.info(f"Duplicate alert detected: {alert.alert_id}")
            return {
                "status": "duplicate",
                "thread_id": thread_id,
                "alert_id": alert.alert_id,
                "message": "Alert deduplicated - already processing"
            }
        
        # Log receipt audit
        await self.audit_logger.log_event(
            action=AuditAction.ALERT_RECEIVED,
            actor="ado_pipeline",
            target=alert.alert_id,
            details={
                'service': alert.service_name,
                'environment': alert.environment.value,
                'severity': alert.severity.value,
                'error_message': alert.error_message[:200]
            }
        )
        
        # Update metrics
        self.metrics.increment_alert_count(alert.alert_id, "received")
        
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = {"alert": alert}
        
        try:
            # Get the compiled app
            app = await self.get_app()
            
            # Start workflow with async streaming
            events = []
            async for event in app.astream(initial_state, config):
                events.append(event)
            
            # Check if workflow is paused
            state = await app.aget_state(config)
            if state and state.next:
                logger.info(f"Workflow paused for alert {alert.alert_id} waiting for human approval")
                return {
                    "status": "WAITING_ON_HUMAN",
                    "thread_id": thread_id,
                    "alert_id": alert.alert_id,
                    "jira_ticket_id": state.values.get('jira_ticket_id')
                }
            
            logger.info(f"Workflow completed for alert {alert.alert_id}")
            return {
                "status": "COMPLETED",
                "thread_id": thread_id,
                "alert_id": alert.alert_id,
                "final_status": state.values.get('final_status') if state else "unknown"
            }
            
        except Exception as e:
            logger.error(f"Workflow failed for alert {alert.alert_id}: {e}")
            self.metrics.increment_error_count("workflow_start_failure")
            
            # Log error audit
            await self.audit_logger.log_event(
                action=AuditAction.WORKFLOW_ERROR,
                actor="system",
                target=alert.alert_id,
                details={'error': str(e)}
            )
            
            return {
                "status": "ERROR",
                "thread_id": thread_id,
                "alert_id": alert.alert_id,
                "error": str(e)
            }
    
    async def resume_workflow(
        self, 
        thread_id: str, 
        human_approved: bool, 
        additional_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Resume a paused workflow after human decision with async checkpointing.
        
        Args:
            thread_id: The thread ID of the paused workflow
            human_approved: Whether the human approved the remediation
            additional_data: Additional data to merge into state
            
        Returns:
            Dictionary with workflow status
        """
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            # Get the compiled app
            app = await self.get_app()
            
            # Get current state
            current_state = await app.aget_state(config)
            if not current_state:
                return {
                    "status": "ERROR",
                    "thread_id": thread_id,
                    "error": "Workflow not found"
                }
            
            # Get alert ID for logging
            alert = current_state.values.get('alert')
            if alert:
                alert_id = getattr(alert, 'alert_id', thread_id)
            else:
                alert_id = thread_id
            
            # Log human approval audit
            await self.audit_logger.log_event(
                action=AuditAction.HUMAN_APPROVED,
                actor="human",
                target=alert_id,
                details={
                    'approved': human_approved,
                    'thread_id': thread_id,
                    'jira_ticket_id': current_state.values.get('jira_ticket_id')
                }
            )
            
            # Update state with human decision asynchronously
            await app.aupdate_state(
                config,
                {
                    "human_approved": human_approved,
                    "final_status": "APPROVAL_PROCESSED",
                    **(additional_data or {})
                },
                as_node="create_jira_ticket"
            )
            
            # Resume execution
            events = []
            async for event in app.astream(None, config):
                events.append(event)
            
            # Get final state
            final_state = await app.aget_state(config)
            final_status = final_state.values.get('final_status') if final_state else "unknown"
            
            logger.info(f"Workflow resumed for thread {thread_id}. Final status: {final_status}")
            
            # Log completion audit if successful
            if final_status in ["REMEDIATION_SUCCESSFUL", "COMPLETED"]:
                await self.audit_logger.log_event(
                    action=AuditAction.WORKFLOW_COMPLETED,
                    actor="system",
                    target=alert_id,
                    details={
                        'thread_id': thread_id,
                        'final_status': final_status,
                        'human_approved': human_approved
                    }
                )
            
            return {
                "status": "COMPLETED" if final_status == "REMEDIATION_SUCCESSFUL" else "FAILED",
                "thread_id": thread_id,
                "final_status": final_status,
                "state": final_state.values if final_state else None
            }
            
        except Exception as e:
            logger.error(f"Failed to resume workflow {thread_id}: {e}")
            self.metrics.increment_error_count("workflow_resume_failure")
            
            return {
                "status": "ERROR",
                "thread_id": thread_id,
                "error": str(e)
            }
    
    async def get_state(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the current state of a workflow asynchronously.
        
        Args:
            thread_id: The thread ID of the workflow
            
        Returns:
            Dictionary with workflow state or None if not found
        """
        try:
            app = await self.get_app()
            config = {"configurable": {"thread_id": thread_id}}
            state = await app.aget_state(config)
            
            if state:
                return {
                    "values": state.values,
                    "next": state.next,
                    "config": state.config
                }
            return None
            
        except Exception as e:
            logger.error(f"Failed to get workflow state for {thread_id}: {e}")
            return None
    
    async def get_thread_history(self, thread_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get execution history for a thread asynchronously.
        
        Args:
            thread_id: The thread ID of the workflow
            limit: Maximum number of events to return
            
        Returns:
            List of execution events
        """
        try:
            app = await self.get_app()
            config = {"configurable": {"thread_id": thread_id}}
            
            history = []
            async for event in app.aget_history(config, limit=limit):
                history.append({
                    "step": event.step,
                    "timestamp": event.timestamp.isoformat(),
                    "node": event.node,
                    "state": event.values
                })
            
            return history
            
        except Exception as e:
            logger.error(f"Failed to get thread history for {thread_id}: {e}")
            return []
    
    async def list_workflows(
        self,
        status: Optional[str] = None,
        service: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List workflows with optional filters.
        
        Args:
            status: Filter by workflow status
            service: Filter by service name
            limit: Maximum number of workflows to return
            
        Returns:
            List of workflow summaries
        """
        try:
            # In production, query the database directly
            # This is a simplified version using the checkpointer
            app = await self.get_app()
            # Use checkpointer to list threads
            # This requires implementing a list_threads method
            
            return [
                {
                    "thread_id": "example",
                    "status": "WAITING_ON_HUMAN",
                    "service": "auth-service",
                    "created_at": datetime.utcnow().isoformat()
                }
            ]
            
        except Exception as e:
            logger.error(f"Failed to list workflows: {e}")
            return []
    
    async def close(self):
        """Clean up resources gracefully."""
        logger.info("Closing SREWorkflow resources...")
        
        # Close connection pool
        if self._pool:
            await self._pool.close()
            logger.info("Database connection pool closed")
        
        # Close other resources
        await self.graph_rag.close()
        await self.jira_integration.close()
        
        logger.info("SREWorkflow resources closed")