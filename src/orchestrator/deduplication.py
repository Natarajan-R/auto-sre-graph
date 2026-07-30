# src/orchestrator/deduplication.py
from typing import Dict, Any, Optional, List
import hashlib
import json
from datetime import datetime, timedelta
import logging
from redis.asyncio import Redis
from src.config.settings import settings
from src.models.schemas import PipelineAlert

logger = logging.getLogger(__name__)

class AlertDeduplicator:
    """Prevents duplicate alert processing and aggregates similar alerts."""
    
    def __init__(self):
        self.redis_client = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD.get_secret_value() if settings.REDIS_PASSWORD else None,
            decode_responses=True,
            socket_timeout=5
        )
        self.dedup_window = 300  # 5 minutes
        self.similarity_threshold = 0.85
    
    def _generate_alert_fingerprint(self, alert: PipelineAlert) -> str:
        """Generate a unique fingerprint for the alert."""
        # Normalize the alert data
        normalized = {
            'service': alert.service_name,
            'environment': alert.environment.value,
            'error_type': self._extract_error_type(alert.error_message),
            'severity': alert.severity.value
        }
        # Create hash
        fingerprint_str = json.dumps(normalized, sort_keys=True)
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]
    
    def _extract_error_type(self, error_message: str) -> str:
        """Extract the error type from the error message."""
        import re
        # Common error patterns
        patterns = [
            r'(Timeout|ConnectionTimeout|ReadTimeout)',
            r'(Connection refused|Connection reset)',
            r'(OutOfMemory|MemoryError)',
            r'(NullPointer|NullReference)',
            r'(Authentication|Authorization|Permission)',
            r'(NotFound|404)',
            r'(BadRequest|400)',
            r'(InternalServerError|500)',
            r'(Database|SQL|DB)',
            r'(Network|DNS|Host)'
        ]
        
        for pattern in patterns:
            if re.search(pattern, error_message, re.IGNORECASE):
                return pattern.strip('()')
        
        return 'UnknownError'
    
    async def is_duplicate(self, alert: PipelineAlert) -> bool:
        fingerprint = self._generate_alert_fingerprint(alert)
        key = f"alert:dedup:{fingerprint}"
        now = datetime.utcnow().timestamp()

        existing = await self.redis_client.get(key)
        if existing:
            count_key = f"alert:count:{fingerprint}"
            count = await self.redis_client.incr(count_key)
            await self.redis_client.expire(count_key, self.dedup_window)
            logger.info(f"Duplicate alert detected for {alert.service_name}. Count: {count}")
            return True

        await self.redis_client.setex(
            key,
            self.dedup_window,
            json.dumps({
                'alert_id': alert.alert_id,
                'service': alert.service_name,
                'timestamp': now,
                'count': 1
            })
        )

        count_key = f"alert:count:{fingerprint}"
        await self.redis_client.setex(count_key, self.dedup_window, 1)
        return False
    
    async def get_aggregated_alert_info(self, alert: PipelineAlert) -> Dict[str, Any]:
        fingerprint = self._generate_alert_fingerprint(alert)
        count_key = f"alert:count:{fingerprint}"

        count = await self.redis_client.get(count_key)
        if count:
            first = await self.redis_client.get(f"alert:first:{fingerprint}")
            return {
                'is_aggregated': int(count) > 1,
                'occurrence_count': int(count),
                'first_occurrence': first
            }

        return {'is_aggregated': False, 'occurrence_count': 0}