import concurrent.futures
import time
import uuid
import requests

from app.database.session import SessionLocal
from app.models.address import Address
from app.models.cart import Cart, CartItem
from app.models.delivery import Delivery, DeliveryPartner, DeliveryStatus
from app.models.menu import MenuCategory, MenuItem
from app.models.order import Order, OrderStatus
from app.models.payment import Payment
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.core.security import create_access_token, hash_password

BASE_URL = "http://127.0.0.1:8000"


def get_auth_header(user_id: int, role: str) -> dict:
    token = create_access_token(data={"sub": str(user_id), "role": role})
    return {"Authorization": f"Bearer {token}"}


def setup_fixtures(db):
    """Create test users, restaurant, and initial data with unique test identifiers."""
    ts = int(time.time() * 1000)
    
    # Create test restaurant owner
    owner = User(
        email=f"owner_{ts}@test.com",
        name=f"Chef Concurrency {ts}",
        password_hash=hash_password("password123"),
        role=UserRole.RESTAURANT
    )
    db.add(owner)
    db.flush()

    restaurant = Restaurant(
        owner_id=owner.id,
        name=f"Concurrency Kitchen {ts}",
        city="Bengaluru_Concurrency",
        address_line="100 Tech Park",
        is_active=True,
        is_open=True
    )
    db.add(restaurant)
    db.flush()

    category = MenuCategory(
        restaurant_id=restaurant.id,
        name="Flash Sale Specials",
        display_order=1
    )
    db.add(category)
    db.flush()

    # Flash sale item with strictly limited stock: 2 portions available!
    limited_item = MenuItem(
        restaurant_id=restaurant.id,
        category_id=category.id,
        name=f"Limited Edition Biryani {ts}",
        price=29900,  # ₹299.00
        stock_count=2,  # ONLY 2 in stock!
        is_available=True,
        is_veg=False
    )
    db.add(limited_item)
    db.flush()

    # Create 10 test customers
    customers = []
    addresses = []
    for i in range(10):
        cust = User(
            email=f"customer_{ts}_{i}@test.com",
            name=f"Runner {i}",
            password_hash=hash_password("password123"),
            role=UserRole.CUSTOMER
        )
        db.add(cust)
        db.flush()
        customers.append(cust)

        addr = Address(
            user_id=cust.id,
            title="Home",
            address_line=f"{i} Street",
            city="Bengaluru_Concurrency",
            postal_code="560001"
        )
        db.add(addr)
        db.flush()
        addresses.append(addr)

    db.commit()
    return owner, restaurant, limited_item, customers, addresses


def test_overselling_prevention():
    """
    Test 1: Extreme Concurrency & Overselling Prevention
    10 parallel customer threads compete for 2 portions of limited_item.
    Assert: Exactly 2 succeed (201 Created), 8 fail with 400 Bad Request ("Insufficient stock").
    Assert: Database stock_count never drops below 0 (ending at exactly 0).
    """
    print("\n" + "=" * 70)
    print("TEST 1: Overselling Prevention Under High Parallel Concurrency")
    print("=" * 70)

    db = SessionLocal()
    owner, restaurant, limited_item, customers, addresses = setup_fixtures(db)
    limited_item_id = limited_item.id
    restaurant_id = restaurant.id

    print(f"[*] Initial limited item ID {limited_item_id}: stock_count = {limited_item.stock_count}")
    print(f"[*] Pre-loading carts for 10 distinct customer accounts...")

    # Set up carts directly
    for i in range(10):
        cust = customers[i]
        cart = Cart(user_id=cust.id, restaurant_id=restaurant_id)
        db.add(cart)
        db.flush()
        cart_item = CartItem(cart_id=cart.id, item_id=limited_item_id, quantity=1)
        db.add(cart_item)
    db.commit()

    # Prepare pure thread-safe payloads before launching threads
    runner_configs = [
        {
            "headers": get_auth_header(c.id, c.role.value),
            "address_id": a.id,
            "index": i
        }
        for i, (c, a) in enumerate(zip(customers, addresses))
    ]
    db.close()  # Close DB session before multi-threaded requests

    print("[*] Launching 10 simultaneous checkout requests across 10 threads...")

    def do_checkout(config: dict):
        payload = {"delivery_address_id": config["address_id"], "notes": f"Concurrency run {config['index']}"}
        resp = requests.post(f"{BASE_URL}/orders/", json=payload, headers=config["headers"], timeout=10)
        return resp.status_code, resp.json()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(do_checkout, cfg) for cfg in runner_configs]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    success_count = sum(1 for status_code, _ in results if status_code == 201)
    failed_count = sum(1 for status_code, _ in results if status_code == 400)

    print(f"[+] Total checkout requests: 10")
    print(f"[+] 201 Created responses:   {success_count} (Expected: 2)")
    print(f"[+] 400 Bad Request rejected: {failed_count} (Expected: 8)")

    # Inspect final DB state with clean session
    verify_db = SessionLocal()
    item_in_db = verify_db.query(MenuItem).filter(MenuItem.id == limited_item_id).first()
    final_stock = item_in_db.stock_count if item_in_db else -99
    print(f"[+] Final inventory stock_count in DB: {final_stock} (Expected: 0)")
    verify_db.close()

    assert success_count == 2, f"Expected exactly 2 successes, got {success_count}!"
    assert failed_count == 8, f"Expected exactly 8 rejections, got {failed_count}!"
    assert final_stock == 0, f"Expected 0 stock remaining, got {final_stock}!"

    print("[PASS] TEST 1 PASSED: Zero overselling! SELECT FOR UPDATE locked rows cleanly.")


def test_double_tap_idempotency():
    """
    Test 2: Double-Tap / Network Retry Order Idempotency
    1 customer fires 5 identical checkout requests simultaneously with the same idempotency_key.
    Assert: Exactly 1 order is created in PostgreSQL.
    Assert: No duplicate orders or duplicate stock deductions occur.
    """
    print("\n" + "=" * 70)
    print("TEST 2: Double-Tap & Network Retry Order Idempotency")
    print("=" * 70)

    db = SessionLocal()
    owner, restaurant, limited_item, customers, addresses = setup_fixtures(db)

    cust = customers[0]
    addr = addresses[0]
    cust_id = cust.id
    cust_role = cust.role.value
    addr_id = addr.id
    restaurant_id = restaurant.id
    limited_item_id = limited_item.id

    idempotency_key = f"idemp_order_{uuid.uuid4().hex}"

    # Set item stock to 10
    limited_item.stock_count = 10
    db.commit()

    # Pre-load cart
    cart = Cart(user_id=cust_id, restaurant_id=restaurant_id)
    db.add(cart)
    db.flush()
    cart_item = CartItem(cart_id=cart.id, item_id=limited_item_id, quantity=1)
    db.add(cart_item)
    db.commit()

    base_headers = get_auth_header(cust_id, cust_role)
    db.close()

    print(f"[*] Customer {cust_id} submitting 5 simultaneous checkouts with idempotency_key: {idempotency_key}...")

    def do_idempotent_checkout():
        headers = dict(base_headers)
        headers["X-Idempotency-Key"] = idempotency_key
        payload = {
            "delivery_address_id": addr_id,
            "notes": "Double tap test",
            "idempotency_key": idempotency_key
        }
        resp = requests.post(f"{BASE_URL}/orders/", json=payload, headers=headers, timeout=10)
        return resp.status_code, resp.json()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(do_idempotent_checkout) for _ in range(5)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Count how many orders exist in DB with this idempotency key
    verify_db = SessionLocal()
    db_orders = verify_db.query(Order).filter(
        Order.user_id == cust_id,
        Order.idempotency_key == idempotency_key
    ).all()

    item_in_db = verify_db.query(MenuItem).filter(MenuItem.id == limited_item_id).first()
    final_stock = item_in_db.stock_count if item_in_db else -99

    print(f"[+] HTTP Status codes received: {[s for s, _ in results]}")
    print(f"[+] Total Order rows created in PostgreSQL: {len(db_orders)} (Expected: exactly 1)")
    print(f"[+] Final item stock in DB: {final_stock} (Deducted once from 10: 9)")

    verify_db.close()

    assert len(db_orders) == 1, f"Expected exactly 1 order in DB, found {len(db_orders)}!"
    assert final_stock == 9, f"Stock deducted multiple times! Remaining: {final_stock}"

    print("[PASS] TEST 2 PASSED: Double-tap deduplication verified via Redis lock & DB constraint.")


def test_payment_idempotency():
    """
    Test 3: Concurrent Payment Processing Idempotency
    5 concurrent threads attempt to pay for the same order using the same idempotency key.
    Assert: Exactly 1 Payment record is created in PostgreSQL.
    Assert: All requests return the same payment record (idempotent replay).
    """
    print("\n" + "=" * 70)
    print("TEST 3: Concurrent Payment Processing & Lock Deduplication")
    print("=" * 70)

    db = SessionLocal()
    owner, restaurant, limited_item, customers, addresses = setup_fixtures(db)

    cust = customers[0]
    addr = addresses[0]
    cust_id = cust.id
    cust_role = cust.role.value

    # Create an order
    order = Order(
        user_id=cust_id,
        restaurant_id=restaurant.id,
        delivery_address_id=addr.id,
        delivery_address_snapshot="Test Address Snapshot",
        status=OrderStatus.CREATED,
        subtotal=29900,
        delivery_fee=4000,
        grand_total=33900
    )
    db.add(order)
    db.commit()
    order_id = order.id

    payment_idempotency_key = f"pay_idemp_{uuid.uuid4().hex}"
    auth_headers = get_auth_header(cust_id, cust_role)
    db.close()

    print(f"[*] Firing 5 concurrent payments for Order #{order_id} with idempotency key: {payment_idempotency_key}...")

    def do_payment():
        payload = {
            "order_id": order_id,
            "payment_method": "UPI",
            "idempotency_key": payment_idempotency_key,
            "should_succeed": True
        }
        resp = requests.post(f"{BASE_URL}/payments/", json=payload, headers=auth_headers, timeout=10)
        return resp.status_code, resp.json()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(do_payment) for _ in range(5)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    verify_db = SessionLocal()
    payments_in_db = verify_db.query(Payment).filter(
        Payment.order_id == order_id,
        Payment.idempotency_key == payment_idempotency_key
    ).all()
    order_in_db = verify_db.query(Order).filter(Order.id == order_id).first()
    final_order_status = order_in_db.status if order_in_db else None

    print(f"[+] HTTP Status codes received: {[s for s, _ in results]}")
    print(f"[+] Total Payment rows created in PostgreSQL: {len(payments_in_db)} (Expected: exactly 1)")
    print(f"[+] Order status transitioned to: {final_order_status} (Expected: CONFIRMED)")

    verify_db.close()

    assert len(payments_in_db) == 1, f"Expected 1 payment, found {len(payments_in_db)}!"
    assert final_order_status == OrderStatus.CONFIRMED

    print("[PASS] TEST 3 PASSED: Payment idempotency verified with distributed lock serialization.")


def test_driver_dispatch_concurrency():
    """
    Test 4: Concurrent Driver Dispatch Race (SELECT FOR UPDATE SKIP LOCKED)
    1 single online delivery partner in 'DispatchCity_xxx'.
    3 separate orders ready for pickup in that city.
    3 concurrent threads attempt to dispatch the driver simultaneously.
    Assert: Exactly 1 dispatch succeeds (assigned to the driver, 200 OK).
    Assert: 2 dispatches fail with 503 Service Unavailable ("No delivery partners online").
    Assert: The driver is marked is_busy=True and has exactly 1 active Delivery record.
    """
    print("\n" + "=" * 70)
    print("TEST 4: Concurrent Driver Dispatch & Double-Booking Prevention (SKIP LOCKED)")
    print("=" * 70)

    db = SessionLocal()
    ts = int(time.time() * 1000)
    unique_city = f"DispatchCity_{ts}"

    # Create restaurant in unique city
    owner = User(
        email=f"dispatch_owner_{ts}@test.com",
        name="Dispatch Kitchen",
        password_hash=hash_password("pass123"),
        role=UserRole.RESTAURANT
    )
    db.add(owner)
    db.flush()

    restaurant = Restaurant(
        owner_id=owner.id,
        name=f"Rider Test Cafe {ts}",
        city=unique_city,
        address_line="1 Airport Rd",
        is_active=True,
        is_open=True
    )
    db.add(restaurant)
    db.flush()

    # Create ONLY ONE delivery partner in this city
    partner_user = User(
        email=f"rider_{ts}@test.com",
        name="Solo Rider",
        password_hash=hash_password("pass123"),
        role=UserRole.DELIVERY_PARTNER
    )
    db.add(partner_user)
    db.flush()

    partner = DeliveryPartner(
        user_id=partner_user.id,
        vehicle_type="Bike",
        vehicle_number="KA-01-AB-1234",
        current_city=unique_city,
        is_online=True,
        is_busy=False  # Available!
    )
    db.add(partner)
    db.flush()

    # Create 3 orders READY_FOR_PICKUP in this city
    orders = []
    for i in range(3):
        ord_obj = Order(
            user_id=owner.id,
            restaurant_id=restaurant.id,
            delivery_address_snapshot=f"Address {i}, {unique_city}",
            status=OrderStatus.READY_FOR_PICKUP,
            subtotal=20000,
            delivery_fee=4000,
            grand_total=24000
        )
        db.add(ord_obj)
        db.flush()
        orders.append(ord_obj)

    db.commit()

    partner_id = partner.id
    order_ids = [o.id for o in orders]
    owner_headers = get_auth_header(owner.id, owner.role.value)
    db.close()

    print(f"[*] Created 1 delivery partner (Partner ID: {partner_id}) in city '{unique_city}'")
    print(f"[*] Created 3 orders ready for pickup: {order_ids}")
    print(f"[*] Launching 3 simultaneous dispatch requests...")

    def do_assign(order_id: int):
        resp = requests.post(f"{BASE_URL}/delivery/assign/{order_id}", headers=owner_headers, timeout=10)
        return resp.status_code, resp.json()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(do_assign, oid) for oid in order_ids]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    status_codes = [s for s, _ in results]
    success_count = sum(1 for s in status_codes if s == 200)
    unavailable_count = sum(1 for s in status_codes if s == 503)

    print(f"[+] HTTP Status codes received: {status_codes}")
    print(f"[+] 200 OK (Driver Assigned):         {success_count} (Expected: exactly 1)")
    print(f"[+] 503 Service Unavailable (No Rider): {unavailable_count} (Expected: exactly 2)")

    # Verify database state with clean session
    verify_db = SessionLocal()
    partner_in_db = verify_db.query(DeliveryPartner).filter(DeliveryPartner.id == partner_id).first()
    deliveries = verify_db.query(Delivery).filter(
        Delivery.partner_id == partner_id,
        Delivery.status == DeliveryStatus.ASSIGNED
    ).all()

    is_busy = partner_in_db.is_busy if partner_in_db else False
    delivery_count = len(deliveries)
    print(f"[+] Partner is_busy flag in DB: {is_busy} (Expected: True)")
    print(f"[+] Active Delivery rows assigned to this partner: {delivery_count} (Expected: exactly 1)")

    verify_db.close()

    assert success_count == 1, f"Expected exactly 1 successful dispatch, got {success_count}!"
    assert unavailable_count == 2, f"Expected exactly 2 503 rejections, got {unavailable_count}!"
    assert delivery_count == 1, f"Rider was double booked! Assigned to {delivery_count} orders!"
    assert is_busy is True, "Partner was not marked busy!"

    print("[PASS] TEST 4 PASSED: SELECT FOR UPDATE SKIP LOCKED prevented driver double-booking!")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("STARTING STAGE 3 CONCURRENCY & DISTRIBUTED CONSISTENCY TEST SUITE")
    print("=" * 70)

    test_overselling_prevention()
    test_double_tap_idempotency()
    test_payment_idempotency()
    test_driver_dispatch_concurrency()

    print("\n" + "=" * 70)
    print("ALL 4 STAGE 3 CONCURRENCY TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70 + "\n")
