"""Adaptador del reverse proxy sobre httpx.

Tres cosas para manejar bien muchas conexiones simultáneas y un downstream
saturado:

  1. UN SOLO httpx.AsyncClient reusado (no uno nuevo por request). httpx
     mantiene un pool de conexiones keep-alive por host — sin esto, cada
     petición pagaba una conexión TCP+TLS nueva, que es carísimo bajo carga
     y es lo primero que se satura si entran muchas requests a la vez.
  2. Un contador de peticiones EN VUELO. Por encima del límite, se responde
     503 DE INMEDIATO (sin esperar, sin encolar) en vez de dejar que las
     peticiones se acumulen sin fondo — eso protege tanto a este proceso
     (memoria/file descriptors) como a los downstream de un pico de tráfico
     que los tumbe. No es un semáforo (que haría esperar/encolar) a
     propósito: bajo un pico real, es mejor rechazar rápido y que el cliente
     reintente que acumular una cola larga que igual va a terminar en timeout.
  3. Un circuit breaker POR DOWNSTREAM (ver circuit_breaker.py). Si un
     downstream específico (ej. 2FA) empieza a fallar por timeout/conexión
     de forma repetida, el circuito se abre: las siguientes requests a ESE
     downstream fallan al instante con 503 (sin ni intentar la llamada,
     sin esperar el timeout completo) durante un cooldown — protege al
     downstream de que le sigan pegando mientras está saturado, y le ahorra
     al cliente la espera larga de un timeout que casi seguro iba a fallar
     igual.
"""
import json
import logging

import httpx

from src.core.config import settings
from src.features.proxy.domain.entities import (
    DestinoRuta,
    RequestProxeada,
    RespuestaProxeada,
)
from src.features.proxy.domain.ports import ReverseProxyPort
from src.features.proxy.infrastructure.circuit_breaker import CircuitBreaker

_log = logging.getLogger("gateway.proxy")

# Headers que NO se reenvían tal cual (hop-by-hop / los recalcula httpx solo).
_HEADERS_EXCLUIDOS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
}


class HttpxReverseProxy(ReverseProxyPort):
    def __init__(self) -> None:
        limits = httpx.Limits(
            max_connections=settings.proxy_max_connections,
            max_keepalive_connections=settings.proxy_max_keepalive_connections,
        )
        self._client = httpx.AsyncClient(
            timeout=settings.proxy_timeout_seconds, limits=limits
        )
        self._max_concurrencia = settings.proxy_max_concurrencia
        self._en_vuelo = 0
        self._circuit = CircuitBreaker(
            umbral_fallos=settings.circuit_breaker_umbral_fallos,
            cooldown_seconds=settings.circuit_breaker_cooldown_seconds,
        )

    async def cerrar(self) -> None:
        await self._client.aclose()

    async def reenviar(
        self, destino: DestinoRuta, request: RequestProxeada
    ) -> RespuestaProxeada:
        path_downstream = request.path
        if destino.strip_prefix:
            path_downstream = path_downstream[len(destino.strip_prefix) :] or "/"

        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in _HEADERS_EXCLUIDOS
        }
        if destino.gateway_key:
            headers[destino.gateway_key_header] = destino.gateway_key

        url = f"{destino.base_url.rstrip('/')}{path_downstream}"
        if request.query_string:
            url = f"{url}?{request.query_string}"

        if not self._circuit.permitir(destino.nombre):
            _log.warning(
                "circuito abierto para %s, rechazando sin intentar %s %s",
                destino.nombre, request.method, request.path,
            )
            body = json.dumps(
                {
                    "error": {
                        "code": "service_unavailable",
                        "message": f"El servicio '{destino.nombre}' está temporalmente no disponible, reintentá en unos segundos.",
                    }
                }
            ).encode()
            return RespuestaProxeada(
                status_code=503,
                headers={"content-type": "application/json"},
                body=body,
            )

        if self._en_vuelo >= self._max_concurrencia:
            _log.warning(
                "límite de concurrencia alcanzado (%d en vuelo), rechazando %s %s",
                self._en_vuelo, request.method, request.path,
            )
            body = json.dumps(
                {
                    "error": {
                        "code": "too_many_requests",
                        "message": "El gateway está saturado, reintentá en unos segundos.",
                    }
                }
            ).encode()
            return RespuestaProxeada(
                status_code=503,
                headers={"content-type": "application/json"},
                body=body,
            )

        self._en_vuelo += 1
        try:
            try:
                resp = await self._client.request(
                    request.method, url, headers=headers, content=request.body
                )
            except httpx.HTTPError as exc:
                self._circuit.registrar_fallo(destino.nombre)
                _log.warning(
                    "downstream %s no disponible: %s (url=%s)", destino.nombre, exc, url
                )
                body = json.dumps(
                    {
                        "error": {
                            "code": "bad_gateway",
                            "message": f"El servicio '{destino.nombre}' no respondió.",
                        }
                    }
                ).encode()
                return RespuestaProxeada(
                    status_code=502,
                    headers={"content-type": "application/json"},
                    body=body,
                )

            # Cualquier respuesta HTTP real (incluso un 4xx/5xx de negocio)
            # prueba que el downstream está vivo — solo los errores de RED
            # cuentan para el circuito (ver except arriba).
            self._circuit.registrar_exito(destino.nombre)

            resp_headers = {
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in _HEADERS_EXCLUIDOS
            }
            return RespuestaProxeada(
                status_code=resp.status_code, headers=resp_headers, body=resp.content
            )
        finally:
            self._en_vuelo -= 1
