from typing import Callable
from fastapi import HTTPException, Request, status

from app.core.redis import redis_client


def rate_limit(max_requests: int = 5, window_seconds: int = 60, endpoint_tag: str = "generic") -> Callable:
    """
    Distributed API Rate Limiter using Redis INCR and EXPIRE.
    
    Interview Concepts:
    - Centralized state across multiple horizontally scaled backend instances.
    - Atomic INCR ensures accurate tracking without race conditions.
    - Setting TTL on first request (count == 1) ensures automatic window reset.
    - Returns HTTP 429 Too Many Requests with standard 'Retry-After' header.
    - Gracefully fails open if Redis is temporarily unreachable.
    """
    async def rate_limiter_dependency(request: Request):
        # Extract client IP (handling standard proxies/load balancers)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        elif request.client:
            client_ip = request.client.host
        else:
            client_ip = "127.0.0.1"

        rate_key = f"rate_limit:{endpoint_tag}:{client_ip}"

        try:
            # Atomic increment
            current_requests = redis_client.incr(rate_key)
            
            # If this is the first request in the current window, set the TTL
            if current_requests == 1:
                redis_client.expire(rate_key, window_seconds)

            if current_requests > max_requests:
                remaining_ttl = redis_client.ttl(rate_key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many requests. Rate limit of {max_requests} attempts per {window_seconds} seconds exceeded.",
                    headers={"Retry-After": str(max(remaining_ttl, 1))}
                )
        except HTTPException:
            raise
        except Exception:
            # If Redis connection fails, gracefully fail open so legit users aren't locked out
            pass

    return rate_limiter_dependency
