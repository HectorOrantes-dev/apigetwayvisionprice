"""Configuración central del API Gateway.

Cada downstream tiene su propia base_url + su propio "gateway secret": el
valor que este proceso manda en el header X-Gateway-Key al reenviar la
petición, para que el downstream pueda distinguir "esto vino del gateway" de
"esto vino de cualquiera en internet". No es un JWT ni un secreto de usuario
— es puramente service-to-service, gateway → downstream.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "VisionPrice API Gateway"
    environment: str = "local"
    api_prefix: str = "/api/v1"

    # CORS: en el gateway sí importa (es el único punto público de verdad).
    cors_origins: str = "*"

    # --- Downstream: API principal (todo lo que no matchee otro prefijo) ---
    main_api_base_url: str = "http://localhost:8000"
    main_api_gateway_key: str = ""

    # --- Downstream: Proveedores (Go) ---
    proveedores_base_url: str = ""
    proveedores_gateway_key: str = ""

    # --- Downstream: Pagos (Conekta/PayPal) ---
    pagos_base_url: str = ""
    pagos_gateway_key: str = ""

    # --- Downstream: 2FA ---
    dosfa_base_url: str = ""
    dosfa_gateway_key: str = ""

    # --- Downstream: Extracciones / motor de IA (audio -> JSON estructurado) ---
    # Ya exige X-Api-Key (MICROSERVICE_API_KEY) — igual que Proveedores, no un
    # X-Gateway-Key nuevo. Ver EXTRACTIONS_API_KEY en la API principal.
    extracciones_base_url: str = ""
    extracciones_gateway_key: str = ""

    # Timeout único para las 5 llamadas salientes.
    proxy_timeout_seconds: int = 20

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.cors_origins or self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
