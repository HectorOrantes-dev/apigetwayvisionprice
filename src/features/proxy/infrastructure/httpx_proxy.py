"""Adaptador del reverse proxy sobre httpx.

Dos cosas para manejar bien muchas conexiones simultáneas:

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
