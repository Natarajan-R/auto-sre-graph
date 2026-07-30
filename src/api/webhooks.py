# src/api/webhooks.py
from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
from typing import Dict, Any
from datetime import datetime
from src.config.settings import settings
from src.models.schemas import PipelineAlert
from src.models.validators import WebhookValidation, AlertFilter
from src.orchestrator.graph import SREWorkflow
from src.integrations.webhook_handler import WebhookHandler
from opentelemetry import trace
from src.observability.tracing import tracer, trace_span
from src.observability.tracing import MetricsCollector
from src.api.dependencies import RateLimiter
from src.api.mining import router as mining_router

logger = logging.getLogger(__name__)

def get_webhook_validation() -> WebhookValidation:
    """Dependency factory for WebhookValidation."""
    return WebhookValidation()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Enterprise AI Workflow Automation - Auto-SRE-Graph"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependencies
workflow = SREWorkflow()
webhook_handler = WebhookHandler()
metrics = MetricsCollector()
alert_filter = AlertFilter()
rate_limiter = RateLimiter()
_processed_alert_ids: set = set()

# Health check
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "version": settings.APP_VERSION,
        "timestamp": datetime.utcnow().isoformat()
    }

# Ingestion endpoint
@app.post("/webhooks/ado")
@trace_span("webhooks.ado")
async def handle_ado_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: PipelineAlert,
    validation: WebhookValidation = Depends(get_webhook_validation),
    _: bool = Depends(rate_limiter),
) -> Dict[str, Any]:
    """
    Handle incoming webhook from ADO pipeline.
    
    This endpoint receives the raw error payload, validates it,
    and starts the diagnostic workflow.
    """
    try:
        # Start trace
        span = trace.get_current_span()
        span.set_attribute("alert.id", payload.alert_id)
        span.set_attribute("alert.service", payload.service_name)
        span.set_attribute("alert.environment", payload.environment)
        
        # Deduplication check
        if payload.alert_id in _processed_alert_ids:
            logger.info(f"Filtered duplicate alert {payload.alert_id}")
            metrics.increment_alert_count(payload.alert_id, "filtered")
            return {
                "status": "filtered",
                "alert_id": payload.alert_id,
                "message": "Duplicate alert filtered out"
            }
        _processed_alert_ids.add(payload.alert_id)
        
        # Validate and sanitize
        validated_payload = validation.validate_payload(payload.model_dump())
        
        # Filter noisy alerts
        if alert_filter.should_filter(payload):
            logger.info(f"Filtered alert {payload.alert_id} - noisy")
            metrics.increment_alert_count(payload.alert_id, "filtered")
            return {
                "status": "filtered",
                "alert_id": payload.alert_id,
                "message": "Alert filtered out - too noisy"
            }
        
        # Start workflow in background
        background_tasks.add_task(
            workflow.start_workflow,
            payload,
            payload.alert_id
        )
        
        metrics.increment_alert_count(payload.alert_id, "ingested")
        logger.info(f"Alert {payload.alert_id} ingested successfully")
        
        return {
            "status": "processing",
            "alert_id": payload.alert_id,
            "message": "Alert queued for processing"
        }
    
    except Exception as e:
        logger.error(f"Failed to process webhook: {e}")
        metrics.increment_alert_count("error", "failed")
        raise HTTPException(status_code=500, detail=str(e))

# Tripwire webhook endpoint
@app.post("/webhooks/tripwire")
@trace_span("webhooks.tripwire")
async def handle_tripwire_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    _: bool = Depends(rate_limiter),
) -> Dict[str, Any]:
    try:
        payload = await request.json()

        span = trace.get_current_span()
        span.set_attribute("alert.source", "tripwire")
        span.set_attribute("alert.service", payload.get("service_name", "unknown"))

        alert_id = payload.get("alert_id", f"TRIPWIRE-{int(datetime.utcnow().timestamp())}")

        if alert_id in _processed_alert_ids:
            logger.info(f"Filtered duplicate tripwire alert {alert_id}")
            return {"status": "filtered", "alert_id": alert_id, "message": "Duplicate alert filtered out"}
        _processed_alert_ids.add(alert_id)

        result = await webhook_handler.process(request, "tripwire", payload)
        alert = PipelineAlert(**result["alert"])

        if alert_filter.should_filter(alert):
            logger.info(f"Filtered tripwire alert {alert_id} - noisy")
            return {"status": "filtered", "alert_id": alert_id, "message": "Alert filtered out"}

        background_tasks.add_task(workflow.start_workflow, alert, alert_id)
        metrics.increment_alert_count(alert_id, "ingested")
        logger.info(f"Tripwire alert {alert_id} ingested successfully")

        return {"status": "processing", "alert_id": alert_id, "message": "Tripwire alert queued for processing"}

    except Exception as e:
        logger.error(f"Failed to process tripwire webhook: {e}")
        metrics.increment_alert_count("error", "failed")
        raise HTTPException(status_code=500, detail=str(e))

# Jira webhook endpoint
@app.post("/webhooks/jira")
@trace_span("webhooks.jira")
async def handle_jira_webhook(
    request: Request,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """
    Handle Jira webhook for approval decisions.
    """
    try:
        # Verify webhook secret
        secret = request.headers.get("X-Jira-Secret")
        if secret != settings.JIRA_WEBHOOK_SECRET.get_secret_value():
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        # Parse webhook payload
        payload = await request.json()
        
        # Extract decision
        thread_id = payload.get('thread_id')
        is_approved = payload.get('approved', False)
        
        if not thread_id:
            raise HTTPException(status_code=400, detail="Missing thread_id")
        
        # Resume workflow in background
        background_tasks.add_task(
            workflow.resume_workflow,
            thread_id,
            is_approved,
            {'jira_data': payload}
        )
        
        logger.info(f"Jira webhook processed for thread {thread_id}")
        return {
            "status": "processing",
            "thread_id": thread_id,
            "message": "Workflow resuming"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process Jira webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Status endpoint
@app.get("/status/{thread_id}")
@trace_span("status.get")
async def get_workflow_status(thread_id: str) -> Dict[str, Any]:
    """
    Get the status of a workflow by thread ID.
    """
    try:
        state = await workflow.get_state(thread_id)
        
        if not state:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        return {
            "thread_id": thread_id,
            "status": state['values'].get('final_status', 'unknown'),
            "jira_ticket_id": state['values'].get('jira_ticket_id'),
            "human_approved": state['values'].get('human_approved', False),
            "last_updated": datetime.utcnow().isoformat(),
            "state": state['values']
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workflow status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Metrics endpoint
@app.get("/metrics")
async def get_metrics() -> Dict[str, Any]:
    """Get system metrics."""
    return {
        "alerts_processed": metrics.get_alert_counts(),
        "agent_confidence": metrics.get_confidence_avg(),
        "workflow_status": metrics.get_workflow_status_counts(),
        "uptime": metrics.get_uptime(),
        "mining": {
            "clusters_detected": metrics.mining_clusters_detected,
            "new_clusters": metrics.mining_new_clusters,
            "velocity_spikes": metrics.mining_velocity_spikes,
            "runs_completed": metrics.mining_runs_completed,
        },
    }

# Include mining routes
app.include_router(mining_router)

# Error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    metrics.increment_error_count()
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "path": request.url.path,
            "timestamp": datetime.utcnow().isoformat()
        }
    )