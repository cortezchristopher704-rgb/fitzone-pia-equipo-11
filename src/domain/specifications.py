"""Implementación del Patrón Specification con composición booleana (&, |, ~) para FitZone."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class Specification(ABC, Generic[T]):
    """Clase base para Specifications combinables mediante AND (&), OR (|) y NOT (~)."""

    @abstractmethod
    def is_satisfied_by(self, candidate: T) -> bool:
        """Evalúa si el candidato cumple la condición de negocio."""

    def __and__(self, other: "Specification[T]") -> "AndSpecification[T]":
        return AndSpecification(self, other)

    def __or__(self, other: "Specification[T]") -> "OrSpecification[T]":
        return OrSpecification(self, other)

    def __invert__(self) -> "NotSpecification[T]":
        return NotSpecification(self)


class AndSpecification(Specification[T]):
    def __init__(self, left: Specification[T], right: Specification[T]) -> None:
        self.left = left
        self.right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self.left.is_satisfied_by(candidate) and self.right.is_satisfied_by(candidate)


class OrSpecification(Specification[T]):
    def __init__(self, left: Specification[T], right: Specification[T]) -> None:
        self.left = left
        self.right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self.left.is_satisfied_by(candidate) or self.right.is_satisfied_by(candidate)


class NotSpecification(Specification[T]):
    def __init__(self, spec: Specification[T]) -> None:
        self.spec = spec

    def is_satisfied_by(self, candidate: T) -> bool:
        return not self.spec.is_satisfied_by(candidate)


# ==============================================================================
# SPECIFICATIONS DE OPERACIONES DE MEMBRESÍA Y PLANES DEPORTIVOS (11_FitZone)
# ==============================================================================


class SocioActivoSpec(Specification[Any]):
    """Verifica que el socio (actor) de la operación o entidad esté activo."""

    def is_satisfied_by(self, candidate: Any) -> bool:
        if hasattr(candidate, "socio"):
            return bool(candidate.socio.activo)
        return bool(getattr(candidate, "activo", False))


class DetalleNoVacioSpec(Specification[Any]):
    """Verifica que la operación contenga al menos un renglón de plan deportivo."""

    def is_satisfied_by(self, candidate: Any) -> bool:
        return len(getattr(candidate, "lineas", [])) > 0


class RecursosHabilitadosYConStockSpec(Specification[Any]):
    """Verifica que cada recurso solicitado esté habilitado y tenga capacidad/stock suficiente."""

    def is_satisfied_by(self, candidate: Any) -> bool:
        lineas = getattr(candidate, "lineas", [])
        if not lineas:
            return False
        return all(
            linea.recurso_habilitado and linea.cantidad <= linea.stock_disponible
            for linea in lineas
        )


class OperacionAutorizadaSpec(Specification[Any]):
    """Verifica que la operación cuente con autorización administrativa/recepción."""

    def is_satisfied_by(self, candidate: Any) -> bool:
        return bool(getattr(candidate, "autorizado", False))


class SocioPreferenteSpec(Specification[Any]):
    """Verifica que el socio sea Preferente / VIP."""

    def is_satisfied_by(self, candidate: Any) -> bool:
        if hasattr(candidate, "socio"):
            return bool(candidate.socio.es_preferente)
        return bool(getattr(candidate, "es_preferente", False))


class MontoMinimoSpec(Specification[Any]):
    """Verifica que el importe total de la operación sea mayor o igual al umbral en MXN."""

    def __init__(self, umbral: Decimal = Decimal("1500.00")) -> None:
        self.umbral = umbral

    def is_satisfied_by(self, candidate: Any) -> bool:
        total_money = getattr(candidate, "total_bruto", None)
        if total_money is None:
            return False
        return bool(total_money.amount >= self.umbral)


class PromocionActivaSpec(Specification[Any]):
    """Verifica si la operación tiene una promoción activa aplicada."""

    def is_satisfied_by(self, candidate: Any) -> bool:
        return bool(getattr(candidate, "promocion_activa", False))


# ==============================================================================
# SPECIFICATIONS DE RESERVACIÓN DE CLASES Y ELEGIBILIDAD DE SOCIO (U2/U3 BRD)
# ==============================================================================


class SocioSinBloqueoSpec(Specification[Any]):
    """Verifica que el socio no esté sancionado/bloqueado por acumulación de 3 no-shows."""

    def is_satisfied_by(self, candidate: Any) -> bool:
        return not bool(getattr(candidate, "bloqueado_reservas", False))


class CupoReservasPorPlanSpec(Specification[Any]):
    """Verifica límite de reservas simultáneas según el plan: Básico <= 2, Premium sin límite."""

    def is_satisfied_by(self, candidate: Any) -> bool:
        tipo_plan = str(getattr(candidate, "tipo_plan", "BASICO")).upper()
        reservas_activas = int(getattr(candidate, "reservas_activas_count", 0))
        if tipo_plan in ("PREMIUM", "PREFERENTE", "ANUAL", "VIP"):
            return True
        return reservas_activas < 2


# Composición declarativa oficial para el dominio de FitZone
PUEDE_PROCESARSE_SPEC = (
    SocioActivoSpec()
    & DetalleNoVacioSpec()
    & RecursosHabilitadosYConStockSpec()
    & OperacionAutorizadaSpec()
)

BENEFICIO_PREFERENTE_SPEC = (
    SocioPreferenteSpec()
    & MontoMinimoSpec(Decimal("1500.00"))
    & ~PromocionActivaSpec()
)

ELEGIBLE_PARA_RESERVAR_SPEC = (
    SocioActivoSpec() & SocioSinBloqueoSpec() & CupoReservasPorPlanSpec()
)
