"""Puertos (Interfaces segregadas ISP y DIP) de la capa de Aplicación de FitZone."""

from decimal import Decimal
from typing import Protocol

from src.domain.models import (
    ClaseProgramada,
    OperacionMembresia,
    PlanDeportivo,
    Socio,
)


class SocioRepositoryPort(Protocol):
    """Puerto de persistencia para el Aggregate Root Socio."""

    def get_by_id(self, actor_id: str) -> Socio | None: ...
    def list_all(self) -> list[Socio]: ...
    def save(self, socio: Socio) -> None: ...


class CatalogoRepositoryPort(Protocol):
    """Puerto de persistencia para los recursos PlanDeportivo."""

    def get_by_id(self, recurso_id: str) -> PlanDeportivo | None: ...
    def list_all(self) -> list[PlanDeportivo]: ...
    def save(self, plan: PlanDeportivo) -> None: ...


class OperacionRepositoryPort(Protocol):
    """Puerto de persistencia para el Aggregate Root OperacionMembresia."""

    def get_by_id(self, operacion_id: str) -> OperacionMembresia | None: ...
    def list_all(self) -> list[OperacionMembresia]: ...
    def save(self, operacion: OperacionMembresia) -> None: ...


class ClaseProgramadaRepositoryPort(Protocol):
    """Puerto de persistencia para el Aggregate Root ClaseProgramada."""

    def get_by_id(self, clase_id: str) -> ClaseProgramada | None: ...
    def list_all(self) -> list[ClaseProgramada]: ...
    def save(self, clase: ClaseProgramada) -> None: ...


class UnitOfWorkPort(Protocol):
    """Puerto para delimitar transacciones ACID (commit / rollback)."""

    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class NotificadorPort(Protocol):
    """Puerto externo para envío de notificaciones (Email/SMS/Push) a socios y administración."""

    def enviar_notificacion(self, destinatario_id: str, asunto: str, mensaje: str) -> bool: ...


class TorniquetePort(Protocol):
    """Puerto externo de hardware para apertura física de torniquete en recepción."""

    def abrir_barrera(self, actor_id: str) -> bool: ...


class PasarelaPagoPort(Protocol):
    """Puerto externo para cobro de operaciones o accesos Drop-in."""

    def cobrar(self, referencia: str, monto: Decimal) -> bool: ...
