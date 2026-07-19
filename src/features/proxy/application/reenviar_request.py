"""Caso de uso: recibir una petición entrante y reenviarla al downstream que
corresponda, con el secreto de ese downstream inyectado.
"""
from src.features.proxy.domain.entities import RequestProxeada, RespuestaProxeada
from src.features.proxy.domain.ports import ReverseProxyPort, RoutingTablePort


class ReenviarRequest:
    def __init__(self, routing: RoutingTablePort, proxy: ReverseProxyPort) -> None:
        self._routing = routing
        self._proxy = proxy

    async def execute(self, request: RequestProxeada) -> RespuestaProxeada:
        destino = self._routing.resolver(request.path)
        return await self._proxy.reenviar(destino, request)
