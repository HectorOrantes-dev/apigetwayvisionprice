# VisionPrice — API Gateway

Reverse proxy / punto de entrada único para el móvil. Reenvía hacia:

| Prefijo externo | Downstream | Header de auth que inyecta |
|---|---|---|
| `/api/v1/proveedores/*` | Proveedores (Go) | `X-Api-Key` (el que Proveedores YA exige) |
| `/api/v1/pagos-ms/*` | Pagos (Conekta/PayPal) | `X-Gateway-Key` |
| `/api/v1/2fa/*` | 2FA | `X-Gateway-Key` |
| `/api/v1/extracciones/*` | Extracciones / motor de IA | `X-Api-Key` (el que Extracciones YA exige) |
| todo lo demás (`/api/v1/*`) | API principal | `X-Gateway-Key` |

No reimplementa JWT ni RBAC — cada downstream sigue validando su propia
autenticación exactamente como hoy (`get_current_user`, `require_roles`,
etc.). Ver `src/features/proxy/infrastructure/routing_table.py` para el
mapeo exacto y por qué `/api/v1/pagos-ms` (no `/api/v1/pagos`) para no chocar
con el webhook que ya existe en la API principal.

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
