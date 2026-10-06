import time
import uuid
import pytest
import requests
from sqlalchemy.orm import Session

from app.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException, CircuitState, get_circuit_breaker
from app.core.security import create_access_token, hash_password
from app.database.session import SessionLocal
from app.models.address import Address
from app.models.cart import Cart, CartItem
from app.models.menu import MenuCategory, MenuItem
from app.models.order import Order, OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole

BASE_HTTP_URL = "http://127.0.0.1:8000"


def get_token(user_id: int, role: str) -> str:
    return create_access_token(data={"sub": str(user_id), "role": role})


def test_01_liveness_probe():
    """Verify K8s Liveness Probe endpoint returns 200 and attaches X-Request-ID."""
    url = f"{BASE_HTTP_URL}/health/live"
    res = requests.get(url, timeout=5)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["status"] == "alive"
    assert "X-Request-ID" in res.headers, "X-Request-ID header missing from response"
    assert res.headers["X-Request-ID"].startswith("req_")
    print("✅ Test 1 Passed: Liveness probe healthy with generated Correlation ID")


def test_02_readiness_probe():
    """Verify K8s Readiness Probe validates PostgreSQL and Redis pool health."""
    url = f"{BASE_HTTP_URL}/health/ready"
    res = requests.get(url, timeout=5)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
    assert data["redis"] == "connected"
    print("✅ Test 2 Passed: Readiness probe confirmed DB and Redis connections")


def test_03_correlation_id_propagation():
    """Verify custom X-Request-ID sent by client is propagated back in response."""
    custom_cid = f"test-trace-{uuid.uuid4().hex[:12]}"
    url = f"{BASE_HTTP_URL}/health/live"
    headers = {"X-Request-ID": custom_cid}
    res = requests.get(url, headers=headers, timeout=5)
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID") == custom_cid, (
        f"Expected echoed {custom_cid}, got {res.headers.get('X-Request-ID')}"
    )
    print(f"✅ Test 3 Passed: Custom Correlation ID successfully propagated: {custom_cid}")


def test_04_prometheus_metrics_endpoint():
    """Verify /metrics exposes Prometheus formatted counters, gauges, and histograms."""
    url = f"{BASE_HTTP_URL}/metrics"
    res = requests.get(url, timeout=5)
    assert res.status_code == 200
    assert "text/plain" in res.headers.get("Content-Type", "")

    body = res.text
    # Verify standard metrics and custom business metrics exist in scrape output
    expected_metrics = [
        "http_requests_total",
        "http_request_duration_seconds",
        "http_active_requests",
        "food_delivery_orders_created_total",
        "food_delivery_order_revenue_paise_total",
        "food_delivery_payments_processed_total",
        "food_delivery_circuit_breaker_state",
    ]
    for metric in expected_metrics:
        assert metric in body, f"Prometheus scrape missing expected metric: {metric}"
    print("✅ Test 4 Passed: /metrics exposes valid Prometheus telemetry data")


def test_05_circuit_breaker_state_machine():
    """
    Directly tests the CircuitBreaker state transitions:
    CLOSED (normal) -> failures >= threshold -> OPEN (tripped) -> timeout -> HALF_OPEN (trial) -> success -> CLOSED.
    """
    breaker = CircuitBreaker("test_isolated_service", failure_threshold=3, recovery_timeout_seconds=1.0)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0

    # Simulate 2 failures (under threshold)
    def failing_fn():
        raise ConnectionError("Upstream timeout")

    for i in range(2):
        with pytest.raises(ConnectionError):
            breaker.call(failing_fn)
        assert breaker.state == CircuitState.CLOSED

    assert breaker.failure_count == 2

    # 3rd failure trips the breaker to OPEN
    with pytest.raises(ConnectionError):
        breaker.call(failing_fn)
    assert breaker.state == CircuitState.OPEN
    print("✅ Test 5a: Circuit Breaker transitioned CLOSED -> OPEN after 3 consecutive failures")

    # While OPEN, any call is immediately rejected with CircuitBreakerOpenException
    with pytest.raises(CircuitBreakerOpenException) as exc_info:
        breaker.call(lambda: "never called")
    assert "OPEN" in str(exc_info.value)
    print("✅ Test 5b: Circuit Breaker successfully short-circuited call while OPEN")

    # Wait for recovery timeout (1.0 second) to elapse
    time.sleep(1.1)

    # First call in HALF_OPEN: let it succeed to prove recovery
    def successful_fn():
        return "recovering"

    res = breaker.call(successful_fn)
    assert res == "recovering"
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0
    print("✅ Test 5c: Circuit Breaker canary call succeeded, transitioned HALF_OPEN -> CLOSED")


def test_06_circuit_breaker_via_payments_api():
    """
    Test Circuit Breaker protection on POST /payments API.
    Trips the gateway using simulate_gateway_outage=True and validates HTTP 502 -> HTTP 503 short-circuit.
    """
    db: Session = SessionLocal()
    ts = int(time.time() * 1000)

    # Setup customer and confirmed order for testing
    customer = User(
        email=f"cb_customer_{ts}@test.com",
        name=f"CB Tester {ts}",
        password_hash=hash_password("pass123"),
        role=UserRole.CUSTOMER
    )
    db.add(customer)
    db.flush()

    restaurant_owner = User(
        email=f"cb_owner_{ts}@test.com",
        name=f"CB Resto {ts}",
        password_hash=hash_password("pass123"),
        role=UserRole.RESTAURANT
    )
    db.add(restaurant_owner)
    db.flush()

    restaurant = Restaurant(
        owner_id=restaurant_owner.id,
        name=f"Circuit Breaker Diner {ts}",
        address_line="10 Circuit Lane",
        city="Bengaluru_CB",
        is_active=True
    )
    db.add(restaurant)
    db.flush()

    address = Address(
        user_id=customer.id,
        title="Work",
        address_line="10 Tech Park",
        city="Bengaluru_CB",
        postal_code="560100"
    )
    db.add(address)
    db.flush()

    token = get_token(customer.id, "customer")
    headers = {"Authorization": f"Bearer {token}"}

    # Reset payment_gateway breaker for a clean test
    gateway_breaker = get_circuit_breaker("payment_gateway", failure_threshold=3, recovery_timeout_seconds=2.0)
    gateway_breaker.state = CircuitState.CLOSED
    gateway_breaker.failure_count = 0

    # Create 4 orders to test repeated simulated gateway outages
    order_ids = []
    for i in range(4):
        order = Order(
            user_id=customer.id,
            restaurant_id=restaurant.id,
            delivery_address_id=address.id,
            delivery_address_snapshot="10 Tech Park, Bengaluru_CB",
            status=OrderStatus.CREATED,
            subtotal=15000,
            delivery_fee=3000,
            grand_total=18000,
            idempotency_key=f"cb_order_idem_{ts}_{i}"
        )
        db.add(order)
        db.flush()
        order_ids.append(order.id)
    db.commit()
    db.close()

    # Call 1: Outage simulated -> 502 Bad Gateway
    r1 = requests.post(
        f"{BASE_HTTP_URL}/payments",
        json={
            "order_id": order_ids[0],
            "payment_method": "UPI",
            "idempotency_key": f"pay_cb_{ts}_1",
            "simulate_gateway_outage": True
        },
        headers=headers,
        timeout=5
    )
    assert r1.status_code == 502, f"Expected 502, got {r1.status_code}: {r1.text}"

    # Call 2: Outage simulated -> 502 Bad Gateway
    r2 = requests.post(
        f"{BASE_HTTP_URL}/payments",
        json={
            "order_id": order_ids[1],
            "payment_method": "UPI",
            "idempotency_key": f"pay_cb_{ts}_2",
            "simulate_gateway_outage": True
        },
        headers=headers,
        timeout=5
    )
    assert r2.status_code == 502, f"Expected 502, got {r2.status_code}: {r2.text}"

    # Call 3: Outage simulated -> 502 Bad Gateway (Circuit trips to OPEN)
    r3 = requests.post(
        f"{BASE_HTTP_URL}/payments",
        json={
            "order_id": order_ids[2],
            "payment_method": "UPI",
            "idempotency_key": f"pay_cb_{ts}_3",
            "simulate_gateway_outage": True
        },
        headers=headers,
        timeout=5
    )
    assert r3.status_code == 502, f"Expected 502, got {r3.status_code}: {r3.text}"

    # Call 4: Circuit is now OPEN! Request must be immediately rejected with 503 Service Unavailable
    r4 = requests.post(
        f"{BASE_HTTP_URL}/payments",
        json={
            "order_id": order_ids[3],
            "payment_method": "UPI",
            "idempotency_key": f"pay_cb_{ts}_4",
            "simulate_gateway_outage": False  # Even normal requests fail fast while OPEN!
        },
        headers=headers,
        timeout=5
    )
    assert r4.status_code == 503, f"Expected 503 Service Unavailable, got {r4.status_code}: {r4.text}"
    assert "Retry-After" in r4.headers, "Retry-After header missing on 503 response"
    assert "Circuit Breaker OPEN" in r4.json()["detail"]
    print("✅ Test 6a Passed: API returned HTTP 503 with Retry-After when Circuit Breaker is OPEN")

    # Verify metrics reflects OPEN state (2.0)
    metrics_res = requests.get(f"{BASE_HTTP_URL}/metrics", timeout=5)
    assert 'food_delivery_circuit_breaker_state{circuit_name="payment_gateway"} 2.0' in metrics_res.text
    print("✅ Test 6b Passed: Prometheus metric correctly reports circuit breaker state as 2.0 (OPEN)")

    # Reset breaker back to CLOSED for normal server operations
    gateway_breaker.state = CircuitState.CLOSED
    gateway_breaker.failure_count = 0
    gateway_breaker._update_metrics()


if __name__ == "__main__":
    test_01_liveness_probe()
    test_02_readiness_probe()
    test_03_correlation_id_propagation()
    test_04_prometheus_metrics_endpoint()
    test_05_circuit_breaker_state_machine()
    test_06_circuit_breaker_via_payments_api()
    print("\n🎉 ALL STAGE 5 OBSERVABILITY & FAULT TOLERANCE TESTS PASSED SUCCESSFULLY! 🎉")
