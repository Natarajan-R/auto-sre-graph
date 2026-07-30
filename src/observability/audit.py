# src/observability/audit.py
from typing import Dict, Any, Optional, List
from datetime import datetime
import json
import logging
from enum import Enum
from dataclasses import dataclass, asdict
from src.config.settings import settings

logger = logging.getLogger(__name__)

class AuditAction(str, Enum):
    ALERT_RECEIVED = "ALERT_RECEIVED"
    ALERT_FILTERED = "ALERT_FILTERED"
    CONTEXT_RETRIEVED = "CONTEXT_RETRIEVED"
    DIAGNOSIS_COMPLETE = "DIAGNOSIS_COMPLETE"
    JIRA_TICKET_CREATED = "JIRA_TICKET_CREATED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    REMEDIATION_EXECUTED = "REMEDIATION_EXECUTED"
    WORKFLOW_ERROR = "WORKFLOW_ERROR"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"

@dataclass
class AuditEvent:
    """Audit event structure."""
    event_id: str
    action: AuditAction
    actor: str
    target: str
    timestamp: datetime
    details: Dict[str, Any]
    environment: str
    source_ip: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

class AuditLogger:
    """Manages audit logging for compliance and security."""
    
    def __init__(self):
        self.audit_log_dir = "/var/log/auto-sre-graph/audit"
        self.current_log_file = None
        self._ensure_log_directory()
        self.audit_levels = {
            'CRITICAL': ['REMEDIATION_EXECUTED', 'HUMAN_APPROVED', 'WORKFLOW_ERROR'],
            'HIGH': ['JIRA_TICKET_CREATED', 'DIAGNOSIS_COMPLETE'],
            'MEDIUM': ['CONTEXT_RETRIEVED', 'WORKFLOW_COMPLETED'],
            'LOW': ['ALERT_RECEIVED', 'ALERT_FILTERED']
        }
    
    def _ensure_log_directory(self):
        """Ensure audit log directory exists."""
        import os
        os.makedirs(self.audit_log_dir, exist_ok=True)
    
    def _get_current_log_file(self) -> str:
        """Get the current audit log file."""
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        return f"{self.audit_log_dir}/audit_{date_str}.log"
    
    async def log_event(
        self,
        action: AuditAction,
        actor: str,
        target: str,
        details: Dict[str, Any],
        source_ip: Optional[str] = None
    ):
        """Log an audit event."""
        event = AuditEvent(
            event_id=self._generate_event_id(),
            action=action,
            actor=actor,
            target=target,
            timestamp=datetime.utcnow(),
            details=details,
            environment=settings.ENVIRONMENT.value,
            source_ip=source_ip
        )
        
        # Log to structured logger
        log_data = event.to_dict()
        logger.info(f"AUDIT: {json.dumps(log_data)}")
        
        # Write to audit file
        self._write_audit_entry(log_data)
        
        # Store in database for compliance
        await self._store_audit_event(log_data)
    
    def _generate_event_id(self) -> str:
        """Generate a unique event ID."""
        import uuid
        return str(uuid.uuid4())
    
    def _write_audit_entry(self, entry: Dict[str, Any]):
        """Write audit entry to file."""
        import aiofiles
        # In production, use async file writing
        log_file = self._get_current_log_file()
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    
    async def _store_audit_event(self, entry: Dict[str, Any]):
        """Store audit event in database."""
        # In production, store in a dedicated audit database
        # This is critical for compliance (HIPAA, GDPR, SOX, etc.)
        pass
    
    async def query_audit_events(
        self,
        action: Optional[AuditAction] = None,
        actor: Optional[str] = None,
        target: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query audit events for compliance reporting."""
        # In production, implement database query
        # This would return events from the audit database
        return []
    
    def get_audit_report(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> Dict[str, Any]:
        """Generate an audit report for compliance."""
        report = {
            'period': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat()
            },
            'total_events': 0,
            'events_by_action': {},
            'events_by_actor': {},
            'critical_events': [],
            'high_risk_events': []
        }
        
        # In production, this would analyze the audit data
        # Generate metrics for compliance reporting
        
        return report