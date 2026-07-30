# src/orchestrator/state.py
__all__ = ["SREWorkflowState"]

from typing import Annotated, Optional, List, Dict, Any
from typing_extensions import TypedDict
import operator
from src.models.schemas import PipelineAlert, DiagnosticAnalysis

class SREWorkflowState(TypedDict):
    """The global state managed by LangGraph and persisted in PostgreSQL."""
    
    # 1. Ingestion Phase
    alert: PipelineAlert
    
    # 2. Context Phase (Appended by RAG nodes)
    vector_context: Annotated[List[Dict[str, Any]], operator.add]
    graph_topology: Optional[Dict[str, Any]]
    
    # 3. Reasoning Phase
    analysis: Optional[DiagnosticAnalysis]
    
    # 4. Action/HITL Phase
    jira_ticket_id: Optional[str]
    human_approved: bool
    final_status: str
    
    # 5. Error Handling
    error_count: int
    error_messages: Annotated[List[str], operator.add]

