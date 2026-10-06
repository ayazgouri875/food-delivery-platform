import json
import logging
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("api.access")


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """
    Distributed Tracing & Correlation ID Middleware.
    
    1. Extracts 'X-Request-ID' from incoming headers or generates a new UUID.
    2. Attaches request_id to request.state for downstream controllers.
    3. Emits structured JSON access logs with duration, path, and status code.
    4. Sets 'X-Request-ID' in the outgoing HTTP response headers.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Resolve Correlation ID
        request_id = request.headers.get("x-request-id")
        if not request_id:
            request_id = f"req_{uuid.uuid4().hex[:16]}"

        request.state.request_id = request_id

        # 2. Time request execution
        start_time = time.time()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            # 3. Propagate Correlation ID to client response header
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            logger.error(json.dumps({
                "event": "unhandled_exception",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "error": str(exc)
            }))
            raise exc
        finally:
            duration_ms = round((time.time() - start_time) * 1000, 2)

            # Suppress high-frequency polling/health logs from spamming audit logs
            if request.url.path not in ("/health/live", "/metrics"):
                log_record = {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else "unknown"
                }
                logger.info(json.dumps(log_record))
