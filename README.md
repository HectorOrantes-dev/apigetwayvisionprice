# VisionPrice — API Gateway

Reverse proxy / punto de entrada único para el móvil. Reenvía hacia:

| Prefijo externo | Downstream | Header de auth que inyecta |
|---|---|---|
| `/api/v1/proveedores/*` | Proveedores (Go) | `X-Api-Key` (el que Proveedores YA exige) |
| `/api/v1/pagos-ms/*` | Pagos (Conekta/PayPal) | `X-Gateway-Key` |
| `/api/v1/2fa/*` | 2FA | `X-Gateway-Key` |
| `/api/v1/extracciones/*` | Extracciones / motor de IA | `X-Api-Key` (el que Extracciones YA exige) |
| todo lo demás (`/api/v1/*`) | API principal | `X-Gateway-Key` |

No reemplaza la autenticación de cada downstream — cada uno sigue validando
su propio JWT/RBAC exactamente como hoy (`get_current_user`, `require_roles`,
etc.). Ver `src/features/proxy/infrastructure/routing_table.py` para el
mapeo exacto y por qué `/api/v1/pagos-ms` (no `/api/v1/pagos`) para no chocar
con el webhook que ya existe en la API principal.

## Identidad y validación de JWT (capa EXTRA, no en vez de)

El `Authorization: Bearer` del cliente se reenvía **intacto** a cada
downstream — nunca se reemplaza ni se traduce a otro header. Cada downstream
sigue siendo la autoridad final: valida el mismo JWT con su propio
`get_current_user`, exactamente como si el gateway no existiera.

Además de eso, `JwtGateMiddleware` (`src/shared/jwt_gate.py`) agrega un
rechazo TEMPRANO: si el token falta, está mal formado, vencido o tiene firma
inválida, corta con `401` **antes** de gastar una llamada de red al
downstream. Usa el mismo `JWT_SECRET`/`JWT_ALGORITHM` que ya comparten la API
principal y Pagos — no es un secreto nuevo.

**Rutas exentas** (verificadas contra el código real, no adivinadas — ver
`_EXENTOS_MAIN_API`/`_EXENTOS_PAGOS` en `jwt_gate.py`): login, register,
password reset, Google auth, `/roles`, webhooks internos (Conekta/PayPal/ML/
notificaciones, que usan `X-Api-Key` propio, no JWT de usuario). Los
downstream que no usan JWT de usuario en absoluto (2FA, Proveedores,
Extracciones — usan `X-Api-Key` o, en 2FA, nada todavía) quedan exentos por
completo.

Si `JWT_SECRET` no está configurado, esta capa es un no-op total — el
gateway sigue funcionando igual que sin ella, solo pierde el rechazo
temprano (el downstream sigue protegiendo igual).

## Cómo maneja muchas conexiones a la vez

- **Un solo `httpx.AsyncClient` reusado** (`HttpxReverseProxy`, creado una
  vez, no por request) con pool de conexiones keep-alive
  (`PROXY_MAX_CONNECTIONS` / `PROXY_MAX_KEEPALIVE_CONNECTIONS`) — evita abrir
  un socket/TLS nuevo por cada petición.
- **Techo de requests en vuelo** (`PROXY_MAX_CONCURRENCIA`): por encima de
  ese número, responde `503` de inmediato en vez de encolar sin fondo.
- **Rate limit por IP** (`RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`,
  ver `src/shared/rate_limit.py`): ventana deslizante en memoria, responde
  `429` si un mismo cliente se pasa. Es el único punto de entrada del móvil
  ahora, así que es el lugar correcto para esto en vez de repetirlo en cada
  downstream (2FA, por ejemplo, no tenía nada).

Ambos son en memoria — por instancia de proceso. Si Railway escala el
gateway a más de una réplica, cada una cuenta lo suyo (suficiente para
frenar un cliente que se desboca; no es un límite exacto entre réplicas —
para eso haría falta un backend compartido tipo Redis).

## Qué pasa si un downstream se satura (circuit breaker)

`CircuitBreaker` (`src/features/proxy/infrastructure/circuit_breaker.py`),
uno por downstream (`main_api`, `pagos`, `2fa`, `proveedores`,
`extracciones`):

- **Cerrado** (normal): las requests pasan. Solo cuentan como fallo los
  errores de RED (timeout, conexión rechazada) — un `401`/`404`/`422` del
  downstream NO cuenta, eso prueba que está vivo.
- Tras `CIRCUIT_BREAKER_UMBRAL_FALLOS` fallos de red **consecutivos**, se
  **abre**: durante `CIRCUIT_BREAKER_COOLDOWN_SECONDS`, cualquier request a
  ese downstream se rechaza con `503` al instante — sin ni intentar la
  llamada, sin esperar `PROXY_TIMEOUT_SECONDS`. Protege al downstream
  saturado de que le sigan pegando, y evita que cada usuario espere el
  timeout completo para enterarse de que no sirve de nada reintentar ya.
- Pasado el cooldown, deja pasar **una** request de prueba (medio-abierto);
  las demás siguen rechazándose hasta que esa resuelva. Si funciona, cierra
  el circuito; si falla, lo vuelve a abrir.

Caso concreto que motivó esto: si el microservicio de 2FA se satura y tarda
40s+ en responder, sin circuit breaker cada intento de login espera el
timeout completo (hasta `PROXY_TIMEOUT_SECONDS`) antes de fallar, Y le sigue
mandando tráfico a un servicio que ya está sufriendo. Con el circuito
abierto, después de unos pocos fallos el resto de los logins fallan al
instante con un mensaje claro, y 2FA deja de recibir tráfico nuevo durante
el cooldown para poder recuperarse.

## Estado del rollout

**Fase actual: el gateway existe y funciona, pero NINGÚN downstream lo exige
todavía.** Los 4 servicios (API principal, Pagos, 2FA — Proveedores ya lo
exigía de antes) tienen un middleware `GatewayKeyMiddleware` en modo
**dual-accept**: si configurás `GATEWAY_SHARED_KEY` en cada uno y el header
`X-Gateway-Key` viene, lo valida; si NO viene, deja pasar igual. Esto permite
probar el gateway en producción en paralelo, sin romper el tráfico directo
que la app móvil (ya publicada) sigue mandando hoy.

### Pasos para completar el rollout

1. **Deployar este repo** como 5to servicio en Railway (o donde corresponda),
   con las variables de `.env.example` completas — cada `*_GATEWAY_KEY` debe
   ser un secreto random largo (`openssl rand -hex 32`), **distinto por
   servicio**, EXCEPTO `PROVEEDORES_GATEWAY_KEY` que debe ser el mismo valor
   que ya existe hoy como `PROVIDERS_API_KEY`/`MICROSERVICE_API_KEY`.
2. **Configurar `GATEWAY_SHARED_KEY`** en la API principal, Pagos y 2FA con
   esos mismos valores (cada uno el suyo).
3. **Probar el gateway en producción** apuntándolo a los 3 servicios reales,
   verificando que cada ruta responda igual que pegándole directo.
4. **Actualizar la app móvil** para que apunte al dominio del gateway en vez
   de a los 4 dominios de Railway actuales. Requiere un release de la app.
5. **Recién cuando la mayoría del tráfico venga del gateway** (medible por
   logs / métricas de cada servicio), cambiar el modo dual-accept a
   estricto en los 4 `GatewayKeyMiddleware` (un cambio de una línea en cada
   uno — ver el comentario "modo estricto" en cada archivo
   `gateway_key.py`/`GatewayKeyMiddleware`).
6. Solo en ese punto, los 4 servicios dejan de ser alcanzables directamente
   sin pasar por el gateway.

**No saltar al paso 6 antes del 4** — la app móvil ya publicada seguiría
pegándole directo a los dominios viejos y quedaría rota hasta que los
usuarios actualicen.

## Correr local

```bash
cp .env.example .env  # completar las URLs/keys
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```
