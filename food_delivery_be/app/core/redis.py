import json
import logging
from typing import Any, Optional
import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Reusable connection pool with automatic string decoding (UTF-8)
redis_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=20
)

redis_client = redis.Redis(connection_pool=redis_pool)


def get_redis() -> redis.Redis:
    """Returns the shared Redis client instance."""
    return redis_client


def is_redis_healthy() -> bool:
    """Check if the Redis instance is reachable and responding to PING."""
    try:
        return bool(redis_client.ping())
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
        return False


def get_cache(key: str) -> Optional[Any]:
    """
    Safely retrieves and deserializes JSON data from Redis.
    Falls back gracefully to None if Redis is unreachable (graceful degradation).
    """
    try:
        cached_data = redis_client.get(key)
        if cached_data:
            return json.loads(cached_data)
        return None
    except Exception as e:
        logger.warning(f"Redis GET failed for key '{key}': {e}. Falling back to DB.")
        return None


def set_cache(key: str, data: Any, ttl: Optional[int] = None) -> bool:
    """
    Safely serializes and stores JSON data in Redis with a TTL (Time-To-Live).
    """
    if ttl is None:
        ttl = settings.CACHE_TTL_SECONDS
    try:
        serialized = json.dumps(data)
        return bool(redis_client.set(key, serialized, ex=ttl))
    except Exception as e:
        logger.warning(f"Redis SET failed for key '{key}': {e}.")
        return False


def delete_cache(key: str) -> bool:
    """
    Invalidates a specific cached key.
    """
    try:
        return bool(redis_client.delete(key))
    except Exception as e:
        logger.warning(f"Redis DELETE failed for key '{key}': {e}.")
        return False


def delete_pattern(pattern: str) -> int:
    """
    Invalidates all keys matching a pattern (e.g., 'restaurant:*:menu').
    Uses SCAN instead of KEYS to avoid blocking the single-threaded Redis event loop.
    """
    deleted_count = 0
    try:
        cursor = "0"
        while cursor != 0:
            cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                deleted_count += redis_client.delete(*keys)
        return deleted_count
    except Exception as e:
        logger.warning(f"Redis SCAN and DELETE failed for pattern '{pattern}': {e}.")
        return deleted_count


# Atomic Lua script: only delete the key if the token matches
LUA_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


from contextlib import contextmanager
import time
import uuid


@contextmanager
def distributed_lock(
    lock_key: str,
    lock_timeout_seconds: int = 10,
    acquire_timeout_seconds: float = 5.0,
    retry_interval_seconds: float = 0.05
):
    """
    Production-grade Redis Distributed Lock using SET NX EX and atomic Lua release.
    
    1. Generates a unique UUID token so only the lock owner can release it.
    2. Retries up to acquire_timeout_seconds.
    3. Auto-expires after lock_timeout_seconds to prevent deadlocks on process crash.
    4. Releases safely using an atomic Lua script to prevent accidental deletion of another worker's lock.
    """
    token = str(uuid.uuid4())
    deadline = time.time() + acquire_timeout_seconds
    acquired = False

    try:
        while time.time() < deadline:
            # Atomic SET NX EX
            if redis_client.set(lock_key, token, nx=True, ex=lock_timeout_seconds):
                acquired = True
                break
            time.sleep(retry_interval_seconds)

        if not acquired:
            raise TimeoutError(f"Could not acquire distributed lock for key '{lock_key}' within {acquire_timeout_seconds}s")

        yield token

    finally:
        if acquired:
            try:
                # Atomic Lua evaluation
                redis_client.eval(LUA_RELEASE_LOCK_SCRIPT, 1, lock_key, token)
            except Exception as e:
                logger.warning(f"Error releasing lock for key '{lock_key}': {e}")

