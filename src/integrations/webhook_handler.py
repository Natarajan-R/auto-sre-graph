# src/integrations/webhook_handler.py
from typing import Dict, Any, Optional, Callable, Awaitable
import logging
import json
from datetime import datetime
import aiohttp
from fastapi import Request, HTTPException
from src.config.settings import settings
from src.models.schemas import PipelineAlert, JiraTicketDraft
from src.observability.tracing import tracer, trace_span

logger = logging.getLogger(__name__)

class WebhookHandler:
    """
    Handles incoming webhooks from various sources.
    Provides verification, parsing, and routing of webhook events.
    """
    
    def __init__(self):
        self.webhook_secret = settings.JIRA_WEBHOOK_SECRET
        self.signing_secret = settings.WEBHOOK_SIGNING_SECRET
        self.handlers: Dict[str, Callable] = {}
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """Register default webhook handlers."""
        self.handlers = {
            'jira_approval': self._handle_jira_approval,
            'ado_pipeline': self._handle_ado_pipeline,
            'tripwire': self._handle_tripwire,
            'github': self._handle_github,
            'gitlab': self._handle_gitlab,
            'custom': self._handle_custom
        }
    
    @trace_span("webhook_handler.process")
    async def process(
        self,
        request: Request,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process an incoming webhook.
        
        Args:
            request: The incoming request
            event_type: Type of webhook event
            payload: Webhook payload
            
        Returns:
            Processing result
        """
        try:
            # Verify webhook
            if not await self._verify_webhook(request, payload):
                raise HTTPException(status_code=401, detail="Webhook verification failed")
            
            # Route to appropriate handler
            handler = self.handlers.get(event_type)
            if not handler:
                logger.warning(f"No handler found for event type: {event_type}")
                return {'status': 'ignored', 'message': 'No handler registered'}
            
            # Process with handler
            result = await handler(payload)
            
            logger.info(f"Webhook {event_type} processed successfully")
            return result
            
        except Exception as e:
            logger.error(f"Failed to process webhook {event_type}: {e}")
            raise
    
    async def _verify_webhook(self, request: Request, payload: Dict[str, Any]) -> bool:
        """Verify webhook authenticity."""
        secret = request.headers.get("X-Webhook-Secret")
        if self.webhook_secret and secret != self.webhook_secret.get_secret_value():
            return False
        
        signature = request.headers.get("X-Signature")
        if self.signing_secret and signature:
            import hashlib
            import hmac

            body = await request.body()
            computed = hmac.new(
                self.signing_secret.get_secret_value().encode(),
                body,
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(signature, computed):
                return False

        return True
    
    @trace_span("webhook_handler.jira_approval")
    async def _handle_jira_approval(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle Jira approval webhook.
        
        Args:
            payload: Jira webhook payload
            
        Returns:
            Processing result
        """
        try:
            # Extract approval data
            issue_id = payload.get('issue', {}).get('key')
            status = payload.get('issue', {}).get('fields', {}).get('status', {}).get('name')
            
            # Check if it's an approval transition
            is_approved = status and status.lower() in ['approved', 'resolved', 'closed']
            
            # Get thread ID from issue
            thread_id = None
            for field in payload.get('issue', {}).get('fields', {}).get('customfields', []):
                if field.get('name') == 'Thread ID':
                    thread_id = field.get('value')
                    break
            
            if not thread_id:
                # Try from description or labels
                description = payload.get('issue', {}).get('fields', {}).get('description', '')
                import re
                match = re.search(r'Thread ID: (\S+)', description)
                if match:
                    thread_id = match.group(1)
            
            result = {
                'type': 'jira_approval',
                'issue_id': issue_id,
                'thread_id': thread_id,
                'approved': is_approved,
                'status': status,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            logger.info(f"Jira approval processed for issue {issue_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to handle Jira approval: {e}")
            raise
    
    @trace_span("webhook_handler.ado_pipeline")
    async def _handle_ado_pipeline(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle ADO pipeline webhook.
        
        Args:
            payload: ADO webhook payload
            
        Returns:
            Processing result
        """
        try:
            # Extract pipeline data
            resource = payload.get('resource', {})
            
            # Parse alert from pipeline
            alert = PipelineAlert(
                alert_id=resource.get('runId', str(datetime.utcnow().timestamp())),
                environment=resource.get('environment', 'DEV'),
                service_name=resource.get('service', 'unknown'),
                error_message=resource.get('errorMessage', 'Pipeline failure'),
                stack_trace=resource.get('stackTrace'),
                git_commit_hash=resource.get('commitHash'),
                severity=resource.get('severity', 'HIGH'),
                service_version=resource.get('version'),
                additional_context=resource
            )
            
            result = {
                'type': 'ado_pipeline',
                'alert': alert.model_dump(),
                'resource': resource,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            logger.info(f"ADO pipeline webhook processed for run {resource.get('runId')}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to handle ADO pipeline: {e}")
            raise
    
    @trace_span("webhook_handler.github")
    async def _handle_github(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle GitHub webhook.
        
        Args:
            payload: GitHub webhook payload
            
        Returns:
            Processing result
        """
        try:
            # Extract GitHub data
            repository = payload.get('repository', {}).get('name')
            action = payload.get('action')
            workflow = payload.get('workflow', {}).get('name')
            conclusion = payload.get('workflow_run', {}).get('conclusion')
            
            result = {
                'type': 'github',
                'repository': repository,
                'action': action,
                'workflow': workflow,
                'conclusion': conclusion,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            logger.info(f"GitHub webhook processed for {repository}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to handle GitHub webhook: {e}")
            raise
    
    @trace_span("webhook_handler.gitlab")
    async def _handle_gitlab(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle GitLab webhook.
        
        Args:
            payload: GitLab webhook payload
            
        Returns:
            Processing result
        """
        try:
            # Extract GitLab data
            project = payload.get('project', {}).get('name')
            object_kind = payload.get('object_kind')
            pipeline = payload.get('pipeline', {})
            
            result = {
                'type': 'gitlab',
                'project': project,
                'object_kind': object_kind,
                'pipeline_id': pipeline.get('id'),
                'status': pipeline.get('status'),
                'processed_at': datetime.utcnow().isoformat()
            }
            
            logger.info(f"GitLab webhook processed for {project}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to handle GitLab webhook: {e}")
            raise
    
    @trace_span("webhook_handler.tripwire")
    async def _handle_tripwire(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            alert = PipelineAlert(
                alert_id=payload.get('alert_id', f"TRIPWIRE-{int(datetime.utcnow().timestamp())}"),
                environment=payload.get('environment', 'DEV'),
                service_name=payload.get('service_name', 'unknown'),
                error_message=payload.get('error_message', 'Log tripwire triggered'),
                stack_trace=payload.get('stack_trace'),
                severity=payload.get('severity', 'HIGH'),
                additional_context={'source': 'log_tripwire', 'raw_payload': payload}
            )

            result = {
                'type': 'tripwire',
                'alert': alert.model_dump(),
                'raw_payload': payload,
                'processed_at': datetime.utcnow().isoformat()
            }

            logger.info(f"Tripwire alert processed: {payload.get('alert_id')}")
            return result

        except Exception as e:
            logger.error(f"Failed to handle tripwire alert: {e}")
            raise

    @trace_span("webhook_handler.custom")
    async def _handle_custom(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle custom webhook.
        
        Args:
            payload: Custom webhook payload
            
        Returns:
            Processing result
        """
        try:
            # Parse custom alert
            alert = PipelineAlert(
                alert_id=payload.get('id', str(datetime.utcnow().timestamp())),
                environment=payload.get('environment', 'DEV'),
                service_name=payload.get('service', 'unknown'),
                error_message=payload.get('error', 'Unknown error'),
                stack_trace=payload.get('stack_trace'),
                git_commit_hash=payload.get('commit'),
                severity=payload.get('severity', 'HIGH'),
                additional_context=payload
            )
            
            result = {
                'type': 'custom',
                'alert': alert.model_dump(),
                'original_payload': payload,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            logger.info(f"Custom webhook processed for {payload.get('id')}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to handle custom webhook: {e}")
            raise
    
    def register_handler(self, event_type: str, handler: Callable):
        """
        Register a custom webhook handler.
        
        Args:
            event_type: The event type to handle
            handler: Async function to handle the webhook
        """
        self.handlers[event_type] = handler
        logger.info(f"Registered handler for event type: {event_type}")
    
    async def send_webhook(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        Send a webhook to an external service.
        
        Args:
            url: The webhook URL
            payload: The payload to send
            headers: Additional headers
            
        Returns:
            True if successful, False otherwise
        """
        try:
            default_headers = {
                "Content-Type": "application/json",
                "User-Agent": "Auto-SRE-Graph/1.0"
            }
            
            if headers:
                default_headers.update(headers)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=default_headers,
                    timeout=30
                ) as response:
                    if response.status in [200, 201, 202, 204]:
                        logger.info(f"Webhook sent to {url} successfully")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Webhook to {url} failed: {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error sending webhook to {url}: {e}")
            return False