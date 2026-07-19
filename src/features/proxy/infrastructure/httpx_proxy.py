"""Adaptador del reverse proxy sobre httpx."""
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

        try:
            async with httpx.AsyncClient(timeout=settings.proxy_timeout_seconds) as client:
                resp = await client.request(
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
