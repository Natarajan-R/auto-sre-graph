# src/observability/sla_monitor.py
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging
from collections import deque
from dataclasses import dataclass, field
import json
from src.config.settings import settings
from src.models.schemas import PipelineAlert, DiagnosticAnalysis

logger = logging.getLogger(__name__)

@dataclass
class SLAMetrics:
    """SLA metrics for a service."""
    service_name: str
    total_incidents: int = 0
    resolved_incidents: int = 0
    average_resolution_time: float = 0.0
    p95_resolution_time: float = 0.0
    p99_resolution_time: float = 0.0
    total_downtime: float = 0.0
    success_rate: float = 100.0
    rollback_count: int = 0
    escalation_count: int = 0
    resolution_times: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    def add_incident(self, resolution_time: float, action: str):
        """Add an incident resolution record."""
        self.total_incidents += 1
        if resolution_time > 0:
            self.resolved_incidents += 1
            self.resolution_times.append(resolution_time)
            self.average_resolution_time = sum(self.resolution_times) / len(self.resolution_times)
            
            # Calculate percentiles
            sorted_times = sorted(self.resolution_times)
            if len(sorted_times) > 10:
                p95_index = int(len(sorted_times) * 0.95)
                p99_index = int(len(sorted_times) * 0.99)
                self.p95_resolution_time = sorted_times[p95_index]
                self.p99_resolution_time = sorted_times[p99_index]
        
        if action == "ROLLBACK":
            self.rollback_count += 1
        elif action == "ESCALATE_ONLY":
            self.escalation_count += 1
        
        # Update success rate
        if self.total_incidents > 0:
            self.success_rate = (self.resolved_incidents / self.total_incidents) * 100

class SLAMonitor:
    """Monitors and enforces SLAs for the system."""
    
    def __init__(self):
        self.metrics: Dict[str, SLAMetrics] = {}
        self.sla_configs: Dict[str, Dict] = {}
        self._load_sla_configs()
        self.alert_thresholds = {
            'response_time': 300,  # 5 minutes
            'resolution_time': 3600,  # 1 hour
            'escalation_rate': 0.3,  # 30%
            'success_rate': 0.95  # 95%
        }
    
    def _load_sla_configs(self):
        """Load SLA configurations for services."""
        # In production, this could come from a config file or database
        self.sla_configs = {
            'critical': {
                'response_time': 120,
                'resolution_time': 1800,
                'uptime': 99.99
            },
            'high': {
                'response_time': 300,
                'resolution_time': 3600,
                'uptime': 99.9
            },
            'medium': {
                'response_time': 600,
                'resolution_time': 7200,
                'uptime': 99.0
            }
        }
    
    def get_service_metrics(self, service_name: str) -> SLAMetrics:
        """Get or create SLA metrics for a service."""
        if service_name not in self.metrics:
            self.metrics[service_name] = SLAMetrics(service_name=service_name)
        return self.metrics[service_name]
    
    def record_incident_resolution(
        self,
        alert: PipelineAlert,
        analysis: DiagnosticAnalysis,
        resolution_time: float
    ):
        """Record an incident resolution for SLA tracking."""
        metrics = self.get_service_metrics(alert.service_name)
        metrics.add_incident(resolution_time, analysis.proposed_action)
        
        # Check if SLA violated
        sla_violated = self._check_sla_compliance(alert, metrics)
        if sla_violated:
            self._trigger_sla_alert(alert, metrics)
        
        # Store in database for long-term tracking
        self._store_incident_record(alert, analysis, resolution_time)
    
    def _check_sla_compliance(self, alert: PipelineAlert, metrics: SLAMetrics) -> bool:
        """Check if SLA is being violated."""
        service_config = self.sla_configs.get(alert.severity.value.lower(), self.sla_configs['medium'])
        
        # Check response time
        if metrics.average_resolution_time > service_config['response_time']:
            return True
        
        # Check success rate
        if metrics.success_rate < self.alert_thresholds['success_rate'] * 100:
            return True
        
        # Check escalation rate
        if metrics.total_incidents > 10:
            escalation_rate = metrics.escalation_count / metrics.total_incidents
            if escalation_rate > self.alert_thresholds['escalation_rate']:
                return True
        
        return False
    
    def _trigger_sla_alert(self, alert: PipelineAlert, metrics: SLAMetrics):
        """Trigger an SLA violation alert."""
        logger.error(f"SLA Violation for {alert.service_name}: {metrics}")
        
        # Send to notification system
        notification = {
            'type': 'SLA_VIOLATION',
            'service': alert.service_name,
            'metrics': {
                'avg_resolution_time': metrics.average_resolution_time,
                'success_rate': metrics.success_rate,
                'escalation_rate': metrics.escalation_count / max(metrics.total_incidents, 1)
            },
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Could send to Slack, PagerDuty, etc.
        self._send_notification(notification)
    
    def _send_notification(self, notification: Dict[str, Any]):
        """Send notification to alerting systems."""
        # Implement notification logic here
        logger.info(f"SLA Alert: {notification}")
    
    def _store_incident_record(
        self,
        alert: PipelineAlert,
        analysis: DiagnosticAnalysis,
        resolution_time: float
    ):
        """Store incident record for historical analysis."""
        # In production, store in a database
        record = {
            'alert_id': alert.alert_id,
            'service': alert.service_name,
            'environment': alert.environment.value,
            'resolution_time': resolution_time,
            'confidence': analysis.confidence_score,
            'action': analysis.proposed_action,
            'timestamp': datetime.utcnow().isoformat()
        }
        logger.debug(f"Storing incident record: {record}")