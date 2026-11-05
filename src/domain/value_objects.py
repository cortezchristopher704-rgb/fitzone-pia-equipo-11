"""Value Objects inmutables del dominio FitZone."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from src.domain.exceptions import DatosInvalidosError


@dataclass(frozen=True)
class Money:
    """Representa un importe monetario exacto en Decimal (MXN)."""

    amount: Decimal
    currency: str = "MXN"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise DatosInvalidosError("El monto monetario debe ser de tipo Decimal")
        if not self.amount.is_finite() or self.amount < Decimal(0):
            raise DatosInvalidosError("El monto monetario debe ser finito y no negativo")
        if not self.currency or not self.currency.strip():
            raise DatosInvalidosError("La moneda no puede estar vacía")

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise DatosInvalidosError("No se pueden sumar monedas distintas")
        return Money(self.amount + other.amount, self.currency)

    def multiply(self, factor: int | Decimal) -> "Money":
        dec_factor = Decimal(factor) if isinstance(factor, int) else factor
        if dec_factor < Decimal(0):
            raise DatosInvalidosError("El factor de multiplicación no puede ser negativo")
        quantized = (self.amount * dec_factor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return Money(quantized, self.currency)


@dataclass(frozen=True)
class Vigencia:
    """Representa el rango de fechas de validez de una membresía."""

    fecha_inicio: date
    fecha_fin: date

    def __post_init__(self) -> None:
        if self.fecha_fin < self.fecha_inicio:
            raise DatosInvalidosError(
                "La fecha de vencimiento no puede ser anterior a la fecha de inicio"
            )

    def esta_vigente(self, fecha_actual: date) -> bool:
        return self.fecha_inicio <= fecha_actual <= self.fecha_fin

    def dias_para_vencer(self, fecha_actual: date) -> int:
        return (self.fecha_fin - fecha_actual).days


@dataclass(frozen=True)
class LineaOperacion:
    """Representa un renglón dentro de una OperacionMembresia."""

    recurso_id: str
    descripcion: str
    precio_unitario: Money
    cantidad: int
    recurso_habilitado: bool = True
    stock_disponible: int = 999

    def __post_init__(self) -> None:
        if not self.recurso_id or not self.recurso_id.strip():
            raise DatosInvalidosError("El ID del recurso no puede estar vacío")
        if not isinstance(self.cantidad, int) or self.cantidad <= 0:
            raise DatosInvalidosError("La cantidad debe ser un entero mayor a cero")

    @property
    def subtotal(self) -> Money:
        return self.precio_unitario.multiply(self.cantidad)
