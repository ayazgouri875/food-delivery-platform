import json
import logging
import math
import time
from typing import Any, Dict, Optional, Tuple

from app.core.events import EventType, publish_order_event
from app.core.redis import redis_client

logger = logging.getLogger(__name__)

# Average urban two-wheeler speed: 25 km/h = ~416 meters per minute
AVERAGE_SPEED_METERS_PER_MINUTE = 416.0
HANDOFF_BUFFER_MINUTES = 3.0


def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes great-circle distance between two GPS coordinates in meters
    using the Haversine formula.
    """
    R = 6371000.0  # Earth's radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def calculate_eta_minutes(distance_meters: float) -> int:
    """Estimates travel time in minutes based on urban delivery speed profile."""
    transit_minutes = distance_meters / AVERAGE_SPEED_METERS_PER_MINUTE
    total_minutes = math.ceil(transit_minutes + HANDOFF_BUFFER_MINUTES)
    return max(1, total_minutes)


class TelemetryService:
    """
    Driver Geolocation Telemetry Service.
    
    1. Indexes driver GPS coordinates in Redis Geospatial (GEOADD).
    2. Stores recent telemetry state with TTL.
    3. Calculates real-time distance and ETA to delivery destination.
    4. Broadcasts live location updates to the order's real-time Pub/Sub channel.
    """

    @classmethod
    def record_partner_location(
        cls,
        partner_id: int,
        latitude: float,
        longitude: float,
        heading: Optional[float] = None,
        speed: Optional[float] = None,
        active_order_id: Optional[int] = None,
        dest_latitude: Optional[float] = None,
        dest_longitude: Optional[float] = None
    ) -> Dict[str, Any]:
        now = time.time()
        telemetry_payload = {
            "partner_id": partner_id,
            "latitude": latitude,
            "longitude": longitude,
            "heading": heading,
            "speed": speed,
            "updated_at": now
        }

        try:
            # 1. Update Redis Geospatial index (Note: longitude precedes latitude in Redis GEOADD)
            redis_client.geoadd("geo:delivery_partners", (longitude, latitude, str(partner_id)))

            # 2. Cache raw telemetry snapshot (TTL 1 hour)
            key = f"partner:{partner_id}:telemetry"
            redis_client.set(key, json.dumps(telemetry_payload), ex=3600)
        except Exception as e:
            logger.warning(f"Error caching partner {partner_id} telemetry: {e}")

        # 3. If there is an active order being delivered, compute distance & ETA and broadcast live event!
        distance_meters = None
        eta_minutes = None

        if dest_latitude is not None and dest_longitude is not None:
            distance_meters = round(calculate_haversine_distance(latitude, longitude, dest_latitude, dest_longitude), 1)
            eta_minutes = calculate_eta_minutes(distance_meters)
            telemetry_payload["distance_meters"] = distance_meters
            telemetry_payload["eta_minutes"] = eta_minutes

        if active_order_id:
            publish_order_event(
                order_id=active_order_id,
                event_type=EventType.DRIVER_LOCATION_UPDATED,
                data={
                    "partner_id": partner_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "heading": heading,
                    "speed": speed,
                    "distance_meters": distance_meters,
                    "eta_minutes": eta_minutes,
                    "timestamp": now
                }
            )

        return telemetry_payload

    @classmethod
    def get_latest_location(cls, partner_id: int) -> Optional[Dict[str, Any]]:
        """Fetch the latest reported GPS telemetry for a delivery partner."""
        try:
            raw = redis_client.get(f"partner:{partner_id}:telemetry")
            if raw:
                return json.loads(raw)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch partner telemetry: {e}")
            return None
