"""Puertos compartidos (arquitectura hexagonal).

`Operacion` es lo que los módulos de negocio (citas, mensajería, vista pública) necesitan saber de la operación
del puerto: el reloj, el estado de cada caseta y la agenda. Hoy lo implementa el simulador
(`modulos/simulacion/dominio/motor.Simulador`); en producción lo implementaría un adaptador sobre los sensores de las
casetas y los sistemas de la terminal, sin tocar a quienes lo consumen.

`EstadoOperacion` amplía el puerto con la lectura detallada que necesita el pronóstico para construir sus variables.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from app.nucleo.contracts.enums import Clima, Mundo, TipoCarga
from app.nucleo.contracts.schemas import AccesoEstado

if TYPE_CHECKING:  # solo para el verificador de tipos: el puerto no depende de la simulación en tiempo de ejecución
    from app.modulos.simulacion.dominio.escenario import Escenario
    from app.nucleo.config import Settings


class Operacion(Protocol):
    esc: "Escenario"  # parámetros de la operación: casetas, cargas prioritarias, factores de impacto
    cfg: "Settings"
    clima: Clima

    def ts(self, t: float | None = None) -> datetime:
        """Instante del reloj de la operación (el actual si `t` es None)."""

    def a_minuto(self, dt: datetime) -> float:
        """Minuto del reloj de la operación que corresponde a `dt`."""

    def estado_accesos(self, mundo: Mundo) -> list[AccesoEstado]:
        """Estado actual de cada caseta: abierta o cerrada, fila, espera y semáforo."""

    def acceso_abierto(self, acceso_id: str) -> bool:
        """Si la caseta está abierta en la operación real (con Fluport)."""

    def espera_por_agenda(self, acceso_id: str, inicio: datetime) -> float:
        """Espera estimada solo con la carga ya agendada (para horarios fuera del horizonte del pronóstico)."""

    def inyectar_cita(self, cita_id: int, acceso_id: str, inicio: datetime, tipo_carga: TipoCarga,
                      es_demo: bool = False, agencia_id: str | None = None) -> str:
        """Registra en la operación la llegada prevista del camión de una cita."""

    def cancelar_cita(self, cita_id: int) -> bool:
        """Retira la llegada de una cita. False si no existe o si el camión ya salió."""

    def tiene_cita(self, cita_id: int) -> bool:
        """Si la operación tiene registrada la llegada de esa cita."""


class EstadoOperacion(Operacion, Protocol):
    t: float  # minuto actual del reloj
    mundos: dict[Mundo, Any]  # estado detallado por mundo: filas, atendidos y planificador por caseta
    demanda_conocida: dict[tuple[str, int], int]  # (caseta, franja) -> camiones esperados
    olas: list[tuple[float, float]]  # (inicio, fin) de las olas de demanda por buque
