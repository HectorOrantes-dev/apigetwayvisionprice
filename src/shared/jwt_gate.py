"""Validación de JWT en el gateway — capa EXTRA, no reemplaza la de la API.

El downstream (API principal / Pagos) sigue validando el JWT exactamente
como siempre (get_current_user, mismo secreto). Esto agrega un rechazo
TEMPRANO en el gateway: si el token falta, está mal formado, vencido o tiene
firma inválida, corta acá con 401 — sin gastar una llamada de red al
downstream. Es defensa en profundidad, no un reemplazo: si este middleware
tuviera un bug y dejara pasar algo que no debía, el downstream lo va a
rechazar igual, porque sigue validando por su cuenta.

Rutas exentas (verificadas contra el código real de cada servicio — ver
conversación de diseño, NO adivinadas): login/register/password/google-auth
(el usuario todavía no tiene JWT ahí), webhooks internos (usan X-Api-Key, no
JWT de usuario), y los downstream que ni siquiera usan JWT de usuario
(2FA, Proveedores, Extracciones — estos usan X-Api-Key o, en 2FA, nada).
"""
import json

import jwt

from src.core.config import settings
from src.features.proxy.infrastructure.routing_table import RoutingTableEstatica

_routing = RoutingTableEstatica()

# Downstream que NO usan el JWT de usuario móvil en absoluto (X-Api-Key
# propio, o —2FA— ninguna auth todavía). El gateway no debe intentar validar
# nada ahí con este secreto: sería el secreto equivocado.
_DESTINOS_SIN_JWT_USUARIO = {"2fa", "proveedores", "extracciones"}

# Paths exactos (gateway-facing, con el prefijo tal cual lo ve el cliente)
# que SÍ van a main_api/pagos pero no llevan JWT — verificados uno por uno
# contra get_current_user/require_internal_key en el código real.
_EXENTOS_MAIN_API = {
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/login/verify",
    "/api/v1/auth/password/forgot",
    "/api/v1/auth/password/verify-code",
    "/api/v1/auth/password/reset",
    "/api/v1/auth/google/login",
    "/api/v1/auth/google/register",
    "/api/v1/roles",
    # Webhooks/cron internos: X-Api-Key (require_internal_key), no JWT.
    "/api/v1/pagos/callback",
    "/api/v1/ml/callback",
    "/api/v1/notificaciones/jobs/vencimientos",
    "/api/v1/notificaciones/eventos",
}
_EXENTOS_PAGOS = {
    "/api/v1/pagos-ms/conekta/webhook",
    "/api/v1/pagos-ms/paypal/webhook",
}
_SIEMPRE_EXENTOS = {"/health", "/docs", "/redoc", "/openapi.json"}


def _esta_exento(destino_nombre: str, path: str) -> bool:
    if path in _SIEMPRE_EXENTOS:
        return True
    if destino_nombre in _DESTINOS_SIN_JWT_USUARIO:
        return True
    if destino_nombre == "main_api":
        return path in _EXENTOS_MAIN_API
    if destino_nombre == "pagos":
        return path in _EXENTOS_PAGOS
    return False


class JwtGateMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.jwt_secret:
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        destino = _routing.resolver(path)
        if _esta_exento(destino.nombre, path):
            return await self.app(scope, receive, send)

        token = _extraer_bearer(scope)
        if token is None:
            return await _rechazar(send, "Falta el header Authorization: Bearer <token>.")

        try:
            jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except jwt.ExpiredSignatureError:
            return await _rechazar(send, "El token expiró.")
        except jwt.InvalidTokenError:
            return await _rechazar(send, "Token inválido.")

        return await self.app(scope, receive, send)


def _extraer_bearer(scope) -> str | None:
    for k, v in scope.get("headers", []):
        if k == b"authorization":
            valor = v.decode()
            if valor.startswith("Bearer "):
                return valor[7:]
            return None
    return None


async def _rechazar(send, mensaje: str) -> None:
    body = json.dumps({"error": {"code": "unauthorized", "message": mensaje}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
