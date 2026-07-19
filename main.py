"""VisionPrice — API Gateway.

Único punto de entrada público para el móvil. Reenvía (reverse proxy) hacia:
  - la API principal (todo lo que no matchee otro prefijo),
  - Proveedores      (/api/v1/proveedores/*),
  - Pagos            (/api/v1/pagos-ms/*),
  - 2FA              (/api/v1/2fa/*).

No reemplaza la autenticación de cada downstream — cada uno sigue validando
su propio JWT exactamente como hoy, con el MISMO Authorization: Bearer que
mandó el cliente (se reenvía intacto, nunca se reemplaza). Lo que este
proceso agrega, todo como capas EXTRA (defensa en profundidad, no en vez de):
  (1) un solo dominio público para el móvil,
  (2) inyecta X-Gateway-Key por downstream para que puedan rechazar tráfico
      que no vino de acá,
  (3) JwtGateMiddleware: valida firma+expiración del JWT (mismo secreto que
      la API principal/Pagos) y corta con 401 ANTES de gastar una llamada al
      downstream — que igual lo vuelve a validar del lado suyo,
  (4) un log centralizado (AuditLoggingMiddleware) de qué usuario pegó qué
      request a qué downstream.

Ver src/features/proxy/infrastructure/routing_table.py para el mapeo exacto.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.features.proxy.infrastructure.dependencies import cerrar_proxy
from src.features.proxy.infrastructure.router import router as proxy_router
from src.shared.audit_logging import AuditLoggingMiddleware
from src.shared.jwt_gate import JwtGateMiddleware
from src.shared.rate_limit import RateLimitMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Reverse proxy / API Gateway de VisionPrice.",
    )

    # Orden: se agregan de adentro hacia afuera (el último add_middleware
    # queda más externo). JwtGate justo antes del proxy (rechaza sin gastar
    # una llamada al downstream). RateLimit por delante de eso (más barato,
    # frena volumen antes de intentar decodificar nada). Auditoría al final
    # para que vea el status FINAL de todo lo demás, incluyendo rechazos.
    app.add_middleware(JwtGateMiddleware)
    app.add_middleware(RateLimitMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(AuditLoggingMiddleware)

    @app.on_event("shutdown")
    async def _cerrar_pool_conexiones() -> None:
        await cerrar_proxy()

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "environment": settings.environment}

    # Catch-all al final: cualquier otro path/método se reenvía.
    app.include_router(proxy_router)

    return app


app = create_app()
