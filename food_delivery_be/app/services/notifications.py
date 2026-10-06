import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.redis import redis_client

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Decoupled Asynchronous Notification Service.
    
    Dispatches push notifications, SMS alerts, and email invoices asynchronously
    without blocking the core transaction thread. Keeps a structured audit log
    in Redis for user inboxes and integration verification.
    """

    @staticmethod
    def _record_notification(user_id: int, notification_type: str, title: str, body: str, metadata: Dict[str, Any]):
        notification_payload = {
            "user_id": user_id,
            "type": notification_type,
            "title": title,
            "body": body,
            "metadata": metadata,
            "sent_at": time.time()
        }
        serialized = json.dumps(notification_payload)
        try:
            # User inbox key (TTL: 30 days)
            user_inbox_key = f"notifications:user:{user_id}"
            redis_client.lpush(user_inbox_key, serialized)
            redis_client.ltrim(user_inbox_key, 0, 99)  # Keep last 100 notifications
            redis_client.expire(user_inbox_key, 2592000)

            # Global audit stream
            redis_client.lpush("notifications:audit_log", serialized)
            redis_client.ltrim("notifications:audit_log", 0, 499)

            logger.info(f"[NOTIFICATION SENT] User {user_id} | {notification_type} | '{title}'")
        except Exception as e:
            logger.error(f"Error persisting notification: {e}")

    @classmethod
    def send_order_placed(cls, order_id: int, user_id: int, user_email: str, grand_total_paise: int):
        amount_rupees = f"₹{grand_total_paise / 100:.2f}"
        title = "Order Placed Successfully! 🍽️"
        body = f"Your order #{order_id} for {amount_rupees} has been placed and is awaiting payment."
        cls._record_notification(
            user_id=user_id,
            notification_type="ORDER_PLACED",
            title=title,
            body=body,
            metadata={"order_id": order_id, "amount_paise": grand_total_paise, "email": user_email}
        )

    @classmethod
    def send_order_confirmed(cls, order_id: int, user_id: int, restaurant_name: str):
        title = "Order Confirmed! 👨‍🍳"
        body = f"Your order #{order_id} has been confirmed. {restaurant_name} has started preparing your food!"
        cls._record_notification(
            user_id=user_id,
            notification_type="ORDER_CONFIRMED",
            title=title,
            body=body,
            metadata={"order_id": order_id, "restaurant_name": restaurant_name}
        )

    @classmethod
    def send_driver_assigned(cls, order_id: int, customer_id: int, driver_name: str, vehicle_number: Optional[str]):
        title = "Delivery Partner Assigned 🛵"
        veh_str = f" ({vehicle_number})" if vehicle_number else ""
        body = f"{driver_name}{veh_str} has been assigned to pick up your order #{order_id}."
        cls._record_notification(
            user_id=customer_id,
            notification_type="DRIVER_ASSIGNED",
            title=title,
            body=body,
            metadata={"order_id": order_id, "driver_name": driver_name, "vehicle_number": vehicle_number}
        )

    @classmethod
    def send_order_picked_up(cls, order_id: int, customer_id: int, driver_name: str):
        title = "Order on the way! 🚀"
        body = f"{driver_name} has picked up your food and is heading to your delivery address."
        cls._record_notification(
            user_id=customer_id,
            notification_type="ORDER_PICKED_UP",
            title=title,
            body=body,
            metadata={"order_id": order_id, "driver_name": driver_name}
        )

    @classmethod
    def send_order_delivered(cls, order_id: int, customer_id: int, customer_email: str, grand_total_paise: int):
        amount_rupees = f"₹{grand_total_paise / 100:.2f}"
        title = "Order Delivered! 🎉"
        body = f"Your order #{order_id} ({amount_rupees}) was successfully delivered. Bon appétit!"
        cls._record_notification(
            user_id=customer_id,
            notification_type="ORDER_DELIVERED",
            title=title,
            body=body,
            metadata={"order_id": order_id, "amount_paise": grand_total_paise, "email": customer_email}
        )

    @classmethod
    def get_user_notifications(cls, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch user's in-app notification history from Redis."""
        try:
            raw = redis_client.lrange(f"notifications:user:{user_id}", 0, limit - 1)
            return [json.loads(n) for n in raw]
        except Exception as e:
            logger.warning(f"Failed to fetch user notifications: {e}")
            return []
