"""Circuit breaker por downstream (CERRADO / ABIERTO / MEDIO-ABIERTO).

Protege contra un downstream saturado/caído: sin esto, CADA request espera
el timeout completo (hasta PROXY_TIMEOUT_SECONDS) para fallar, y encima le
sigue pegando tráfico a un servicio que ya está sufriendo. Con el circuito
abierto, se falla rápido (sin ni intentar la llamada) durante un cooldown,
dándole aire al downstream para recuperarse.

Solo cuentan como fallo los errores de RED (timeout, conexión rechazada —
httpx.HTTPError). Un 401/404/422 del downstream NO cuenta: esos prueban que
el servicio está vivo y respondiendo, es un error de negocio, no de
disponibilidad.

Es seguro entre corrutinas de asyncio sin locks explícitos: no hay ningún
`await` entre leer y modificar el estado, así que no hay forma de que dos
corrutinas se intercalen a mitad de una transición (asyncio es cooperativo,
solo cede el control en un `await`).
"""
import time
from dataclasses import dataclass, field


@dataclass
class _EstadoCircuito:
    fallos_consecutivos: int = 0
    abierto_hasta: float = 0.0  # timestamp monotonic; 0 = nunca se abrió
    prueba_en_curso: bool = False


class CircuitBreaker:
    def __init__(self, umbral_fallos: int, cooldown_seconds: float) -> None:
        self._umbral = umbral_fallos
        self._cooldown = cooldown_seconds
        self._circuitos: dict[str, _EstadoCircuito] = {}

    def _de(self, nombre: str) -> _EstadoCircuito:
        if nombre not in self._circuitos:
            self._circuitos[nombre] = _EstadoCircuito()
        return self._circuitos[nombre]

    def permitir(self, nombre: str) -> bool:
        """False si el circuito está abierto y hay que rechazar sin intentar."""
        estado = self._de(nombre)
        if estado.abierto_hasta == 0.0:
            return True  # cerrado, nunca se abrió

        ahora = time.monotonic()
        if ahora < estado.abierto_hasta:
            return False  # abierto, todavía en cooldown

        # Cooldown cumplido: solo UNA request de prueba pasa (medio-abierto);
        # el resto sigue rechazándose hasta que esa prueba resuelva.
        if estado.prueba_en_curso:
            return False
        estado.prueba_en_curso = True
        return True

    def registrar_exito(self, nombre: str) -> None:
        estado = self._de(nombre)
        estado.fallos_consecutivos = 0
        estado.abierto_hasta = 0.0
        estado.prueba_en_curso = False

    def registrar_fallo(self, nombre: str) -> None:
        estado = self._de(nombre)
        estado.prueba_en_curso = False
        estado.fallos_consecutivos += 1
        if estado.fallos_consecutivos >= self._umbral:
            estado.abierto_hasta = time.monotonic() + self._cooldown
