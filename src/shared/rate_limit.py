"""Rate limiting por IP (ventana deslizante, en memoria).

Antes, cada microservicio tenía que resolver esto por su cuenta (o no lo
resolvía — 2FA no tenía nada). Como el gateway es ahora el único punto de
entrada del móvil, es el lugar correcto para centralizarlo.

En memoria = por instancia de proceso. Si Railway escala a más de una
réplica, cada una lleva su propio conteo — alcanza para frenar un cliente
que se desboca, no es un límite exacto entre réplicas (para eso haría falta
un backend compartido tipo Redis).
"""
import json
import time
from collections import defaultdict, deque

from src.core.config import settings
from src.shared.net import client_ip

_EXCLUIDOS = ("/health",)


class RateLimitMiddleware:
    def __init__(self, app) -> None:
        self.app = app
        self._buckets: dict[str, deque] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if path in _EXCLUIDOS:
            return await self.app(scope, receive, send)

        ip = client_ip(scope)
        ahora = time.monotonic()
        limite = ahora - settings.rate_limit_window_seconds
        dq = self._buckets[ip]
        while dq and dq[0] < limite:
            dq.popleft()

        if len(dq) >= settings.rate_limit_max_requests:
            return await _rechazar(send)

        dq.append(ahora)
        return await self.app(scope, receive, send)


async def _rechazar(send) -> None:
    body = json.dumps(
        {
            "error": {
                "code": "too_many_requests",
                "message": "Demasiadas peticiones. Esperá unos segundos.",
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
