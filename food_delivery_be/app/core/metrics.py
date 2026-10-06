import time
from typing import Callable
from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match

# -------------------------------------------------------------
# Prometheus Metrics Definitions
# -------------------------------------------------------------

# 1. HTTP Traffic & Latency Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests processed by endpoint and status code",
    ["method", "endpoint", "status_code"]
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Histogram of HTTP request processing latency in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0)
)

HTTP_ACTIVE_REQUESTS = Gauge(
    "http_active_requests",
    "Number of currently active HTTP requests being processed concurrently"
)

# 2. Business Domain Metrics
ORDERS_CREATED_TOTAL = Counter(
    "food_delivery_orders_created_total",
    "Total number of customer food delivery orders created"
)

ORDER_REVENUE_PAISE_TOTAL = Counter(
    "food_delivery_order_revenue_paise_total",
    "Total cumulative revenue transacted in paise (integers)"
)

PAYMENTS_PROCESSED_TOTAL = Counter(
    "food_delivery_payments_processed_total",
    "Total payment gateway transactions processed",
    ["status", "payment_method"]
)

DELIVERY_DISPATCHES_TOTAL = Counter(
    "food_delivery_dispatches_total",
    "Total driver delivery dispatches executed",
    ["city"]
)

ACTIVE_WS_CONNECTIONS = Gauge(
    "food_delivery_active_websocket_connections",
    "Number of active real-time WebSocket client connections"
)

CIRCUIT_BREAKER_STATE = Gauge(
    "food_delivery_circuit_breaker_state",
    "Circuit breaker state: 0=CLOSED (Normal), 1=HALF_OPEN, 2=OPEN (Tripped)",
    ["circuit_name"]
)


def get_normalized_endpoint(request: Request) -> str:
    """
    Finds the matched route pattern (e.g. '/orders/{order_id}') instead of
    raw path ('/orders/12') to prevent high-cardinality metric explosion.
    """
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL and hasattr(route, "path"):
            return route.path
    return request.url.path


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """
    Captures request latency, active request gauge, and request counters
    for all HTTP traffic passing through the application.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Exclude metrics and health endpoints from latency histograms to avoid polluting metrics
        if request.url.path in ("/metrics", "/health", "/health/live", "/health/ready"):
            return await call_next(request)

        HTTP_ACTIVE_REQUESTS.inc()
        start_time = time.time()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.time() - start_time
            HTTP_ACTIVE_REQUESTS.dec()

            endpoint = get_normalized_endpoint(request)
            method = request.method

            HTTP_REQUESTS_TOTAL.labels(
                method=method,
                endpoint=endpoint,
                status_code=str(status_code)
            ).inc()

            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)
