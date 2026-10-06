# System Architecture: Food Delivery Platform (Stages 1 & 2)

This document provides a comprehensive structural and behavioral breakdown of the **Food Delivery Platform Backend**, built using **FastAPI**, **PostgreSQL**, **Redis**, **SQLAlchemy 2.0+**, **Pydantic v2**, and **Bcrypt/JWT**.

---

## 1. High-Level Architecture Overview

The system is architected as a **Layered Modular Monolith with Distributed Caching**. Each domain is isolated into its own models, schemas, and routers, while sharing common infrastructure (database sessions, security utilities, and Redis caching).

```mermaid
graph TD
    Client[Mobile / Web Client] -->|HTTP / JSON + Bearer JWT| APIGateway[FastAPI Layer: main.py]

    subgraph "FastAPI Modular Routing Layer"
        APIGateway --> R_Auth[routers/auth.py]
        APIGateway --> R_Users[routers/users.py]
        APIGateway --> R_Rest[routers/restaurants.py]
        APIGateway --> R_Menu[routers/menu.py]
        APIGateway --> R_Cart[routers/cart.py]
        APIGateway --> R_Addr[routers/address.py]
        APIGateway --> R_Order[routers/orders.py]
        APIGateway --> R_Pay[routers/payments.py]
        APIGateway --> R_Deliv[routers/delivery.py]
    end

    subgraph "Dependency Injection & Distributed Controls"
        Dep_Auth[dependencies/auth.py: get_current_user, require_role]
        Dep_DB[dependencies/database.py: get_db]
        Dep_Rate[dependencies/rate_limiter.py: rate_limit]
        Sec[core/security.py: Bcrypt + PyJWT]
        Conf[core/config.py: Settings]
    end

    R_Auth -.-> Dep_DB
    R_Auth -.-> Sec
    R_Auth -.-> Dep_Rate
    R_Rest -.-> Dep_Auth
    R_Menu -.-> Dep_Auth
    R_Cart -.-> Dep_Auth
    R_Order -.-> Dep_Auth
    R_Pay -.-> Dep_Auth
    R_Deliv -.-> Dep_Auth

    subgraph "Distributed Caching Layer (Redis 8+)"
        RedisClient[core/redis.py: Connection Pool]
        Redis[(Redis In-Memory Store)]
    end

    R_Rest -->|Cache-Aside / Read| RedisClient
    R_Menu -->|Evict / Invalidate| RedisClient
    Dep_Rate -->|Atomic INCR & EXPIRE| RedisClient
    RedisClient --> Redis

    subgraph "Data Persistence Layer (SQLAlchemy ORM)"
        DB_Sess[database/session.py: Connection Pool]
        Models[models/*.py: 13 Relational Tables]
    end

    Dep_DB --> DB_Sess
    DB_Sess --> PostgreSQL[(PostgreSQL Database: food_delivery)]
```

---

## 2. Directory Structure & File Mapping

| Directory / Layer | Purpose | Exact File Locations |
| :--- | :--- | :--- |
| **Core Configuration & Infrastructure** | Environment variables, cryptographic hashing, JWT tokens, and Redis client | [app/core/config.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/core/config.py)<br>[app/core/security.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/core/security.py)<br>[app/core/redis.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/core/redis.py) |
| **Database Engine** | Connection pool, declarative base, and session factory | [app/database/base.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/database/base.py)<br>[app/database/session.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/database/session.py) |
| **ORM Models** | 13 Relational Database Tables | [app/models/user.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/user.py)<br>[app/models/restaurant.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/restaurant.py)<br>[app/models/menu.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/menu.py)<br>[app/models/cart.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/cart.py)<br>[app/models/address.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/address.py)<br>[app/models/order.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/order.py)<br>[app/models/payment.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/payment.py)<br>[app/models/delivery.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/delivery.py) |
| **Pydantic Schemas** | Request validation and response serialization | [app/schemas/user.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/schemas/user.py)<br>[app/schemas/restaurant.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/schemas/restaurant.py)<br>[app/schemas/menu.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/schemas/menu.py)<br>[app/schemas/cart.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/schemas/cart.py)<br>[app/schemas/address.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/schemas/address.py)<br>[app/schemas/order.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/schemas/order.py)<br>[app/schemas/payment.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/schemas/payment.py)<br>[app/schemas/delivery.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/schemas/delivery.py) |
| **FastAPI Dependencies** | Request-scoped DB sessions, JWT extraction, RBAC, and Redis rate limiting | [app/dependencies/database.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/dependencies/database.py)<br>[app/dependencies/auth.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/dependencies/auth.py)<br>[app/dependencies/rate_limiter.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/dependencies/rate_limiter.py) |
| **Domain Routers** | HTTP controllers and business logic controllers | [app/routers/auth.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/auth.py)<br>[app/routers/users.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/users.py)<br>[app/routers/restaurants.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/restaurants.py)<br>[app/routers/menu.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/menu.py)<br>[app/routers/cart.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/cart.py)<br>[app/routers/address.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/address.py)<br>[app/routers/orders.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/orders.py)<br>[app/routers/payments.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/payments.py)<br>[app/routers/delivery.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/delivery.py) |
| **Entry Point** | App initialization, router mounting, and startup schema creation | [app/main.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/main.py) |

---

## 3. Relational Database Entity-Relationship Diagram (ERD)

The database schema consists of **13 normalized tables** connected via foreign keys with explicit cascading delete strategies.

```mermaid
erDiagram
    users ||--o{ addresses : "has many"
    users ||--o{ restaurants : "owns (as RESTAURANT)"
    users ||--o| carts : "has one"
    users ||--o{ orders : "places (as CUSTOMER)"
    users ||--o| delivery_partners : "operates (as DELIVERY_PARTNER)"

    restaurants ||--o{ menu_categories : "categorizes"
    restaurants ||--o{ menu_items : "offers"
    restaurants ||--o{ orders : "receives"

    menu_categories ||--o{ menu_items : "groups"

    carts ||--o{ cart_items : "contains"
    menu_items ||--o{ cart_items : "referenced by"

    orders ||--o{ order_items : "snapshots"
    orders ||--|| payments : "billed by"
    orders ||--o| deliveries : "dispatched via"
    orders ||--o{ order_status_history : "audited by"

    delivery_partners ||--o{ deliveries : "fulfills"
```

---

## 4. Finite State Machines (FSM)

### A. Order Lifecycle State Machine
Orders transition strictly according to the transition graph defined in [routers/orders.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/orders.py).

```mermaid
stateDiagram-v2
    [*] --> CREATED: Checkout Cart
    CREATED --> CONFIRMED: Payment Verified (SUCCESS)
    CREATED --> CANCELLED: Customer cancels before payment

    CONFIRMED --> PREPARING: Kitchen accepts order
    CONFIRMED --> CANCELLED: Customer / Restaurant cancels

    PREPARING --> READY_FOR_PICKUP: Food packed
    note right of PREPARING: Customer cancellation is strictly blocked!

    READY_FOR_PICKUP --> PICKED_UP: Rider collects from restaurant
    READY_FOR_PICKUP --> CANCELLED: Restaurant cancellation

    PICKED_UP --> DELIVERED: Rider hands over to customer
    DELIVERED --> [*]
    CANCELLED --> [*]
```

### B. Delivery Fulfillment State Machine
```mermaid
stateDiagram-v2
    [*] --> ASSIGNED: City-matching dispatch (partner.is_busy = True)
    ASSIGNED --> PICKED_UP: Rider arrives at kitchen (delivery.picked_up_at = now())
    note right of PICKED_UP: Synchronizes order.status -> PICKED_UP
    PICKED_UP --> DELIVERED: Rider delivers to address (delivery.delivered_at = now())
    note right of DELIVERED: Synchronizes order.status -> DELIVERED & frees rider (partner.is_busy = False)
    DELIVERED --> [*]
```

---

## 5. Core Architectural Decisions & Placement Concepts

### 1. Integer Currency Representation (Paise/Cents)
* **File Reference**: [app/models/menu.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/menu.py), [app/models/order.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/order.py), [app/models/payment.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/payment.py)
* **Concept**: IEEE 754 floating-point arithmetic is non-exact (`0.1 + 0.2 = 0.30000000000000004`). In a billing and ledger system, floating-point rounding errors compound over millions of transactions.
* **Implementation**: All prices, subtotals, delivery fees, and grand totals are stored as standard `Integer` columns representing the smallest denomination (paise). ₹340.00 is stored as `34000`.

### 2. Concurrency Control with Row-Level Locking (`SELECT FOR UPDATE`)
* **File Reference**: [app/routers/orders.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/orders.py)
* **Concept**: Prevent the **Overselling / Double-Dipping Problem**. If two users checkout the last Biryani (`stock = 1`) simultaneously, a standard `SELECT` query would read `1` in both transactions and decrement both to `0`, resulting in an oversell.
* **Implementation**: We invoke `.with_for_update()` in SQLAlchemy. In PostgreSQL, this issues `SELECT * FROM menu_items WHERE id = ? FOR UPDATE`, placing an exclusive row-level write lock. The second transaction pauses until the first transaction commits or rolls back, reading the updated stock and preventing negative inventory.

### 3. Price Snapshotting (Historical Invariance)
* **File Reference**: [app/models/order.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/models/order.py)
* **Concept**: Historical receipts must never mutate if a restaurant changes menu prices.
* **Implementation**: `OrderItem` does not just store a foreign key pointer `menu_items.id`. It explicitly freezes `item_name`, `unit_price`, and `subtotal` at the exact moment of order placement.

### 4. Single-Restaurant Cart Constraint & Conflict Resolution
* **File Reference**: [app/routers/cart.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/cart.py)
* **Concept**: A customer cannot order from two restaurants simultaneously because a single driver cannot pick up from two distinct kitchens across town without violating SLAs.
* **Implementation**: The `Cart` entity maintains a `restaurant_id` foreign key. Adding an item from Restaurant B when Restaurant A items exist triggers `HTTP 409 Conflict`. Clients can pass `clear_existing: true` to purge the old items and rebind the cart to the new restaurant atomically.

### 5. Payment Idempotency Keys
* **File Reference**: [app/routers/payments.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/payments.py)
* **Concept**: Prevent double charging when customers tap "Pay" twice or when mobile networks retry failed HTTP packets.
* **Implementation**: `payments.idempotency_key` is marked `UNIQUE` and indexed. If a request arrives with an already-processed key, the backend bypasses the payment gateway and returns the existing transaction immediately.

### 6. Cache-Aside Pattern & Active Invalidation (Redis)
* **File Reference**: [app/core/redis.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/core/redis.py), [app/routers/restaurants.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/restaurants.py), [app/routers/menu.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/menu.py)
* **Concept**: Sub-millisecond reads without stale data.
* **Implementation**: `GET /restaurants/{id}/menu` reads from Redis (`X-Cache: HIT`). On cache miss, it reads PostgreSQL, sets Redis with a 300s TTL (`X-Cache: MISS`). Any menu mutation (`POST /items`, `PATCH /items`, `DELETE /items`) evicts the key immediately, preventing stale customer views. Uses cursor-based `SCAN` rather than blocking `KEYS *` for pattern invalidation.

### 7. Distributed API Rate Limiting (Redis INCR + EXPIRE)
* **File Reference**: [app/dependencies/rate_limiter.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/dependencies/rate_limiter.py)
* **Concept**: Defends authentication endpoints against distributed brute-force attacks across horizontally scaled instances.
* **Implementation**: Atomic Redis `INCR` and `EXPIRE` window tracker. Enforces 5 requests per 60 seconds per IP on `/auth/login`, returning `HTTP 429 Too Many Requests` with `Retry-After` header.
