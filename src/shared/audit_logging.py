"""Logging centralizado de auditoría — NO es autenticación ni autorización.

Decodifica el claim `sub`/`rol` del JWT que ya viaja en el request (base64,
SIN validar firma ni expiración) solo para poder loguear "qué usuario pegó
qué request, a qué downstream, cuándo, desde qué IP" en un único lugar.

Ningún downstream deja de validar el JWT de verdad — esto es puramente un
log adicional para poder reconstruir el rastro de un usuario (o de un token
robado) sin tener que ir servicio por servicio. Si el token es inválido o
está vencido, igual se loguea con lo que diga el payload (aunque el
downstream lo termine rechazando con 401) — es "quién LO INTENTÓ", no una
confirmación de que se le permitió.
"""
import base64
import json
import logging
import time

from src.features.proxy.infrastructure.routing_table import RoutingTableEstatica
from src.shared.net import client_ip

_log = logging.getLogger("gateway.audit")
_routing = RoutingTableEstatica()
_EXCLUIDOS = ("/health",)


def _decode_jwt_claims(auth_header: str | None) -> dict:
    if not auth_header or not auth_header.startswith("Bearer "):
        return {}
    token = auth_header[7:]
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(payload)
    except Exception:  # noqa: BLE001 — un JWT malformado no debe romper el log
        return {}


class AuditLoggingMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in _EXCLUIDOS:
            return await self.app(scope, receive, send)

        inicio = time.monotonic()
        auth = None
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                auth = v.decode()
                break
        claims = _decode_jwt_claims(auth)
        destino = _routing.resolver(scope.get("path", ""))
        ip = client_ip(scope)

        status_holder = {"status": None}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)

        duracion_ms = round((time.monotonic() - inicio) * 1000, 1)
        _log.info(
            "usuario=%s rol=%s ip=%s metodo=%s path=%s downstream=%s status=%s duracion_ms=%s",
            claims.get("sub", "-"),
            claims.get("rol", "-"),
            ip,
            scope.get("method"),
            scope.get("path"),
            destino.nombre,
            status_holder["status"],
            duracion_ms,
        )
