import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
import redis.asyncio as aioredis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.events import get_order_channel, get_order_timeline
from app.core.security import decode_access_token
from app.database.session import SessionLocal
from app.dependencies.auth import get_current_user
from app.models.delivery import DeliveryPartner
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["Real-Time WebSockets & Events"])


@router.websocket("/orders/{order_id}")
async def order_live_tracking_websocket(
    websocket: WebSocket,
    order_id: int,
    token: Optional[str] = Query(None, description="JWT Bearer token for authentication")
):
    """
    Real-Time WebSocket Order Tracking Endpoint.
    
    Architecture:
    1. Authenticates client via query param JWT token.
    2. Authorizes user access (Customer, Restaurant Owner, Assigned Rider, or Admin).
    3. Sends initial connection payload with current order state and full timeline history.
    4. Connects to Redis Pub/Sub channel 'channel:order:{order_id}'.
    5. Streams real-time order state transitions and driver GPS telemetry to the client.
    """
    # Step 1: Authenticate JWT
    if not token:
        # Check Authorization header if query param not present
        auth_header = websocket.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication token")
        return

    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
        user_role = payload.get("role")
    except Exception as e:
        logger.warning(f"WebSocket auth failed for order {order_id}: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    # Step 2: Authorize user access against PostgreSQL
    db: Session = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Order not found")
            return

        is_authorized = False
        if user_role == UserRole.ADMIN.value:
            is_authorized = True
        elif user_role == UserRole.CUSTOMER.value and order.user_id == user_id:
            is_authorized = True
        elif user_role == UserRole.RESTAURANT.value:
            restaurant = db.query(Restaurant).filter(Restaurant.id == order.restaurant_id).first()
            if restaurant and restaurant.owner_id == user_id:
                is_authorized = True
        elif user_role == UserRole.DELIVERY_PARTNER.value:
            partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == user_id).first()
            if partner and order.delivery and order.delivery.partner_id == partner.id:
                is_authorized = True

        if not is_authorized:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized access to order")
            return

        current_status = order.status.value
        restaurant_id = order.restaurant_id
    finally:
        db.close()

    # Step 3: Accept connection & send initial snapshot
    await websocket.accept()
    logger.info(f"WebSocket client connected for order #{order_id} (User ID: {user_id})")

    # Send initial state snapshot and timeline history
    timeline = get_order_timeline(order_id)
    initial_message = {
        "event_type": "CONNECTION_ESTABLISHED",
        "order_id": order_id,
        "current_status": current_status,
        "restaurant_id": restaurant_id,
        "timeline": timeline
    }
    await websocket.send_json(initial_message)

    # Step 4: Subscribe to Redis Pub/Sub channel
    channel_name = get_order_channel(order_id)
    redis_sub = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_sub.pubsub()
    await pubsub.subscribe(channel_name)

    async def receive_client_pings():
        """Listen for incoming messages from client (e.g., heartbeats/pings)."""
        try:
            while True:
                msg = await websocket.receive_text()
                # Optional ping-pong heartbeat
                if msg.strip().lower() == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    async def forward_redis_events():
        """Listen on Redis Pub/Sub channel and push updates to the WebSocket."""
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if message and message.get("type") == "message":
                    payload_data = message.get("data")
                    if isinstance(payload_data, str):
                        await websocket.send_text(payload_data)
                    else:
                        await websocket.send_json(payload_data)
                await asyncio.sleep(0.01)
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            logger.debug(f"PubSub forwarder ended: {ex}")

    ping_task = asyncio.create_task(receive_client_pings())
    event_task = asyncio.create_task(forward_redis_events())

    try:
        # Run until either client disconnects or an error occurs
        done, pending = await asyncio.wait(
            [ping_task, event_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    finally:
        logger.info(f"WebSocket client disconnected for order #{order_id} (User ID: {user_id})")
        try:
            await pubsub.unsubscribe(channel_name)
            await redis_sub.aclose()
        except Exception:
            pass


@router.get("/notifications", tags=["Notifications"], summary="Get in-app notifications for authenticated user")
def list_user_notifications(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user)
):
    """Fetches user notification audit log from Redis."""
    notifications = NotificationService.get_user_notifications(current_user.id, limit=limit)
    return {"user_id": current_user.id, "count": len(notifications), "notifications": notifications}
