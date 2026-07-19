"""Entidades del reverse proxy."""
from dataclasses import dataclass


@dataclass
class DestinoRuta:
    """A qué downstream mandar una petición y cómo reescribir el path.

    external_prefix: el segmento que el cliente (móvil) usa, ej. "/api/v1/2fa".
    base_url: la URL pública del microservicio downstream.
    gateway_key: el secreto que este gateway manda en X-Gateway-Key a ESE
        downstream (cada downstream tiene el suyo — ver core/config.py).
    strip_prefix: qué parte del path se quita antes de reenviar. Casi siempre
        es igual a external_prefix, pero 2FA es la excepción (ver
        routing_table.py) porque sus rutas internas ya incluyen "/2fa".
    """
    nombre: str
    external_prefix: str
    base_url: str
    gateway_key: str
    strip_prefix: str
    # Nombre del header en el que este downstream espera la key. Proveedores
    # ya tiene su propio APIKeyMiddleware esperando "X-Api-Key" — no hay que
    # inventarle un mecanismo nuevo, solo mandarle lo que ya valida.
    gateway_key_header: str = "X-Gateway-Key"


@dataclass
class RequestProxeada:
    method: str
    path: str
    headers: dict[str, str]
    query_string: str
    body: bytes


@dataclass
class RespuestaProxeada:
    status_code: int
    headers: dict[str, str]
    body: bytes
