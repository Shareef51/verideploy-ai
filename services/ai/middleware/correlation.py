from uuid import UUID, uuid4
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

HEADER = "x-correlation-id"

def _normalize(value: str | None) -> str:
    if not value: return str(uuid4())
    try: return str(UUID(value))
    except ValueError: return str(uuid4())

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id=_normalize(request.headers.get(HEADER))
        request.state.correlation_id=correlation_id
        response=await call_next(request)
        response.headers[HEADER]=correlation_id
        return response
