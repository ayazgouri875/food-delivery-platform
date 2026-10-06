import enum
import functools
import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"        # Normal: calls permitted
    HALF_OPEN = "HALF_OPEN"  # Recovery testing: single trial call permitted
    OPEN = "OPEN"            # Tripped: calls short-circuited immediately


class CircuitBreakerOpenException(Exception):
    """Raised when an operation is attempted while the circuit breaker is OPEN."""
    def __init__(self, name: str, retry_after_seconds: float):
        super().__init__(f"Circuit breaker '{name}' is OPEN. Downstream dependency is degraded.")
        self.name = name
        self.retry_after_seconds = retry_after_seconds


class CircuitBreaker:
    """
    Production-grade Circuit Breaker implementation for external dependencies
    (Payment Gateways, SMS Providers, External Geospatial APIs).
    
    Prevents cascading resource exhaustion during third-party outages.
    """
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 10.0
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_state_change = time.time()
        self.last_failure_time: Optional[float] = None

    def _update_metrics(self):
        try:
            from app.core.metrics import CIRCUIT_BREAKER_STATE
            state_map = {CircuitState.CLOSED: 0, CircuitState.HALF_OPEN: 1, CircuitState.OPEN: 2}
            CIRCUIT_BREAKER_STATE.labels(circuit_name=self.name).set(state_map[self.state])
        except Exception:
            pass

    def __call__(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            return self.call(func, *args, **kwargs)
        return wrapper

    def call(self, func: Callable, *args, **kwargs) -> Any:
        now = time.time()

        # 1. State Check: If OPEN, evaluate if recovery timeout has elapsed
        if self.state == CircuitState.OPEN:
            elapsed = now - (self.last_failure_time or now)
            if elapsed >= self.recovery_timeout_seconds:
                logger.info(f"Circuit '{self.name}' transitioning from OPEN to HALF_OPEN (Canary trial)")
                self.state = CircuitState.HALF_OPEN
                self._update_metrics()
            else:
                remaining = round(self.recovery_timeout_seconds - elapsed, 2)
                raise CircuitBreakerOpenException(self.name, remaining)

        # 2. Execute target function
        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as exc:
            self.on_failure(exc)
            raise exc

    def on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            logger.info(f"Circuit '{self.name}' canary trial succeeded! Transitioning to CLOSED.")
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self._update_metrics()
        elif self.state == CircuitState.CLOSED:
            # Gradually heal failure count on successful runs
            self.failure_count = max(0, self.failure_count - 1)

    def on_failure(self, exc: Exception):
        now = time.time()
        self.failure_count += 1
        self.last_failure_time = now
        logger.warning(f"Circuit '{self.name}' recorded failure ({self.failure_count}/{self.failure_threshold}): {exc}")

        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.error(f"Circuit '{self.name}' TRIPPED to OPEN! Short-circuiting calls for {self.recovery_timeout_seconds}s.")
            self._update_metrics()


# Global registry of named circuit breakers
_CIRCUIT_REGISTRY: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout_seconds: float = 10.0
) -> CircuitBreaker:
    if name not in _CIRCUIT_REGISTRY:
        _CIRCUIT_REGISTRY[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout_seconds=recovery_timeout_seconds
        )
    return _CIRCUIT_REGISTRY[name]
