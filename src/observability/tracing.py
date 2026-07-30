# src/observability/tracing.py
from typing import Callable, Dict, Any, Optional
import asyncio
import logging
from functools import wraps
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.propagate import set_global_textmap
from src.config.settings import settings

logger = logging.getLogger(__name__)

def initialize_tracing():
    """Initialize OpenTelemetry tracing."""
    try:
        # Create resource with service information
        resource = Resource(attributes={
            ResourceAttributes.SERVICE_NAME: settings.OTEL_SERVICE_NAME,
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: settings.ENVIRONMENT.value,
            "team.owner": "sre-automation",
            "app.version": settings.APP_VERSION
        })
        
        # Create tracer provider
        provider = TracerProvider(resource=resource)
        
        # Add exporters
        if settings.ENVIRONMENT.value in ["DEV", "SIT"]:
            # Console exporter for development
            console_exporter = ConsoleSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(console_exporter))
        
        if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
            # OTLP exporter for production
            otlp_exporter = OTLPSpanExporter(
                endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            )
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        
        # Set global tracer provider
        trace.set_tracer_provider(provider)
        
        # Set propagation
        set_global_textmap(TraceContextTextMapPropagator())
        
        logger.info(f"Tracing initialized for environment: {settings.ENVIRONMENT.value}")
        return trace.get_tracer(settings.OTEL_SERVICE_NAME)
    
    except Exception as e:
        logger.warning(f"Failed to initialize tracing: {e}. Falling back to no-op tracer.")
        return trace.get_tracer_provider().get_tracer("noop")

# Global tracer instance
tracer = initialize_tracing()

def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Decorator for tracing a function as a span."""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with tracer.start_as_current_span(name) as span:
                # Add attributes
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                # Extract and set trace context from args/kwargs if present
                if hasattr(args[0], 'alert_id') if args else False:
                    span.set_attribute("alert.id", args[0].alert_id)
                
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("success", True)
                    return result
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                    span.record_exception(e)
                    raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("success", True)
                    return result
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                    span.record_exception(e)
                    raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator

# src/observability/metrics.py
from typing import Dict, Any, Optional
import logging
from datetime import datetime
from collections import defaultdict
import json
from src.config.settings import settings

logger = logging.getLogger(__name__)

class MetricsCollector:
    """Collect and aggregate system metrics."""
    
    def __init__(self):
        self.alert_counts = defaultdict(int)
        self.alert_status = defaultdict(int)
        self.confidence_scores = []
        self.workflow_status = defaultdict(int)
        self.errors = defaultdict(int)
        self.start_time = datetime.utcnow()
        self.total_processed = 0
        self.mining_clusters_detected = 0
        self.mining_new_clusters = 0
        self.mining_velocity_spikes = 0
        self.mining_runs_completed = 0
    
    def increment_alert_count(self, alert_id: str, status: str):
        """Increment alert count metric."""
        self.alert_counts[status] += 1
        self.total_processed += 1
        logger.debug(f"Alert {alert_id}: {status}")
    
    def record_confidence(self, confidence: float):
        """Record agent confidence score."""
        self.confidence_scores.append(confidence)
        # Keep only last 1000 scores for memory efficiency
        if len(self.confidence_scores) > 1000:
            self.confidence_scores = self.confidence_scores[-1000:]
    
    def increment_workflow_status(self, status: str):
        """Increment workflow status count."""
        self.workflow_status[status] += 1
    
    def increment_error_count(self, error_type: str = "general"):
        """Increment error count."""
        self.errors[error_type] += 1
    
    def increment_mining_clusters_detected(self, count: int = 1):
        self.mining_clusters_detected += count
    
    def increment_mining_new_clusters(self, count: int = 1):
        self.mining_new_clusters += count
    
    def increment_mining_velocity_spikes(self, count: int = 1):
        self.mining_velocity_spikes += count
    
    def increment_mining_runs(self):
        self.mining_runs_completed += 1
    
    def get_alert_counts(self) -> Dict[str, int]:
        """Get alert count metrics."""
        return dict(self.alert_counts)
    
    def get_confidence_avg(self) -> float:
        """Get average confidence score."""
        if not self.confidence_scores:
            return 0.0
        return sum(self.confidence_scores) / len(self.confidence_scores)
    
    def get_workflow_status_counts(self) -> Dict[str, int]:
        """Get workflow status counts."""
        return dict(self.workflow_status)
    
    def get_uptime(self) -> float:
        """Get uptime in seconds."""
        return (datetime.utcnow() - self.start_time).total_seconds()
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics."""
        return {
            "alerts": dict(self.alert_counts),
            "total_processed": self.total_processed,
            "confidence_avg": self.get_confidence_avg(),
            "workflow_status": dict(self.workflow_status),
            "errors": dict(self.errors),
            "uptime": self.get_uptime(),
            "start_time": self.start_time.isoformat(),
            "environment": settings.ENVIRONMENT.value,
            "mining": {
                "clusters_detected": self.mining_clusters_detected,
                "new_clusters": self.mining_new_clusters,
                "velocity_spikes": self.mining_velocity_spikes,
                "runs_completed": self.mining_runs_completed,
            },
        }
    
    def reset(self):
        """Reset all metrics."""
        self.alert_counts.clear()
        self.alert_status.clear()
        self.confidence_scores.clear()
        self.workflow_status.clear()
        self.errors.clear()
        self.start_time = datetime.utcnow()
        self.total_processed = 0