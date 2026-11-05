"""Excepciones de Dominio para el sistema FitZone (Caso 11 PIA)."""


class FitZoneDomainError(Exception):
    """Clase base para todas las excepciones de negocio de FitZone."""


class DatosInvalidosError(FitZoneDomainError):
    """Se lanza cuando un Value Object o Entidad recibe datos inválidos o fuera de rango."""


class TransicionEstadoInvalidaError(FitZoneDomainError):
    """Se lanza cuando se intenta una transición no permitida en la máquina de estados."""


class PrecondicionOperacionError(FitZoneDomainError):
    """Se lanza cuando una operación de membresía no cumple las Specifications para procesarse."""


class RecursoNoDisponibleError(FitZoneDomainError):
    """Se lanza cuando un plan deportivo o clase está deshabilitado o sin stock."""


class MembresiaInactivaError(FitZoneDomainError):
    """Se lanza cuando un socio con membresía vencida, suspendida o inactiva intenta operar."""


class SocioBloqueadoError(FitZoneDomainError):
    """Se lanza cuando un socio sancionado por 3 no-shows intenta reservar una clase."""


class LimiteReservasPlanError(FitZoneDomainError):
    """Se lanza cuando un socio con Plan Básico excede el límite de 2 reservas simultáneas."""


class ReservaDuplicadaError(FitZoneDomainError):
    """Se lanza cuando un socio intenta reservar dos veces la misma clase."""


class ReservaNoEncontradaError(FitZoneDomainError):
    """Se lanza cuando se intenta cancelar o calificar una reserva inexistente."""


class CancelacionTardiaError(FitZoneDomainError):
    """Se lanza cuando se intenta cancelar fuera del cut-off time (3h socio / 2h instructor)."""


class ClaseSinCupoError(FitZoneDomainError):
    """Se lanza cuando una clase y su lista de espera han alcanzado su límite."""
