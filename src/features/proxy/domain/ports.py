"""Puertos del reverse proxy."""
from abc import ABC, abstractmethod

from src.features.proxy.domain.entities import (
    DestinoRuta,
    RequestProxeada,
    RespuestaProxeada,
)


class ReverseProxyPort(ABC):
    @abstractmethod
    async def reenviar(
        self, destino: DestinoRuta, request: RequestProxeada
    ) -> RespuestaProxeada:
        ...


class RoutingTablePort(ABC):
    @abstractmethod
    def resolver(self, path: str) -> DestinoRuta:
        """Encuentra a qué downstream corresponde este path. El catch-all
        (API principal) nunca falla — es el default si nada más matchea."""
