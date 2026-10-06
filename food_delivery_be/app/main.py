from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import settings
from app.core.logging_middleware import RequestTracingMiddleware
from app.core.metrics import PrometheusMetricsMiddleware
from app.database import Base, engine
import app.models  # Ensures all ORM models are registered before create_all
from app.routers import (
    address_router,
    auth_router,
    cart_router,
    delivery_router,
    menu_router,
    orders_router,
    payments_router,
    restaurants_router,
    users_router,
    websockets_router,
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production-grade Food Delivery Backend API (Swiggy/Zomato clone)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Production Observability & Tracing Middlewares
app.add_middleware(RequestTracingMiddleware)
app.add_middleware(PrometheusMetricsMiddleware)

# Automatically create database tables for development
Base.metadata.create_all(bind=engine)

# Mount domain routers
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(restaurants_router)
app.include_router(menu_router)
app.include_router(cart_router)
app.include_router(address_router)
app.include_router(orders_router)
app.include_router(payments_router)
app.include_router(delivery_router)
app.include_router(websockets_router)


@app.get("/", tags=["General"])
def root():
    return {
        "project": settings.PROJECT_NAME,
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics"
    }


@app.get("/metrics", tags=["Observability & Metrics"], summary="Prometheus Application & Infrastructure Metrics")
def metrics():
    """Exposes real-time Prometheus metrics for scrapers (Grafana / Alertmanager)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health", tags=["Probes & Reliability"], summary="Comprehensive Health Check")
def health_check():
    from app.core.redis import is_redis_healthy

    db_status = "connected"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {e}"

    redis_status = "connected" if is_redis_healthy() else "disconnected"
    is_overall_healthy = (db_status == "connected" and redis_status == "connected")

    return {
        "status": "healthy" if is_overall_healthy else "degraded",
        "database": db_status,
        "redis": redis_status
    }


@app.get("/health/live", tags=["Probes & Reliability"], summary="Kubernetes Liveness Probe")
def liveness_probe():
    """K8s Liveness Probe: Confirms process is responsive."""
    return {"status": "alive"}


@app.get("/health/ready", tags=["Probes & Reliability"], summary="Kubernetes Readiness Probe")
def readiness_probe():
    """K8s Readiness Probe: Confirms DB & Redis pools are healthy before accepting ingress traffic."""
    from app.core.redis import is_redis_healthy

    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    redis_ok = is_redis_healthy()

    if not db_ok or not redis_ok:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "database": "connected" if db_ok else "unreachable",
                "redis": "connected" if redis_ok else "unreachable"
            }
        )

    return {"status": "ready", "database": "connected", "redis": "connected"}