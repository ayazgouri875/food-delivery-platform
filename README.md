# Food Delivery Platform Backend (Swiggy / Zomato Clone)

A production-grade, modular monolith food delivery backend designed to showcase backend engineering, distributed systems concepts, concurrency controls, caching, and event-driven architecture.

---

## 🛠 Tech Stack

- **Framework**: Python 3.13 / FastAPI (Async ASGI)
- **Database**: PostgreSQL 16 with SQLAlchemy 2.0+ ORM
- **In-Memory Cache & Event Bus**: Redis 7 (Cache-Aside, Distributed Lock with Lua scripts, Pub/Sub, Geospatial `GEOADD`)
- **Real-Time Streaming**: Native WebSockets (`ws://...`) with connection lifecycle and audit replay
- **Observability**: Prometheus (`/metrics`), Structured JSON Request Tracing (`X-Request-ID`), Kubernetes Probes (`/health/live`, `/health/ready`)
- **Fault Tolerance**: 3-State Circuit Breaker Pattern (`CLOSED`, `OPEN`, `HALF_OPEN`) with Canary Trials
- **Containerization**: Multi-stage Dockerfile (non-root `appuser`) & Docker Compose orchestration
- **Data Validation & Settings**: Pydantic v2 & Pydantic-Settings
- **Authentication**: JWT (JSON Web Tokens) with PyJWT & Bcrypt password hashing

---

## 🏗 Architecture Roadmap

```
Stage 1: Modular Monolith (FastAPI + PostgreSQL 16, 13 Tables, RBAC)           [COMPLETED]
Stage 2: Caching & Rate Limiting (Redis Cache-Aside, SCAN Invalidation)        [COMPLETED]
Stage 3: High Concurrency, Distributed Locks & Checkout Idempotency            [COMPLETED]
Stage 4: Real-Time Redis Pub/Sub, WebSockets & Driver Geolocation Telemetry    [COMPLETED]
Stage 5: Reliability, Prometheus Metrics, Circuit Breaker & Docker Stack       [COMPLETED]
```

Full engineering documentation:
- 📖 [architecture.md](architecture.md) — Comprehensive System Design, Mathematical Models & Invariants
- 📖 [implementation.md](implementation.md) — Endpoint Directory, Source File Maps & Verification Matrices

---

## 📁 Project Structure

```text
food-delivery-platform/
├── docker-compose.yml          # Postgres 16 + Redis 7 + API + Prometheus 9090
├── architecture.md             # System design & concurrency specifications
├── implementation.md           # API catalog & test verification matrix
├── monitoring/
│   └── prometheus.yml          # Prometheus scraper configuration
└── food_delivery_be/
    ├── Dockerfile              # Multi-stage security hardened container
    ├── requirements.txt
    ├── app/
    │   ├── core/               # Redis, Locks, Events, Metrics, Circuit Breakers, Tracing
    │   ├── database/           # SQLAlchemy engine, session maker & Base
    │   ├── dependencies/       # FastAPI DI: get_db, get_current_user, require_role
    │   ├── models/             # 13 SQLAlchemy ORM domain models
    │   ├── routers/            # Domain route controllers & WebSocket endpoints
    │   ├── schemas/            # Pydantic request / response validation schemas
    │   ├── services/           # Telemetry & decoupled Notification services
    │   └── main.py             # FastAPI entrypoint, probes & metrics
    └── tests/
        ├── test_concurrency.py            # Stage 3: Multi-threaded stress test
        ├── test_stage4_events.py          # Stage 4: Real-time WebSocket lifecycle
        └── test_stage5_observability.py   # Stage 5: Metrics, Probes & Circuit Breaker
```

---

## 🚀 Getting Started

### 1. Clone & Setup Virtual Environment

```bash
cd food_delivery_be
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Database

Ensure PostgreSQL is running and create the database:

```bash
psql -U postgres -c "CREATE DATABASE food_delivery;"
```

### 3. Run the Development Server

**Option A: Run with Docker Compose (Recommended)**
```bash
docker compose up --build
```
This boots PostgreSQL 16, Redis 7, FastAPI Backend API, and Prometheus 9090 scraper in one command!

**Option B: Run Locally with Uvicorn**
```bash
uvicorn app.main:app --reload
```

Interactive API documentation and monitoring endpoints:
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Prometheus Metrics**: [http://127.0.0.1:8000/metrics](http://127.0.0.1:8000/metrics)
- **Prometheus UI**: [http://127.0.0.1:9090](http://127.0.0.1:9090)
- **Liveness Probe**: [http://127.0.0.1:8000/health/live](http://127.0.0.1:8000/health/live)
- **Readiness Probe**: [http://127.0.0.1:8000/health/ready](http://127.0.0.1:8000/health/ready)

---

## 🧪 Automated Test Verification

Run all modular integration and concurrency stress test suites:

```bash
cd food_delivery_be

# Stage 3: Concurrency, Row Locks & Idempotency Stress Test
python3 tests/test_concurrency.py

# Stage 4: WebSockets, Pub/Sub & Driver Telemetry E2E Test
python3 tests/test_stage4_events.py

# Stage 5: Prometheus Scrape, Tracing & Circuit Breaker Test
python3 tests/test_stage5_observability.py
```

---

## 🔐 Auth & Role-Based Access Control (RBAC)

The platform supports 4 distinct user roles:
- `CUSTOMER` — Order food, manage cart, track delivery
- `RESTAURANT` — Manage menus, accept/prepare orders
- `DELIVERY_PARTNER` — Accept delivery tasks, update location/status
- `ADMIN` — System administration, restaurant approvals, user status

