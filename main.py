"""VisionPrice — API Gateway.

Único punto de entrada público para el móvil. Reenvía (reverse proxy) hacia:
  - la API principal (todo lo que no matchee otro prefijo),
  - Proveedores      (/api/v1/proveedores/*),
  - Pagos            (/api/v1/pagos-ms/*),
  - 2FA              (/api/v1/2fa/*).

No reimplementa JWT/RBAC — cada downstream sigue validando su propia
autenticación exactamente como hoy. Lo que este proceso agrega es: (1) un
solo dominio público para el móvil, (2) inyecta X-Gateway-Key por downstream
para que puedan rechazar tráfico que no vino de acá.

Ver src/features/proxy/infrastructure/routing_table.py para el mapeo exacto.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.features.proxy.infrastructure.router import router as proxy_router


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Reverse proxy / API Gateway de VisionPrice.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "environment": settings.environment}

    # Catch-all al final: cualquier otro path/método se reenvía.
    app.include_router(proxy_router)

    return app


app = create_app()
