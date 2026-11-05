"""Eventos de Dominio (Domain Events) inmutables de FitZone."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    """Representa un hecho histórico inmutable que ocurrió en el dominio de FitZone."""

    nombre: str
    entidad_id: str
    detalles: dict[str, Any] = field(default_factory=dict)
    ocurrido_en: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
