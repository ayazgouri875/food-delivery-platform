import asyncio
import json
import time
import requests
import websockets
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.database.session import SessionLocal
from app.models.address import Address
from app.models.delivery import DeliveryPartner
from app.models.menu import MenuCategory, MenuItem
from app.models.order import Order, OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole

BASE_HTTP_URL = "http://127.0.0.1:8000"
BASE_WS_URL = "ws://127.0.0.1:8000"


def get_token(user_id: int, role: str) -> str:
    return create_access_token(data={"sub": str(user_id), "role": role})


def setup_stage4_test_data():
    """Sets up a complete ecosystem: Customer, Restaurant, Driver, and Order."""
    db: Session = SessionLocal()
    ts = int(time.time() * 1000)

    # 1. Customer
    customer = User(
        email=f"ws_customer_{ts}@test.com",
        name=f"Alice LiveTracker {ts}",
        password_hash=hash_password("pass123"),
        role=UserRole.CUSTOMER
    )
    db.add(customer)
    db.flush()

    address = Address(
        user_id=customer.id,
        title="Home",
        address_line="12th Main Indiranagar",
        city="Bengaluru_Live",
        postal_code="560038"
    )
    db.add(address)
    db.flush()

    # 2. Restaurant
    owner = User(
        email=f"ws_owner_{ts}@test.com",
        name=f"Chef Luigi {ts}",
        password_hash=hash_password("pass123"),
        role=UserRole.RESTAURANT
    )
    db.add(owner)
    db.flush()

    restaurant = Restaurant(
        owner_id=owner.id,
        name=f"Luigi Pizzeria {ts}",
        city="Bengaluru_Live",
        address_line="100 Feet Road, Indiranagar",
        latitude=12.9784,
        longitude=77.6408,
        is_active=True,
        is_open=True
    )
    db.add(restaurant)
    db.flush()

    category = MenuCategory(restaurant_id=restaurant.id, name="Pizzas", display_order=1)
    db.add(category)
    db.flush()

    item = MenuItem(
        restaurant_id=restaurant.id,
        category_id=category.id,
        name="Truffle Pizza",
        price=49900,
        stock_count=50,
        is_available=True,
        is_veg=True
    )
    db.add(item)
    db.flush()

    # 3. Delivery Partner
    rider_user = User(
        email=f"ws_rider_{ts}@test.com",
        name=f"Flash Gordon {ts}",
        password_hash=hash_password("pass123"),
        role=UserRole.DELIVERY_PARTNER
    )
    db.add(rider_user)
    db.flush()

    partner = DeliveryPartner(
        user_id=rider_user.id,
        vehicle_type="Electric Scooter",
        vehicle_number="KA-03-EV-9999",
        current_city="Bengaluru_Live",
        is_online=True,
        is_busy=False
    )
    db.add(partner)
    db.flush()

    # 4. Order
    order = Order(
        user_id=customer.id,
        restaurant_id=restaurant.id,
        delivery_address_id=address.id,
        delivery_address_snapshot=f"{address.title}: {address.address_line}, {address.city}",
        status=OrderStatus.CREATED,
        subtotal=49900,
        delivery_fee=4000,
        grand_total=53900
    )
    db.add(order)
    db.commit()

    test_data = {
        "customer_id": customer.id,
        "customer_email": customer.email,
        "customer_token": get_token(customer.id, customer.role.value),
        "owner_id": owner.id,
        "owner_token": get_token(owner.id, owner.role.value),
        "rider_user_id": rider_user.id,
        "rider_token": get_token(rider_user.id, rider_user.role.value),
        "partner_id": partner.id,
        "order_id": order.id,
        "restaurant_id": restaurant.id
    }
    db.close()
    return test_data


async def run_stage4_test():
    print("\n" + "=" * 75)
    print("STARTING STAGE 4: ASYNCHRONOUS EVENTS & WEBSOCKET REAL-TIME TEST SUITE")
    print("=" * 75)

    data = setup_stage4_test_data()
    order_id = data["order_id"]
    customer_token = data["customer_token"]
    owner_token = data["owner_token"]
    rider_token = data["rider_token"]

    print(f"[*] Test Environment Seeded:")
    print(f"    - Order ID: #{order_id}")
    print(f"    - Customer ID: {data['customer_id']}")
    print(f"    - Rider ID: {data['partner_id']}")
    print(f"[*] Connecting customer WebSocket to: {BASE_WS_URL}/ws/orders/{order_id}?token=...")

    ws_url = f"{BASE_WS_URL}/ws/orders/{order_id}?token={customer_token}"

    async with websockets.connect(ws_url) as ws:
        # Step 1: Initial Connection
        init_raw = await ws.recv()
        init_msg = json.loads(init_raw)
        print(f"[+] WebSocket Received: {init_msg.get('event_type')} (Status: {init_msg.get('current_status')})")
        assert init_msg.get("event_type") == "CONNECTION_ESTABLISHED"
        assert init_msg.get("current_status") == "CREATED"
        print("[PASS] Step 1: WebSocket connection established with live state snapshot!")

        # Step 2: Trigger Payment via HTTP POST /payments/
        print("\n[*] Step 2: Customer executes payment via HTTP POST /payments/...")
        pay_payload = {
            "order_id": order_id,
            "payment_method": "UPI",
            "idempotency_key": f"pay_ws_{time.time()}",
            "should_succeed": True
        }
        pay_resp = requests.post(
            f"{BASE_HTTP_URL}/payments/",
            json=pay_payload,
            headers={"Authorization": f"Bearer {customer_token}"}
        )
        assert pay_resp.status_code == 200

        # WebSocket should receive PAYMENT_SUCCESS and ORDER_CONFIRMED
        evt1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        print(f"[+] WebSocket Received: {evt1.get('event_type')}")
        assert evt1.get("event_type") == "PAYMENT_SUCCESS"

        evt2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        print(f"[+] WebSocket Received: {evt2.get('event_type')}")
        assert evt2.get("event_type") == "ORDER_CONFIRMED"
        print("[PASS] Step 2: Payment confirmation pushed to customer WebSocket in real time!")

        # Step 3: Restaurant Kitchen marks PREPARING via HTTP PATCH /orders/{id}/status
        print("\n[*] Step 3: Kitchen transitions order to PREPARING...")
        prep_resp = requests.patch(
            f"{BASE_HTTP_URL}/orders/{order_id}/status",
            json={"status": "PREPARING", "notes": "Woodfired oven baking"},
            headers={"Authorization": f"Bearer {owner_token}"}
        )
        assert prep_resp.status_code == 200

        evt3 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        print(f"[+] WebSocket Received: {evt3.get('event_type')} (Notes: {evt3['data'].get('notes')})")
        assert evt3.get("event_type") == "ORDER_PREPARING"
        print("[PASS] Step 3: Kitchen preparation update pushed over WebSocket!")

        # Step 4: Restaurant Kitchen marks READY_FOR_PICKUP
        print("\n[*] Step 4: Kitchen marks order READY_FOR_PICKUP...")
        ready_resp = requests.patch(
            f"{BASE_HTTP_URL}/orders/{order_id}/status",
            json={"status": "READY_FOR_PICKUP", "notes": "Pizza boxed and ready at counter"},
            headers={"Authorization": f"Bearer {owner_token}"}
        )
        assert ready_resp.status_code == 200

        evt4 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        print(f"[+] WebSocket Received: {evt4.get('event_type')}")
        assert evt4.get("event_type") == "ORDER_READY_FOR_PICKUP"
        print("[PASS] Step 4: Ready for pickup broadcast received!")

        # Step 5: Assign Delivery Partner via HTTP POST /delivery/assign/{order_id}
        print("\n[*] Step 5: System dispatches delivery partner...")
        assign_resp = requests.post(
            f"{BASE_HTTP_URL}/delivery/assign/{order_id}",
            headers={"Authorization": f"Bearer {owner_token}"}
        )
        assert assign_resp.status_code == 200
        delivery_id = assign_resp.json()["id"]

        evt5 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        print(f"[+] WebSocket Received: {evt5.get('event_type')}")
        print(f"    - Assigned Rider: {evt5['data'].get('driver_name')}")
        print(f"    - Vehicle:        {evt5['data'].get('vehicle_number')}")
        assert evt5.get("event_type") == "DRIVER_ASSIGNED"
        print("[PASS] Step 5: Driver assignment broadcast with vehicle details received!")

        # Step 6: Driver Location Telemetry Ping via HTTP POST /delivery/location
        print("\n[*] Step 6: Driver pings GPS telemetry (Lat: 12.9750, Lon: 77.6350)...")
        loc_resp = requests.post(
            f"{BASE_HTTP_URL}/delivery/location",
            json={"latitude": 12.9750, "longitude": 77.6350, "heading": 90.0, "speed": 28.5},
            headers={"Authorization": f"Bearer {rider_token}"}
        )
        assert loc_resp.status_code == 200

        evt6 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        print(f"[+] WebSocket Received: {evt6.get('event_type')}")
        print(f"    - Live Latitude:   {evt6['data'].get('latitude')}")
        print(f"    - Live Longitude:  {evt6['data'].get('longitude')}")
        print(f"    - Distance to Hub: {evt6['data'].get('distance_meters')} meters")
        print(f"    - Dynamic ETA:     {evt6['data'].get('eta_minutes')} minutes")
        assert evt6.get("event_type") == "DRIVER_LOCATION_UPDATED"
        assert evt6["data"].get("eta_minutes") is not None
        print("[PASS] Step 6: Real-time driver GPS telemetry & ETA calculation streamed successfully!")

        # Step 7: Driver picks up order (PICKED_UP)
        print("\n[*] Step 7: Driver collects order from kitchen...")
        pickup_resp = requests.patch(
            f"{BASE_HTTP_URL}/delivery/{delivery_id}/status",
            json={"status": "PICKED_UP"},
            headers={"Authorization": f"Bearer {rider_token}"}
        )
        assert pickup_resp.status_code == 200

        evt7 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        print(f"[+] WebSocket Received: {evt7.get('event_type')}")
        assert evt7.get("event_type") == "ORDER_PICKED_UP"
        print("[PASS] Step 7: Order picked up broadcast received!")

        # Step 8: Driver completes delivery (DELIVERED)
        print("\n[*] Step 8: Driver marks order DELIVERED...")
        deliv_resp = requests.patch(
            f"{BASE_HTTP_URL}/delivery/{delivery_id}/status",
            json={"status": "DELIVERED"},
            headers={"Authorization": f"Bearer {rider_token}"}
        )
        assert deliv_resp.status_code == 200

        evt8 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        print(f"[+] WebSocket Received: {evt8.get('event_type')}")
        assert evt8.get("event_type") == "ORDER_DELIVERED"
        print("[PASS] Step 8: Order delivered final broadcast received!")

    # Step 9: Verify Asynchronous In-App Notifications
    print("\n[*] Step 9: Verifying customer asynchronous notifications inbox...")
    time.sleep(0.5)  # Allow background task queue to settle
    notif_resp = requests.get(
        f"{BASE_HTTP_URL}/ws/notifications",
        headers={"Authorization": f"Bearer {customer_token}"}
    )
    assert notif_resp.status_code == 200
    notifications = notif_resp.json()["notifications"]
    print(f"[+] Found {len(notifications)} asynchronous notifications in customer inbox:")
    for n in notifications:
        print(f"    - [{n['type']}] {n['title']}: {n['body']}")

    notif_types = [n["type"] for n in notifications]
    assert "ORDER_CONFIRMED" in notif_types
    assert "DRIVER_ASSIGNED" in notif_types
    assert "ORDER_PICKED_UP" in notif_types
    assert "ORDER_DELIVERED" in notif_types
    print("[PASS] Step 9: All background notifications verified in Redis inbox!")

    print("\n" + "=" * 75)
    print("ALL 9 STAGE 4 REAL-TIME EVENT & WEBSOCKET TESTS COMPLETED WITH 100% SUCCESS!")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    asyncio.run(run_stage4_test())
