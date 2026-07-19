"""Tabla de ruteo del gateway.

Mapeo verificado contra las rutas REALES de cada servicio (no supuestas):

  - Proveedores (Go): rutas internas sin prefijo de versión — "/productos",
    "/productos/cercanos", "/products/...". Se les quita literalmente
    "/api/v1/proveedores" del path y se reenvía el resto tal cual.

  - Pagos: rutas internas "/conekta/...", "/paypal/...", "/subscriptions...".
    Prefijo externo elegido a propósito como "/api/v1/pagos-ms" (no
    "/api/v1/pagos") para no chocar con la ruta que YA existe en la API
    principal, /api/v1/pagos/callback — ese es un webhook que Pagos le pega
    DIRECTO a la API principal (server-to-server), nunca pasa por acá.

  - 2FA: rutas internas YA incluyen su propio segmento — "/2fa/send",
    "/2fa/verify". Por eso acá se quita solo "/api/v1" (no "/api/v1/2fa"),
    para no perder el "/2fa" que 2FA espera recibir.

  - Todo lo demás → API principal, sin reescribir el path (sus rutas ya
    viven bajo /api/v1/... y el gateway lo respeta tal cual).
"""
from src.core.config import settings
from src.features.proxy.domain.entities import DestinoRuta
from src.features.proxy.domain.ports import RoutingTablePort

_PROVEEDORES = DestinoRuta(
    nombre="proveedores",
    external_prefix="/api/v1/proveedores",
    base_url=settings.proveedores_base_url,
    gateway_key=settings.proveedores_gateway_key,
    strip_prefix="/api/v1/proveedores",
    # Proveedores ya exige X-Api-Key (middleware.APIKeyMiddleware) en el
    # router de catálogo — PROVEEDORES_GATEWAY_KEY debe ser ese mismo valor
    # que hoy usa la API principal (providers_api_key), no uno nuevo.
    gateway_key_header="X-Api-Key",
)

_PAGOS = DestinoRuta(
    nombre="pagos",
    external_prefix="/api/v1/pagos-ms",
    base_url=settings.pagos_base_url,
    gateway_key=settings.pagos_gateway_key,
    strip_prefix="/api/v1/pagos-ms",
)

_DOSFA = DestinoRuta(
    nombre="2fa",
    external_prefix="/api/v1/2fa",
    base_url=settings.dosfa_base_url,
    gateway_key=settings.dosfa_gateway_key,
    strip_prefix="/api/v1",
)

_MAIN_API = DestinoRuta(
    nombre="main_api",
    external_prefix="",  # catch-all
    base_url=settings.main_api_base_url,
    gateway_key=settings.main_api_gateway_key,
    strip_prefix="",
)

# Orden importa: se evalúan de arriba hacia abajo, el primero que matchea
# gana. _MAIN_API queda al final porque su prefix vacío matchea cualquier cosa.
_RUTAS = [_PROVEEDORES, _PAGOS, _DOSFA, _MAIN_API]


class RoutingTableEstatica(RoutingTablePort):
    def resolver(self, path: str) -> DestinoRuta:
        for destino in _RUTAS:
            if destino.external_prefix and path.startswith(destino.external_prefix):
                return destino
        return _MAIN_API
