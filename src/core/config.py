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

    # Timeout único para las 5 llamadas salientes. OJO: /auth/login llama
    # sincrónicamente al microservicio de 2FA (que a su vez manda un email
    # por Gmail SMTP) DENTRO del mismo request — ese sub-request interno ya
    # tiene su propio timeout de 20s (TWO_FACTOR_TIMEOUT en la API
    # principal). Si este valor fuera igual o menor, el gateway corta la
    # conexión ANTES de que la API principal termine de esperar al 2FA,
    # devolviendo un 502 que la app suele mostrar como "sin internet".
    # Este valor SIEMPRE debe quedar por encima de cualquier timeout interno
    # de la cadena, nunca igual.
    proxy_timeout_seconds: int = 40

    # --- Control de concurrencia saliente (hacia los downstream) ---
    # Pool de conexiones HTTP reusadas (keep-alive) hacia TODOS los
    # downstream combinados — evita abrir un socket/TLS handshake nuevo por
    # cada request, que es lo que pasaba antes (AsyncClient nuevo por
    # petición). max_connections limita cuántas conexiones simultáneas puede
    # tener este proceso abiertas en total; si un downstream se cae o se pone
    # lento, esto evita que las peticiones se acumulen sin límite esperando.
    proxy_max_connections: int = 100
    proxy_max_keepalive_connections: int = 20
    # Techo de requests EN VUELO al mismo tiempo dentro de este proceso. Por
    # encima de esto, el gateway responde 503 en vez de seguir aceptando
    # trabajo (protege tanto a este proceso como a los downstream de un pico).
    proxy_max_concurrencia: int = 200

    # --- Rate limiting por IP (ventana deslizante, en memoria) ---
    # Este es el único punto de entrada del móvil ahora, así que es el lugar
    # correcto para centralizar esto en vez de replicarlo en cada downstream.
    # En memoria = por instancia; si Railway escala a >1 réplica, cada una
    # cuenta la suya (suficiente para frenar abuso de un cliente, no perfecto
    # entre réplicas — para eso haría falta Redis).
    rate_limit_max_requests: int = 120
    rate_limit_window_seconds: int = 60

    # --- Validación de JWT en el gateway (capa EXTRA, no reemplaza a la API) ---
    # El MISMO secreto que ya comparten la API principal y Pagos para firmar/
    # validar el JWT de usuario (no es un X-Gateway-Key, es literalmente
    # JWT_SECRET de esos dos servicios). El gateway lo usa para rechazar
    # tokens inválidos/vencidos ANTES de gastar una llamada al downstream —
    # el downstream sigue validando el mismo JWT de nuevo, como siempre.
    # Vacío = no-op (no bloquea nada) — poné el valor real para activarlo.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"

    # --- Circuit breaker por downstream ---
    # Si un downstream falla (timeout/conexión — NO errores de negocio como
    # 401/404, esos prueban que está vivo) esta cantidad de veces seguidas,
    # el circuito se ABRE: durante el cooldown, el gateway responde 503 DE
    # INMEDIATO sin ni intentar la llamada, en vez de que cada request espere
    # el timeout completo (PROXY_TIMEOUT_SECONDS) para fallar. Protege al
    # downstream saturado de que le sigan pegando, y le da al cliente un
    # error rápido en vez de una espera larga que la app suele confundir con
    # "sin internet". Después del cooldown, deja pasar UNA request de prueba
    # (medio-abierto): si funciona, cierra el circuito; si falla, lo reabre.
    circuit_breaker_umbral_fallos: int = 5
    circuit_breaker_cooldown_seconds: int = 30

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.cors_origins or self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
