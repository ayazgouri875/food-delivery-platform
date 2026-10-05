# Food Delivery Platform Backend (Swiggy / Zomato Clone)

A production-grade, modular monolith food delivery backend designed to showcase backend engineering, distributed systems concepts, concurrency controls, caching, and event-driven architecture.

---

## 🛠 Tech Stack

- **Framework**: Python 3.13 / FastAPI
- **Database**: PostgreSQL with SQLAlchemy 2.0+ ORM
- **Data Validation & Settings**: Pydantic v2 & Pydantic-Settings
- **Authentication**: JWT (JSON Web Tokens) with PyJWT & Bcrypt password hashing
- **Roadmap Integrations**: Redis (Cache-Aside, Rate Limiting, Distributed Locks), Kafka (Event Streaming), Docker

---

## 🏗 Architecture Roadmap

```
Stage 1: Modular Monolith (FastAPI + PostgreSQL) [CURRENT]
Stage 2: Caching & Rate Limiting (Redis)
Stage 3: High Concurrency, Row-level Locking & Idempotency
Stage 4: Asynchronous Event Streaming (Apache Kafka)
Stage 5: Observability, Metrics & Docker Deployment
```

---

## 📁 Project Structure

```text
food-delivery-platform/
└── food_delivery_be/
    ├── app/
    │   ├── core/           # Config settings & Bcrypt / JWT security
    │   ├── database/       # SQLAlchemy engine, session maker & Base
    │   ├── dependencies/   # FastAPI DI: get_db, get_current_user, require_role
    │   ├── models/         # SQLAlchemy ORM models (User, Role, etc.)
    │   ├── routers/        # API route handlers (Auth, Users)
    │   ├── schemas/        # Pydantic schemas for requests/responses
    │   └── main.py         # Application entry point & router mounting
    ├── requirements.txt
    ├── .env.example
    └── .gitignore
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

```bash
uvicorn app.main:app --reload
```

Interactive API documentation will be available at:
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Health Check**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 🔐 Auth & Role-Based Access Control (RBAC)

The platform supports 4 distinct user roles:
- `CUSTOMER` — Order food, manage cart, track delivery
- `RESTAURANT` — Manage menus, accept/prepare orders
- `DELIVERY_PARTNER` — Accept delivery tasks, update location/status
- `ADMIN` — System administration, restaurant approvals, user status
