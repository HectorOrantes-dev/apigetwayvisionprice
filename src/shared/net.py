"""Utilidades compartidas de red (ASGI scope)."""


def client_ip(scope) -> str:
    # Railway pone al cliente real en X-Forwarded-For (primer hop); si no
    # viene, cae al IP de conexión directa.
    for k, v in scope.get("headers", []):
        if k == b"x-forwarded-for":
            return v.decode().split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "desconocido"
