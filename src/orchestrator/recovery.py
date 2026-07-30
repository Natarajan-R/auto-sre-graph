# src/orchestrator/recovery.py
from typing import TypeVar, Callable, Awaitable, Any, Optional
import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
import random

logger = logging.getLogger(__name__)

class CircuitBreakerState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: int = 60
    half_open_max_calls: int = 3
    time_window: int = 300  # 5 minutes

class CircuitBreaker:
    """Implements circuit breaker pattern for external service calls."""
    
    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_calls = 0
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a function with circuit breaker protection."""
        async with self._lock:
            # Check if circuit is open
            if self.state == CircuitBreakerState.OPEN:
                if self._should_attempt_recovery():
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info(f"Circuit {self.name} entering HALF_OPEN state")
                else:
                    raise CircuitBreakerOpenError(f"Circuit {self.name} is OPEN")
            
            try:
                result = await func(*args, **kwargs)
                
                # Success
                if self.state == CircuitBreakerState.HALF_OPEN:
                    self.half_open_calls += 1
                    if self.half_open_calls >= self.config.half_open_max_calls:
                        self._reset()
                        logger.info(f"Circuit {self.name} reset to CLOSED")
                else:
                    self._reset()
                
                return result
            
            except Exception as e:
                self._record_failure()
                raise
    
    def _record_failure(self):
        """Record a failure."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        # Check if we should open the circuit
        if self.failure_count >= self.config.failure_threshold:
            if self.state == CircuitBreakerState.CLOSED:
                self.state = CircuitBreakerState.OPEN
                logger.warning(f"Circuit {self.name} opened due to {self.failure_count} failures")
            elif self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.OPEN
                logger.warning(f"Circuit {self.name} opened during HALF_OPEN state")
    
    def _reset(self):
        """Reset the circuit breaker."""
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitBreakerState.CLOSED
        self.half_open_calls = 0
    
    def _should_attempt_recovery(self) -> bool:
        """Check if we should attempt recovery."""
        if not self.last_failure_time:
            return True
        
        time_since_failure = (datetime.utcnow() - self.last_failure_time).total_seconds()
        return time_since_failure > self.config.recovery_timeout

class CircuitBreakerOpenError(Exception):
    """Raised when a circuit breaker is open."""
    pass

class RetryHandler:
    """Handles retry operations with exponential backoff."""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        **kwargs
    ) -> Any:
        """Execute a function with retry logic."""
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            
            except Exception as e:
                last_exception = e
                
                # Check if we should retry
                if should_retry and not should_retry(e):
                    raise
                
                if attempt >= self.max_retries:
                    break
                
                # Calculate delay with exponential backoff
                delay = self.base_delay * (self.exponential_base ** attempt)
                delay = min(delay, self.max_delay)
                
                if self.jitter:
                    delay *= random.uniform(0.8, 1.2)
                
                logger.warning(
                    f"Retry attempt {attempt + 1}/{self.max_retries} "
                    f"after {delay:.2f}s for {func.__name__}: {e}"
                )
                
                await asyncio.sleep(delay)
        
        raise last_exception

class ErrorRecoveryManager:
    """Manages error recovery strategies for workflow failures."""
    
    def __init__(self):
        self.retry_handler = RetryHandler(max_retries=3, base_delay=2.0)
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.error_handlers: Dict[str, Callable] = {}
    
    def get_circuit_breaker(self, name: str) -> CircuitBreaker:
        """Get or create a circuit breaker."""
        if name not in self.circuit_breakers:
            self.circuit_breakers[name] = CircuitBreaker(name)
        return self.circuit_breakers[name]
    
    def register_error_handler(self, error_type: str, handler: Callable):
        """Register an error handler for specific error types."""
        self.error_handlers[error_type] = handler
    
    async def execute_with_recovery(
        self,
        func: Callable,
        error_type: str,
        *args,
        **kwargs
    ) -> Any:
        """Execute a function with recovery strategies."""
        try:
            circuit_breaker = self.get_circuit_breaker(error_type)
            return await circuit_breaker.call(self.retry_handler.execute_with_retry, func, *args, **kwargs)
        
        except Exception as e:
            # Try to recover using registered handler
            if error_type in self.error_handlers:
                logger.info(f"Attempting recovery for {error_type}: {e}")
                try:
                    return await self.error_handlers[error_type](*args, **kwargs)
                except Exception as recovery_error:
                    logger.error(f"Recovery failed for {error_type}: {recovery_error}")
                    raise
            
            # If no recovery handler, just raise
            raise