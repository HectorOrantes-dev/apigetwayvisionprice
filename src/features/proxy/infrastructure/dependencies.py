"""Composición de dependencias del proxy."""
from src.features.proxy.application.reenviar_request import ReenviarRequest
from src.features.proxy.infrastructure.httpx_proxy import HttpxReverseProxy
from src.features.proxy.infrastructure.routing_table import RoutingTableEstatica

_routing = RoutingTableEstatica()
_proxy = HttpxReverseProxy()


def get_reenviar_request() -> ReenviarRequest:
    return ReenviarRequest(routing=_routing, proxy=_proxy)
