# src/observability/cost_manager.py
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging
from collections import defaultdict
import json
from src.config.settings import settings

logger = logging.getLogger(__name__)

class CostManager:
    """Manages and optimizes LLM usage costs."""
    
    def __init__(self):
        self.cost_tiers = {
            'gpt-4': {'input': 0.03, 'output': 0.06},  # per 1K tokens
            'gpt-3.5-turbo': {'input': 0.001, 'output': 0.002},
            'claude-3-opus': {'input': 0.015, 'output': 0.075},
            'claude-3-sonnet': {'input': 0.003, 'output': 0.015}
        }
        self.usage_data = defaultdict(list)
        self.budget_limit = 1000.0  # Monthly budget in USD
        self.current_month_usage = 0.0
        self._load_usage_data()
    
    def _load_usage_data(self):
        """Load usage data from storage."""
        # In production, load from database or file
        pass
    
    def record_usage(self, model: str, input_tokens: int, output_tokens: int):
        """Record LLM usage for cost tracking."""
        if model not in self.cost_tiers:
            model = 'gpt-3.5-turbo'  # Default to cheapest if unknown
        
        cost = (
            (input_tokens / 1000) * self.cost_tiers[model]['input'] +
            (output_tokens / 1000) * self.cost_tiers[model]['output']
        )
        
        self.current_month_usage += cost
        
        record = {
            'timestamp': datetime.utcnow().isoformat(),
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cost': cost,
            'environment': settings.ENVIRONMENT.value
        }
        
        self.usage_data[model].append(record)
        
        # Check budget
        if self.current_month_usage > self.budget_limit * 0.9:
            logger.warning(f"LLM budget approaching limit: ${self.current_month_usage:.2f}")
        
        # In production, store in database
        self._store_usage_record(record)
    
    def _store_usage_record(self, record: Dict[str, Any]):
        """Store usage record in database."""
        # Implement storage logic
        pass
    
    def optimize_model_selection(self, required_complexity: str = 'medium') -> str:
        """Select the most cost-effective model for the task."""
        if settings.ENVIRONMENT.value in ['DEV', 'SIT']:
            # Use cheaper models in lower environments
            if required_complexity == 'high':
                return 'gpt-3.5-turbo'
            return 'gpt-3.5-turbo'
        
        # Production optimization
        if self.current_month_usage > self.budget_limit * 0.8:
            # Budget constraint - use cheaper models
            if required_complexity == 'high':
                return 'gpt-3.5-turbo'
            return 'gpt-3.5-turbo'
        
        return 'gpt-4' if required_complexity == 'high' else 'gpt-3.5-turbo'
    
    def get_cost_report(self, period: str = 'month') -> Dict[str, Any]:
        """Generate a cost report."""
        now = datetime.utcnow()
        
        # Calculate costs for the period
        total_cost = 0
        model_breakdown = defaultdict(float)
        environment_costs = defaultdict(float)
        
        for model, records in self.usage_data.items():
            for record in records:
                record_time = datetime.fromisoformat(record['timestamp'])
                
                # Filter by period
                if period == 'month' and record_time.month != now.month:
                    continue
                elif period == 'week' and (now - record_time).days > 7:
                    continue
                
                cost = record['cost']
                total_cost += cost
                model_breakdown[model] += cost
                environment_costs[record.get('environment', 'unknown')] += cost
        
        return {
            'period': period,
            'total_cost': total_cost,
            'model_breakdown': dict(model_breakdown),
            'environment_breakdown': dict(environment_costs),
            'budget_remaining': self.budget_limit - total_cost,
            'budget_used_percent': (total_cost / self.budget_limit) * 100,
            'timestamp': now.isoformat()
        }
    
    def should_cache_result(self, confidence: float, complexity: str = 'medium') -> bool:
        """Determine if a result should be cached to save costs."""
        if settings.ENVIRONMENT.value == 'PROD':
            # Cache high-confidence results
            return confidence > 0.8
        else:
            # Cache more aggressively in lower environments
            return confidence > 0.7
    
    def get_token_optimization_tips(self) -> List[str]:
        """Get tips for optimizing token usage."""
        tips = []
        
        # Analyze recent usage
        total_tokens = 0
        for model, records in self.usage_data.items():
            for record in records[-100:]:  # Last 100 requests
                total_tokens += record.get('input_tokens', 0)
        
        if total_tokens > 100000:
            tips.append("Consider reducing prompt size by summarizing context")
            tips.append("Use more efficient models for simple tasks")
            tips.append("Implement stricter filtering before LLM processing")
        
        if len(tips) == 0:
            tips.append("Token usage is within optimal range")
        
        return tips