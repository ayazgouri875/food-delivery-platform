# Implementation Guide: Food Delivery Platform (Stages 1 & 2)

This document provides an exhaustive, code-level explanation of how data flows, how authentication, authorization, and rate limiting are enforced, how database transactions and locks are executed, and how Redis Cache-Aside and Invalidation operate.

---

## 1. Authentication, Authorization & Distributed Rate Limiting

The security architecture is decoupled into **Cryptographic Utilities** and **FastAPI Injected Dependencies**.

### A. Password Hashing (Bcrypt)
* **File Location**: [app/core/security.py:8-19](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/core/security.py#L8-L19)
* **Function**: `hash_password(password: str) -> str`
  ```python
  salt = bcrypt.gensalt()
  return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
  ```
* **Function**: `verify_password(plain_password: str, hashed_password: str) -> bool`
  ```python
  return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
  ```
* **Interview Insight**: Passwords are never stored in plaintext. `bcrypt.gensalt()` generates a random 128-bit salt per user to defend against **Rainbow Table Attacks** (precomputed hash lookup tables).

### B. Stateless JWT Issuance & Verification
* **File Location**: [app/core/security.py:22-44](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/core/security.py#L22-L44)
* **Function**: `create_access_token(data: dict, expires_delta: Optional[timedelta]) -> str`
* **Token Structure**:
  * **Header**: Algorithm (`HS256`), Token Type (`JWT`).
  * **Payload Claims**:
    * `sub`: Subject identifier (User ID as string, e.g. `"1"`).
    * `email`: User email address.
    * `role`: User platform role (`CUSTOMER`, `RESTAURANT`, `DELIVERY_PARTNER`, `ADMIN`).
    * `iat`: Issued At timestamp (UTC).
    * `exp`: Expiration timestamp (default: 24 hours).
  * **Signature**: HMAC-SHA256 signature signed using `settings.SECRET_KEY`.
* **Function**: `decode_access_token(token: str) -> dict`
  * Validates the token against tampering. If a user modifies their role claim from `CUSTOMER` to `ADMIN`, signature verification fails and raises `jwt.PyJWTError`.

### C. Authentication Dependency: `get_current_user`
* **File Location**: [app/dependencies/auth.py:14-41](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/dependencies/auth.py#L14-L41)
* **Workflow**:
  1. Intercepts the `Authorization: Bearer <TOKEN>` HTTP header via `OAuth2PasswordBearer(tokenUrl="/auth/token")`.
  2. Decodes the token using `decode_access_token()`. If invalid or expired, raises `HTTP 401 Unauthorized`.
  3. Queries PostgreSQL for the user: `db.query(User).filter(User.id == int(payload["sub"])).first()`.
  4. Verifies `user.is_active == True`. If false, raises `HTTP 403 Forbidden` (`"Inactive user account"`).
  5. Injects the active `User` instance into the route handler.

### D. Role-Based Access Control Factory: `require_role`
* **File Location**: [app/dependencies/auth.py:44-59](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/dependencies/auth.py#L44-L59)
* **Workflow**:
  * Implemented as a higher-order closure that receives a sequence of allowed roles:
    ```python
    def require_role(allowed_roles: Sequence[UserRole]):
        def role_checker(current_user: User = Depends(get_current_user)) -> User:
            if current_user.role not in allowed_roles:
                raise HTTPException(status_code=403, detail=f"Operation not permitted. Required roles: {[r.value for r in allowed_roles]}")
            return current_user
        return role_checker
    ```

### E. Distributed API Rate Limiting (Redis INCR + EXPIRE)
* **File Location**: [app/dependencies/rate_limiter.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/dependencies/rate_limiter.py)
* **Function**: `rate_limit(max_requests=5, window_seconds=60, endpoint_tag="login")`
* **Workflow**:
  1. Extracts client IP (from `X-Forwarded-For` if behind a reverse proxy/load balancer, or `request.client.host`).
  2. Generates atomic key: `rate_limit:{endpoint_tag}:{client_ip}`.
  3. Executes `current_count = redis_client.incr(rate_key)`.
  4. If `current_count == 1`, sets expiration: `redis_client.expire(rate_key, window_seconds)`.
  5. If `current_count > max_requests`, fetches remaining TTL via `redis_client.ttl(rate_key)` and raises `HTTP 429 Too Many Requests` with header `Retry-After: {ttl}`.
  6. Fails open gracefully if Redis is temporarily unreachable.

---

## 2. Database Engine & Session Lifecycle

### A. Connection Pooling Configuration
* **File Location**: [app/database/session.py:6-12](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/database/session.py#L6-L12)
  ```python
  engine = create_engine(
      settings.DATABASE_URL,
      pool_pre_ping=True,  # Issues a test ping to catch stale/dropped TCP connections
      pool_size=10,        # Maintains 10 persistent open connections to PostgreSQL
      max_overflow=20      # Allows up to 20 temporary burst connections under load
  )
  ```

### B. Session Lifecycle Dependency: `get_db`
* **File Location**: [app/dependencies/database.py:7-16](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/dependencies/database.py#L7-L16)
  ```python
  def get_db() -> Generator[Session, None, None]:
      db = SessionLocal()
      try:
          yield db
      finally:
          db.close()
  ```

---

## 3. Redis Cache-Aside & Active Invalidation Implementation

### A. Redis Connection & Safe Cache Helpers
* **File Location**: [app/core/redis.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/core/redis.py)
* **Connection Pool**: Reusable pool with automatic UTF-8 string decoding (`decode_responses=True`).
* **`get_cache(key)`**: Retrieves and JSON-deserializes cache. Returns `None` if key not found or on connection error (Graceful Degradation).
* **`set_cache(key, data, ttl=300)`**: Serializes and stores data with TTL in seconds.
* **`delete_cache(key)`**: Deletes a specific cache key.
* **`delete_pattern(pattern)`**: Uses non-blocking cursor iteration (`SCAN`) instead of blocking `KEYS *` to evict matching keys.

### B. Cache-Aside in Restaurant Discovery & Menus
* **File Location**: [app/routers/restaurants.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/restaurants.py)
* **Workflow**:
  1. `GET /restaurants/{restaurant_id}/menu`:
     ```python
     cache_key = f"restaurant:{restaurant_id}:menu"
     cached_menu = get_cache(cache_key)
     if cached_menu:
         response.headers["X-Cache"] = "HIT"
         return cached_menu
     # Cache miss: query PostgreSQL, populate Redis, return with X-Cache: MISS
     ```
  2. `GET /restaurants/`:
     * Caches discovery query results with key `f"restaurants:list:{city}:{search}:{is_open_only}:{skip}:{limit}"` and a 60-second TTL.

### C. Active Cache Invalidation on Mutations
* **File Location**: [app/routers/menu.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/menu.py), [app/routers/restaurants.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/restaurants.py)
* **Eviction Points**:
  * `create_category`: `delete_cache(f"restaurant:{restaurant_id}:menu")`
  * `create_menu_item`: `delete_cache(f"restaurant:{restaurant_id}:menu")`
  * `update_menu_item`: `delete_cache(f"restaurant:{item.restaurant_id}:menu")`
  * `toggle_item_availability`: `delete_cache(f"restaurant:{item.restaurant_id}:menu")`
  * `delete_menu_item`: `delete_cache(f"restaurant:{restaurant_id}:menu")`
  * `update_restaurant_status`: `delete_cache(...)` + `delete_pattern("restaurants:list:*")`
  * `toggle_restaurant_open`: `delete_cache(...)` + `delete_pattern("restaurants:list:*")`

---

## 4. How Data is Written & Read (Domain Workflows)

### A. Single-Restaurant Cart Enforcement
* **Write Workflow**: [app/routers/cart.py:71-140](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/cart.py#L71-L140)
  1. Customer submits `POST /cart/items` with `item_id`, `quantity`, and `clear_existing`.
  2. Retrieves or initializes `Cart` for `current_user.id`.
  3. Fetches `MenuItem` and verifies `is_available == True`, `restaurant.is_active == True`, and `restaurant.is_open == True`.
  4. **Conflict Check**: If `cart.restaurant_id` differs from `menu_item.restaurant_id`:
     * If `clear_existing == False`: Aborts with `HTTP 409 Conflict`.
     * If `clear_existing == True`: Purges previous items, sets `cart.restaurant_id = menu_item.restaurant_id`.
  5. Increments quantity or creates new `CartItem`. Returns recomputed totals.

### B. Concurrency-Safe Checkout (`SELECT FOR UPDATE`)
* **Write Workflow**: [app/routers/orders.py:44-128](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/orders.py#L44-L128)
  1. Customer submits `POST /orders/` with `delivery_address_id`.
  2. Snapshots delivery address string.
  3. **Row Locking Loop**:
     ```python
     for cart_item in cart.items:
         menu_item = db.query(MenuItem).filter(MenuItem.id == cart_item.item_id).with_for_update().first()
         if menu_item.stock_count != -1:
             if menu_item.stock_count < cart_item.quantity:
                 raise HTTPException(400, detail="Insufficient stock")
             menu_item.stock_count -= cart_item.quantity
     ```
  4. Creates `Order` (`status = CREATED`), `OrderItem` (price snapshotting), and `OrderStatusHistory`.
  5. Clears cart atomically.

### C. Idempotent Payment Processing
* **Write Workflow**: [app/routers/payments.py:23-78](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/payments.py#L23-L78)
  1. Client sends `POST /payments/` with `idempotency_key`.
  2. If `idempotency_key` exists in PostgreSQL, returns previous transaction directly.
  3. Otherwise, generates `txn_mock_<uuid>`, updates `order.status = CONFIRMED`, and logs history.

### D. Dispatch Matching & Rider Fulfillment Sync
* **Write Workflow**: [app/routers/delivery.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/delivery.py)
  1. `POST /delivery/assign/{order_id}`: Finds partner in city (`is_online=True`, `is_busy=False`). Sets `is_busy=True`.
  2. `PATCH /delivery/{id}/status` $\rightarrow$ `PICKED_UP`: Sets `picked_up_at = now()`, syncs `order.status = PICKED_UP`.
  3. `PATCH /delivery/{id}/status` $\rightarrow$ `DELIVERED`: Sets `delivered_at = now()`, syncs `order.status = DELIVERED`, and resets `partner.is_busy = False`.

---

## 5. Complete REST API Catalog

### 1. Authentication Domain ([app/routers/auth.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/auth.py))
| Method | Endpoint | Access | Rate Limit | Request Body | Response Model | Status Code |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/auth/register` | Public | None | `UserRegister` | `Token` | `201 Created` |
| `POST` | `/auth/login` | Public | **5 req / 60s / IP** | `UserLogin` | `Token` | `200 OK` (or `429`) |
| `POST` | `/auth/token` | Public | **5 req / 60s / IP** | `OAuth2PasswordRequestForm` | `Token` | `200 OK` (or `429`) |
| `GET` | `/auth/me` | Authenticated | None | None | `UserResponse` | `200 OK` |

### 2. Users Domain ([app/routers/users.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/users.py))
| Method | Endpoint | Access | Request Body / Params | Response Model | Status Code |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/users/` | `ADMIN` only | `skip: int, limit: int` | `List[UserResponse]` | `200 OK` |
| `GET` | `/users/{user_id}` | Owner or `ADMIN` | None | `UserResponse` | `200 OK` |
| `PATCH` | `/users/{user_id}/status` | `ADMIN` only | `UserStatusUpdate` (is_active: bool) | `UserResponse` | `200 OK` |

### 3. Restaurants Domain ([app/routers/restaurants.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/restaurants.py))
| Method | Endpoint | Access | Cache Strategy | Request Body / Params | Response Model | Status Code |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/restaurants/` | `RESTAURANT`, `ADMIN` | Invalidates `restaurants:list:*` | `RestaurantCreate` | `RestaurantResponse` | `201 Created` |
| `GET` | `/restaurants/` | Public | **Cache-Aside (TTL: 60s)** | `city, search, is_open_only, skip, limit` | `List[RestaurantResponse]` | `200 OK` |
| `GET` | `/restaurants/{id}` | Public | None | None | `RestaurantResponse` | `200 OK` |
| `GET` | `/restaurants/{id}/menu` | Public | **Cache-Aside (TTL: 300s)** | None | `RestaurantFullMenuResponse` | `200 OK` |
| `PATCH` | `/restaurants/{id}/status` | `ADMIN` only | Invalidates menu & list | `RestaurantStatusUpdate` | `RestaurantResponse` | `200 OK` |
| `PATCH` | `/restaurants/{id}/toggle-open` | Owner or `ADMIN` | Invalidates menu & list | `RestaurantToggleOpen` | `RestaurantResponse` | `200 OK` |

### 4. Menu Domain ([app/routers/menu.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/menu.py))
| Method | Endpoint | Access | Cache Effect | Request Body / Params | Response Model | Status Code |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/restaurants/{id}/categories` | Owner / `ADMIN` | Evicts `restaurant:{id}:menu` | `MenuCategoryCreate` | `MenuCategoryResponse` | `201 Created` |
| `GET` | `/restaurants/{id}/categories` | Public | None | None | `List[MenuCategoryResponse]` | `200 OK` |
| `POST` | `/restaurants/{id}/items` | Owner / `ADMIN` | Evicts `restaurant:{id}:menu` | `MenuItemCreate` | `MenuItemResponse` | `201 Created` |
| `GET` | `/restaurants/{id}/items` | Public | None | None | `List[MenuItemResponse]` | `200 OK` |
| `PATCH` | `/menu/items/{id}` | Owner / `ADMIN` | Evicts `restaurant:{id}:menu` | `MenuItemUpdate` | `MenuItemResponse` | `200 OK` |
| `PATCH` | `/menu/items/{id}/availability` | Owner / `ADMIN` | Evicts `restaurant:{id}:menu` | `MenuItemAvailabilityUpdate` | `MenuItemResponse` | `200 OK` |
| `DELETE` | `/menu/items/{id}` | Owner / `ADMIN` | Evicts `restaurant:{id}:menu` | None | None | `204 No Content` |

### 5. Cart Domain ([app/routers/cart.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/cart.py))
| Method | Endpoint | Access | Request Body / Params | Response Model | Status Code |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/cart/` | Authenticated | None | `CartResponse` | `200 OK` |
| `POST` | `/cart/items` | Authenticated | `CartItemAdd` (item_id, quantity, clear_existing) | `CartResponse` | `200 OK` (or `409`) |
| `PATCH` | `/cart/items/{item_id}` | Authenticated | `CartItemUpdate` (quantity: int) | `CartResponse` | `200 OK` |
| `DELETE` | `/cart/items/{item_id}` | Authenticated | None | `CartResponse` | `200 OK` |
| `DELETE` | `/cart/` | Authenticated | None | None | `204 No Content` |

### 6. Address Domain ([app/routers/address.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/address.py))
| Method | Endpoint | Access | Request Body / Params | Response Model | Status Code |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/addresses/` | Authenticated | None | `List[AddressResponse]` | `200 OK` |
| `POST` | `/addresses/` | Authenticated | `AddressCreate` (title, address_line, city, postal_code, is_default) | `AddressResponse` | `201 Created` |
| `DELETE` | `/addresses/{id}` | Owner | None | None | `204 No Content` |

### 7. Orders Domain ([app/routers/orders.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/orders.py))
| Method | Endpoint | Access | Concurrency Guard | Request Body / Params | Response Model | Status Code |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/orders/` | Authenticated | **Redis Distributed Lock + Idempotency Replay + Deterministic `SELECT FOR UPDATE`** | `OrderCreate` (delivery_address_id, notes, idempotency_key) / Header `X-Idempotency-Key` | `OrderResponse` | `201 Created` (or `200` replay, `409` in-flight) |
| `GET` | `/orders/` | Authenticated | None | `skip: int, limit: int` | `List[OrderResponse]` | `200 OK` |
| `GET` | `/orders/{id}` | Participant or `ADMIN` | None | None | `OrderDetailResponse` | `200 OK` |
| `PATCH` | `/orders/{id}/status` | Restaurant, Admin | FSM validation | `OrderStatusUpdate` (status, notes) | `OrderDetailResponse` | `200 OK` |
| `POST` | `/orders/{id}/cancel` | Customer, Restaurant | FSM guard + stock restoral | `notes: str` | `OrderDetailResponse` | `200 OK` |

### 8. Payments Domain ([app/routers/payments.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/payments.py))
| Method | Endpoint | Access | Concurrency Guard | Request Body / Params | Response Model | Status Code |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/payments/` | Authenticated | **Distributed Lock on `idempotency_key` + `SELECT FOR UPDATE` on Order** | `PaymentInitiate` (order_id, payment_method, idempotency_key, should_succeed) | `PaymentResponse` | `200 OK` |

### 9. Delivery Domain ([app/routers/delivery.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/delivery.py))
| Method | Endpoint | Access | Concurrency Guard | Request Body / Params | Response Model | Status Code |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/delivery/partner/profile` | `DELIVERY_PARTNER`, `ADMIN` | None | `DeliveryPartnerProfile` | `DeliveryPartnerResponse` | `200 OK` |
| `GET` | `/delivery/partner/me` | `DELIVERY_PARTNER`, `ADMIN` | None | None | `DeliveryPartnerResponse` | `200 OK` |
| `PATCH` | `/delivery/partner/status` | `DELIVERY_PARTNER`, `ADMIN` | Online/Offline toggle | `DeliveryPartnerToggleOnline` | `DeliveryPartnerResponse` | `200 OK` |
| `POST` | `/delivery/assign/{order_id}` | Authenticated | **Order Row Lock + Partner `SELECT FOR UPDATE SKIP LOCKED`** | None | `DeliveryResponse` | `200 OK` (or `503`) |
| `GET` | `/delivery/my-deliveries` | `DELIVERY_PARTNER` | None | None | `List[DeliveryResponse]` | `200 OK` |
| `PATCH` | `/delivery/{id}/status` | `DELIVERY_PARTNER`, `ADMIN` | Syncs `order.status` & releases partner lock | `DeliveryStatusUpdate` | `DeliveryResponse` | `200 OK` |
| `POST` | `/delivery/location` | `DELIVERY_PARTNER` | **Redis Geospatial Index + Live Pub/Sub Telemetry** | `DeliveryLocationUpdate` (lat, lon, heading, speed) | `DeliveryLocationResponse` | `200 OK` |

### 10. Real-Time WebSockets & Notifications Domain ([app/routers/websockets.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/websockets.py))
| Protocol | Endpoint | Access | Real-Time Broker | Request Body / Params | Event Payload |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `WS` | `/ws/orders/{order_id}` | Participant or `ADMIN` | **Redis Pub/Sub (`channel:order:{id}`)** | `token: str` (JWT Query or Header) | Streams `ORDER_*`, `DRIVER_*`, `PAYMENT_*` payloads |
| `GET` | `/ws/notifications` | Authenticated | Redis Inbox (`notifications:user:{id}`) | `limit: int` (default 20) | User notification history |

---

## Stage 3: Concurrency & Distributed Consistency File Map

| Mechanism | Primary Source File | Technical Strategy | System Guarantee |
| :--- | :--- | :--- | :--- |
| **Distributed Lock** | [app/core/redis.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/core/redis.py#L107-L146) | `redis_client.set(key, token, nx=True, ex=ttl)` + Lua script token validation | Mutual exclusion across distributed nodes; safe auto-release on crash |
| **Order Idempotency** | [app/routers/orders.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/orders.py#L40-L75) | Fast Redis lookup (`idempotency:order:{uid}:{key}`) + PostgreSQL `orders.idempotency_key` unique column | Network retries and double clicks return same order; zero duplicate orders |
| **Deadlock-Free Row Lock** | [app/routers/orders.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/orders.py#L117-L148) | Sort cart items by ascending `item_id` before querying `MenuItem.with_for_update()` | Dijkstra's resource hierarchy; eliminates database deadlocks |
| **Driver Double-Booking Defense** | [app/routers/delivery.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/delivery.py#L173-L188) | `DeliveryPartner.with_for_update(skip_locked=True)` + `Order.with_for_update()` | Parallel dispatch workers claim different riders simultaneously; zero contention |
| **Payment Deduplication** | [app/routers/payments.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/payments.py#L22-L46) | `distributed_lock(f"lock:payment:{key}")` + `Order.with_for_update()` | Prevents duplicate card/UPI debits and duplicate order confirmations |
| **Automated Concurrency Tests** | [tests/test_concurrency.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/tests/test_concurrency.py) | `concurrent.futures.ThreadPoolExecutor` against live FastAPI + PostgreSQL + Redis | Automated stress testing: 10 parallel checkouts, 5 double taps, 3 dispatch races |

---

## Stage 4: Real-Time Event-Driven Architecture File Map

| Mechanism | Primary Source File | Technical Strategy | System Guarantee |
| :--- | :--- | :--- | :--- |
| **Redis Pub/Sub Event Bus** | [app/core/events.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/core/events.py) | `redis_client.publish(channel, json)` + `rpush(timeline_key)` | Sub-millisecond distributed pub/sub; durable replay on reconnection |
| **WebSocket Order Tracking** | [app/routers/websockets.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/routers/websockets.py) | `redis.asyncio` pubsub listener in async task forwarder | Zero database polling; horizontal scalability across multiple app servers |
| **Driver Geolocation Telemetry** | [app/services/telemetry.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/services/telemetry.py) | `GEOADD geo:delivery_partners` + Haversine formula distance & ETA | Real-time GPS indexing without relational database disk contention |
| **Decoupled Notifications** | [app/services/notifications.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/app/services/notifications.py) | FastAPI `BackgroundTasks` + Redis user inbox queues | Non-blocking external notification delivery; instant API response times |
| **Real-Time Integration Tests** | [tests/test_stage4_events.py](file:///Users/macbookpro/Desktop/food-delivery-platform/food_delivery_be/tests/test_stage4_events.py) | Async `websockets` client listening while HTTP transactions execute | 9-step full lifecycle test covering WS handshake, payments, kitchen, GPS, and delivery |


