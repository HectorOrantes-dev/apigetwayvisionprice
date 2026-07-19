"""Composición de dependencias del proxy."""
from src.features.proxy.application.reenviar_request import ReenviarRequest
from src.features.proxy.infrastructure.httpx_proxy import HttpxReverseProxy
from src.features.proxy.infrastructure.routing_table import RoutingTableEstatica

_routing = RoutingTableEstatica()
_proxy = HttpxReverseProxy()


def get_reenviar_request() -> ReenviarRequest:
    return ReenviarRequest(routing=_routing, proxy=_proxy)


async def cerrar_proxy() -> None:
    """Cierra el pool de conexiones del proxy. Llamar en el shutdown de la app."""
    await _proxy.cerrar()
