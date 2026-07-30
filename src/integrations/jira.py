# src/integrations/jira.py
from typing import Dict, Any, Optional
import logging
import json
from datetime import datetime
import aiohttp
from jira import JIRA
from src.config.settings import settings
from src.models.schemas import PipelineAlert, DiagnosticAnalysis, JiraTicketDraft
from src.observability.tracing import tracer, trace_span

logger = logging.getLogger(__name__)

class JiraIntegration:
    def __init__(self):
        self.url = settings.JIRA_URL
        self.auth = None
        if settings.JIRA_USERNAME and settings.JIRA_API_TOKEN:
            self.auth = (
                settings.JIRA_USERNAME,
                settings.JIRA_API_TOKEN.get_secret_value()
            )
        self.session = None
        self.client = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def _get_client(self) -> JIRA:
        """Get or create JIRA client (synchronous)."""
        if not self.client and self.auth:
            self.client = JIRA(
                server=self.url,
                basic_auth=self.auth
            )
        return self.client
    
    @trace_span("jira.create_ticket")
    async def create_ticket_from_analysis(
        self,
        alert: PipelineAlert,
        analysis: DiagnosticAnalysis
    ) -> Dict[str, Any]:
        """Create a Jira ticket from the diagnostic analysis."""
        try:
            # Prepare ticket data
            ticket = self._prepare_ticket_data(alert, analysis)
            
            # Create ticket
            return await self._create_ticket(ticket)
        
        except Exception as e:
            logger.error(f"Failed to create Jira ticket: {e}")
            raise
    
    def _prepare_ticket_data(
        self,
        alert: PipelineAlert,
        analysis: DiagnosticAnalysis
    ) -> JiraTicketDraft:
        """Prepare ticket data for Jira."""
        # Determine priority based on confidence and environment
        priority = "Medium"
        if analysis.confidence_score > 0.8 and alert.environment in ["PROD", "UAT"]:
            priority = "Critical"
        elif analysis.confidence_score > 0.7 and alert.environment in ["PROD", "UAT"]:
            priority = "High"
        elif alert.severity.value in ["CRITICAL", "HIGH"]:
            priority = "High"
        
        # Build description
        description = f"""h2. Root Cause Analysis

*Service:* {alert.service_name}
*Environment:* {alert.environment}
*Alert ID:* {alert.alert_id}
*Timestamp:* {alert.timestamp}

h3. Summary
{analysis.root_cause_summary}

h3. Detailed Analysis
{analysis.detailed_analysis or "No detailed analysis provided."}

h3. Topology Impact
*Upstream Dependencies:* {', '.join(analysis.upstream_dependencies) or 'None'}
*Downstream Dependencies:* {', '.join(analysis.downstream_dependencies) or 'None'}
*Historical Matches:* {'Found' if analysis.historical_matches_found else 'None'}

h3. Proposed Action
*Action:* {analysis.proposed_action}
*Confidence:* {analysis.confidence_score:.2%}

h3. Remediation Script
{analysis.remediation_script or 'Not provided'}

h3. Error Details
*Error Message:* {alert.error_message}

*Stack Trace:*
{{
code:javascript}}
{alert.stack_trace or 'No stack trace available'}
{{code}}

h3. Additional Context
*Service Version:* {alert.service_version or 'Unknown'}
*Commit Hash:* {alert.git_commit_hash or 'Unknown'}
"""
        
        # Prepare labels
        labels = [
            "auto-sre",
            alert.environment.lower(),
            alert.service_name.lower().replace('-', ''),
            f"confidence-{int(analysis.confidence_score * 100)}"
        ]
        
        if analysis.historical_matches_found:
            labels.append("historical-match")
        
        return JiraTicketDraft(
            project_key=settings.JIRA_PROJECT_KEY,
            issue_type=settings.JIRA_ISSUE_TYPE,
            summary=f"[AI Triage] {alert.environment}: {alert.service_name} - {alert.error_message[:50]}",
            description=description,
            priority=priority,
            labels=labels,
            environment=alert.environment,
            affected_service=alert.service_name,
            confidence_score=analysis.confidence_score,
            proposed_action=analysis.proposed_action
        )
    
    @trace_span("jira.create_ticket")
    async def _create_ticket(self, ticket: JiraTicketDraft) -> Dict[str, Any]:
        """Create ticket in Jira."""
        try:
            # Use synchronous client for simplicity
            # In production, consider using async client
            client = self._get_client()
            
            if not client:
                raise ValueError("Jira client not configured")
            
            # Create issue
            issue = client.create_issue(
                project=ticket.project_key,
                summary=ticket.summary,
                description=ticket.description,
                issuetype={'name': ticket.issue_type},
                priority={'name': ticket.priority},
                labels=ticket.labels
            )
            
            if ticket.assignee_id:
                client.assign_issue(issue, ticket.assignee_id)
            
            logger.info(f"Created Jira ticket: {issue.key}")
            
            return {
                'id': issue.key,
                'url': f"{self.url}/browse/{issue.key}",
                'summary': ticket.summary,
                'priority': ticket.priority
            }
        
        except Exception as e:
            logger.error(f"Failed to create Jira ticket: {e}")
            raise
    
    @trace_span("jira.escalate_ticket")
    async def create_escalation_ticket(
        self,
        alert: PipelineAlert,
        analysis: DiagnosticAnalysis
    ) -> Dict[str, Any]:
        """Create an escalation ticket."""
        try:
            # Prepare escalation data
            ticket_data = self._prepare_ticket_data(alert, analysis)
            ticket_data.summary = f"[ESCALATION] {ticket_data.summary}"
            ticket_data.priority = "Critical"  # Escalations are always critical
            
            # Add escalation note
            ticket_data.description = f"""
            h2. ESCALATION - No Automated Action Available
            
            {ticket_data.description}
            
            h3. Escalation Reason
            *Automated action not recommended due to:*
            * Confidence score below threshold: {analysis.confidence_score}
            * Service environment: {alert.environment}
            * Proposed action: {analysis.proposed_action}
            
            *On-call engineer must investigate and remediate manually.*
            """
            
            return await self._create_ticket(ticket_data)
        
        except Exception as e:
            logger.error(f"Failed to create escalation ticket: {e}")
            raise
    
    @trace_span("jira.update_ticket")
    async def update_ticket(
        self,
        ticket_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update an existing Jira ticket."""
        try:
            client = self._get_client()
            
            if not client:
                raise ValueError("Jira client not configured")
            
            issue = client.issue(ticket_id)
            
            if 'summary' in updates:
                issue.update(summary=updates['summary'])
            if 'description' in updates:
                issue.update(description=updates['description'])
            if 'status' in updates:
                transitions = client.transitions(issue)
                for transition in transitions:
                    if transition['name'].lower() == updates['status'].lower():
                        client.transition_issue(issue, transition['id'])
                        break
            
            if 'comment' in updates:
                client.add_comment(issue, updates['comment'])
            
            logger.info(f"Updated Jira ticket: {ticket_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to update Jira ticket {ticket_id}: {e}")
            return False
    
    @trace_span("jira.get_ticket")
    async def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket details from Jira."""
        try:
            client = self._get_client()
            
            if not client:
                raise ValueError("Jira client not configured")
            
            issue = client.issue(ticket_id)
            
            return {
                'id': issue.key,
                'summary': issue.fields.summary,
                'status': issue.fields.status.name,
                'priority': issue.fields.priority.name,
                'assignee': issue.fields.assignee.displayName if issue.fields.assignee else None,
                'created': issue.fields.created,
                'updated': issue.fields.updated,
                'url': f"{self.url}/browse/{issue.key}"
            }
        
        except Exception as e:
            logger.error(f"Failed to get Jira ticket {ticket_id}: {e}")
            return None
    
    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()