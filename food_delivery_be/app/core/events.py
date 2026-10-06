import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.redis import redis_client

logger = logging.getLogger(__name__)

# Canonical Event Types across the Food Delivery Lifecycle
class EventType:
    ORDER_CREATED = "ORDER_CREATED"
    PAYMENT_SUCCESS = "PAYMENT_SUCCESS"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    ORDER_PREPARING = "ORDER_PREPARING"
    ORDER_READY_FOR_PICKUP = "ORDER_READY_FOR_PICKUP"
    DRIVER_ASSIGNED = "DRIVER_ASSIGNED"
    DRIVER_LOCATION_UPDATED = "DRIVER_LOCATION_UPDATED"
    ORDER_PICKED_UP = "ORDER_PICKED_UP"
    ORDER_DELIVERED = "ORDER_DELIVERED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


def get_order_channel(order_id: int) -> str:
    """Returns the Redis Pub/Sub channel key for an order."""
    return f"channel:order:{order_id}"


def get_order_timeline_key(order_id: int) -> str:
    """Returns the Redis list key storing the historical event audit trail."""
    return f"timeline:order:{order_id}"


def publish_order_event(order_id: int, event_type: str, data: Dict[str, Any]) -> bool:
    """
    Publishes an event to the order's real-time Pub/Sub channel and
    appends it to the durable Redis event timeline for replay on reconnect.
    
    Payload schema:
    {
        "order_id": int,
        "event_type": str,
        "timestamp": float,
        "data": dict
    }
    """
    payload = {
        "order_id": order_id,
        "event_type": event_type,
        "timestamp": time.time(),
        "data": data
    }
    serialized = json.dumps(payload)

    try:
        # 1. Append to timeline list (TTL 7 days)
        timeline_key = get_order_timeline_key(order_id)
        redis_client.rpush(timeline_key, serialized)
        redis_client.expire(timeline_key, 604800)  # 7 days

        # 2. Publish to live Redis Pub/Sub channel
        channel = get_order_channel(order_id)
        subscribers = redis_client.publish(channel, serialized)
        logger.info(f"Published event '{event_type}' to channel '{channel}' ({subscribers} active subscribers)")
        return True
    except Exception as e:
        logger.error(f"Failed to publish event '{event_type}' for order {order_id}: {e}")
        return False


def get_order_timeline(order_id: int) -> List[Dict[str, Any]]:
    """Retrieves all past events recorded in the order's timeline."""
    try:
        timeline_key = get_order_timeline_key(order_id)
        raw_events = redis_client.lrange(timeline_key, 0, -1)
        return [json.loads(ev) for ev in raw_events]
    except Exception as e:
        logger.warning(f"Failed to fetch timeline for order {order_id}: {e}")
        return []
