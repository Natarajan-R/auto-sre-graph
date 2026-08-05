# src/models/schemas.py
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator, ConfigDict
import re

class Environment(str, Enum):
    SIT = "SIT"
    UAT = "UAT"
    PROD = "PROD"
    DEV = "DEV"

class AlertSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

class PipelineAlert(BaseModel):
    """Contract for incoming telemetry and deployment failures."""
    model_config = ConfigDict(extra="forbid")
    
    alert_id: str = Field(..., description="Unique ADO Pipeline Run ID or APM Trace ID", min_length=1, max_length=100)
    environment: Environment = Field(..., description="Target environment for the release")
    service_name: str = Field(..., description="The microservice triggering the alert", min_length=1, max_length=100)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    error_message: str = Field(..., min_length=10, max_length=10000, description="The top-level exception message")
    stack_trace: Optional[str] = Field(None, max_length=100000, description="Raw stack trace, if available")
    git_commit_hash: Optional[str] = Field(None, min_length=7, max_length=40, pattern=r'^[a-fA-F0-9]{7,40}$')
    severity: AlertSeverity = Field(default=AlertSeverity.HIGH, description="Alert severity level")
    service_version: Optional[str] = Field(None, max_length=50)
    additional_context: Optional[Dict[str, Any]] = Field(None, description="Additional context from the pipeline")
    
    @validator('error_message')
    def strip_excess_whitespace(cls, v):
        # Remove excessive whitespace and control characters
        v = re.sub(r'\s+', ' ', v).strip()
        return v
    
    @validator('stack_trace', pre=True)
    def strip_ansi(cls, v):
        if v is None:
            return None
        # Remove ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', v)

class ActionType(str, Enum):
    ROLLBACK = "ROLLBACK"
    RESTART_SERVICE = "RESTART_SERVICE"
    ESCALATE_ONLY = "ESCALATE_ONLY"
    SCALE_UP = "SCALE_UP"
    CONFIG_UPDATE = "CONFIG_UPDATE"

class DiagnosticAnalysis(BaseModel):
    """Strict contract enforcing the LLM's diagnostic reasoning."""
    model_config = ConfigDict(extra="forbid")
    
    root_cause_summary: str = Field(
        ..., 
        max_length=250, 
        description="One-sentence summary of why the failure occurred."
    )
    detailed_analysis: Optional[str] = Field(
        None,
        max_length=2000,
        description="Detailed analysis with reasoning steps."
    )
    historical_matches_found: bool = Field(
        ..., 
        description="True if similar past incidents were found via Vector RAG."
    )
    historical_match_ids: Optional[List[str]] = Field(
        default_factory=list,
        description="IDs of similar historical incidents found."
    )
    upstream_dependencies: List[str] = Field(
        default_factory=list, 
        description="Impacted services retrieved via Neo4j GraphRAG."
    )
    downstream_dependencies: List[str] = Field(
        default_factory=list,
        description="Services that depend on this service."
    )
    confidence_score: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Agent's confidence in the root cause hypothesis."
    )
    proposed_action: ActionType = Field(
        ..., 
        description="The deterministic action the workflow should take next."
    )
    remediation_script: Optional[str] = Field(
        None, 
        max_length=5000,
        description="The exact bash/CLI command to execute the fix, if applicable."
    )
    estimated_impact: Optional[str] = Field(
        None,
        max_length=500,
        description="Estimated impact of the failure and remediation."
    )
    alternative_actions: Optional[List[str]] = Field(
        default_factory=list,
        description="Alternative remediation actions if the primary fails."
    )
    
    @validator('confidence_score')
    def validate_confidence(cls, v):
        if v < 0 or v > 1:
            raise ValueError('Confidence score must be between 0 and 1')
        return round(v, 4)

class JiraTicketDraft(BaseModel):
    """Contract for payload sent to the Atlassian Jira API."""
    model_config = ConfigDict(extra="forbid")
    
    project_key: str = Field(default="SRE", max_length=10, min_length=2)
    issue_type: str = Field(default="Incident", max_length=50)
    summary: str = Field(..., max_length=255, min_length=1)
    description: str = Field(
        ..., 
        description="Markdown formatted description containing the stack trace and LLM analysis.",
        max_length=65535
    )
    priority: str = Field(..., description="Mapped from the LLM's confidence_score and environment.")
    labels: List[str] = Field(default_factory=list, max_items=20)
    assignee_id: Optional[str] = Field(None, max_length=100)
    environment: Optional[str] = Field(None, max_length=50)
    affected_service: Optional[str] = Field(None, max_length=100)
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    proposed_action: Optional[str] = Field(None, max_length=50)
    
    @validator('priority')
    def validate_priority(cls, v):
        valid_priorities = ['Blocker', 'Critical', 'High', 'Medium', 'Low']
        if v not in valid_priorities:
            raise ValueError(f'Priority must be one of {valid_priorities}')
        return v
    
    @validator('labels')
    def validate_labels(cls, v):
        # Ensure labels are lowercase alphanumeric
        cleaned = []
        for label in v:
            cleaned.append(re.sub(r'[^a-zA-Z0-9_-]', '', label.lower()))
        return list(set(cleaned))  # Remove duplicates
