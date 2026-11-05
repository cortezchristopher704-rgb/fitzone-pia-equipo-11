"""Entidades, Aggregates, Máquina de Estados y Servicios de Dominio de FitZone."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from src.domain.events import DomainEvent
from src.domain.exceptions import (
    CancelacionTardiaError,
    ClaseSinCupoError,
    DatosInvalidosError,
    LimiteReservasPlanError,
    MembresiaInactivaError,
    PrecondicionOperacionError,
    ReservaDuplicadaError,
    ReservaNoEncontradaError,
    SocioBloqueadoError,
    TransicionEstadoInvalidaError,
)
from src.domain.specifications import (
    BENEFICIO_PREFERENTE_SPEC,
    ELEGIBLE_PARA_RESERVAR_SPEC,
    PUEDE_PROCESARSE_SPEC,
)
from src.domain.value_objects import LineaOperacion, Money, Vigencia


class EstadoOperacion(str, Enum):
    """Estados oficiales del ciclo de vida de una OperacionMembresia."""

    SOLICITADA = "SOLICITADA"
    ACTIVA = "ACTIVA"
    SUSPENDIDA = "SUSPENDIDA"
    VENCIDA = "VENCIDA"
    CANCELADA = "CANCELADA"


class EstadoReserva(str, Enum):
    """Estados de una reserva dentro de una ClaseProgramada."""

    CONFIRMADA = "CONFIRMADA"
    LISTA_ESPERA = "LISTA_ESPERA"
    CANCELADA = "CANCELADA"
    ASISTIDA = "ASISTIDA"
    NO_SHOW = "NO_SHOW"
    PROMOCION_PENDIENTE = "PROMOCION_PENDIENTE"


@dataclass
class PlanDeportivo:
    """Representa un recurso o plan comercializado en el catálogo de FitZone."""

    recurso_id: str
    descripcion: str
    precio_mxn: Money
    capacidad_o_stock: int
    habilitado: bool = True

    def __post_init__(self) -> None:
        if not self.recurso_id or not self.recurso_id.strip():
            raise DatosInvalidosError("El ID del recurso/plan no puede estar vacío")
        if self.capacidad_o_stock < 0:
            raise DatosInvalidosError("La capacidad o stock no puede ser negativa")


@dataclass
class Socio:
    """Aggregate Root que modela a un socio de FitZone, su elegibilidad y disciplina."""

    actor_id: str
    nombre: str
    es_preferente: bool = False
    activo: bool = True
    ciudad: str = "Monterrey"
    tipo_plan: str = "BASICO"
    vigencia: Vigencia | None = None
    no_shows_mes: int = 0
    bloqueado_reservas: bool = False
    dias_bloqueo_restantes: int = 0
    reservas_activas_count: int = 0
    umbral_no_shows: int = 3
    periodo_no_shows: str = ""
    bloqueo_hasta: date | None = None
    eventos: list[DomainEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.actor_id or not self.actor_id.strip():
            raise DatosInvalidosError("El ID del socio no puede estar vacío")
        if not self.nombre or not self.nombre.strip():
            raise DatosInvalidosError("El nombre del socio no puede estar vacío")
        if self.es_preferente and self.tipo_plan == "BASICO":
            self.tipo_plan = "PREMIUM"

    def verificar_acceso_fisico(self, fecha_actual: date | None = None) -> dict[str, object]:
        """CU-04 (US-006, US-007): Valida ingreso en torniquete según vigencia/estado.
        El bloqueo por no-shows NO impide el acceso físico al gimnasio (BRD P6 / US-017).
        """
        fecha_actual = fecha_actual or date.today()
        if not self.activo:
            motivo = "Membresía Inactiva o Suspendida"
            self.eventos.append(
                DomainEvent("AccesoFisicoDenegado", self.actor_id, {"motivo": motivo})
            )
            return {"permitido": False, "motivo": motivo}

        if self.vigencia is None:
            motivo = "Vigencia de membresía no registrada"
            self.eventos.append(
                DomainEvent("AccesoFisicoDenegado", self.actor_id, {"motivo": motivo})
            )
            return {"permitido": False, "motivo": motivo}

        if not self.vigencia.esta_vigente(fecha_actual):
            motivo = "Membresía Vencida"
            self.eventos.append(
                DomainEvent("AccesoFisicoDenegado", self.actor_id, {"motivo": motivo})
            )
            return {"permitido": False, "motivo": motivo}

        self.eventos.append(
            DomainEvent("AccesoFisicoPermitido", self.actor_id, {"motivo": "Membresía Vigente"})
        )
        return {"permitido": True, "motivo": "Acceso Autorizado"}

    def registrar_asistencia(self) -> None:
        """US-011: La asistencia cambia el estado de la reserva, no borra faltas del mes."""
        return None

    def actualizar_bloqueo(self, fecha_actual: date | None = None) -> None:
        hoy = fecha_actual or date.today()
        if self.bloqueo_hasta and hoy < self.bloqueo_hasta:
            self.dias_bloqueo_restantes = (self.bloqueo_hasta - hoy).days
        if self.bloqueo_hasta and hoy >= self.bloqueo_hasta:
            self.bloqueado_reservas = False
            self.dias_bloqueo_restantes = 0
            self.bloqueo_hasta = None

    def registrar_no_show(self, fecha_actual: date | None = None) -> bool:
        """Cuenta faltas por mes calendario y bloquea reservas siete días desde la tercera."""
        hoy = fecha_actual or date.today()
        periodo = hoy.strftime("%Y-%m")
        if self.periodo_no_shows != periodo:
            self.periodo_no_shows = periodo
            self.no_shows_mes = 0
        self.actualizar_bloqueo(hoy)
        self.no_shows_mes += 1
        if self.no_shows_mes == self.umbral_no_shows:
            self.bloqueado_reservas = True
            self.bloqueo_hasta = hoy + timedelta(days=7)
            self.dias_bloqueo_restantes = 7
            self.eventos.append(DomainEvent(
                "SocioBloqueadoPorInasistencia", self.actor_id,
                {"no_shows_mes": self.no_shows_mes, "dias_bloqueo": 7,
                 "bloqueo_hasta": self.bloqueo_hasta.isoformat()},
            ))
            return True
        return False


@dataclass
class OperacionMembresia:
    """Aggregate Root que representa la contratación/gestión de planes deportivos de un Socio.
    Implementa Máquina de Estados estricta, Specification Pattern y Domain Events.
    """

    operacion_id: str
    socio: Socio
    estado: EstadoOperacion = EstadoOperacion.SOLICITADA
    fecha_solicitud: str = "2026-10-01"
    promocion_activa: bool = False
    autorizado: bool = True
    referencia: str = ""
    lineas: list[LineaOperacion] = field(default_factory=list)
    eventos: list[DomainEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.operacion_id or not self.operacion_id.strip():
            raise DatosInvalidosError("El ID de la operación no puede estar vacío")
        if isinstance(self.estado, str):
            self.estado = EstadoOperacion(self.estado)

    def agregar_linea(self, plan: PlanDeportivo, cantidad: int) -> None:
        if self.estado != EstadoOperacion.SOLICITADA:
            raise TransicionEstadoInvalidaError(
                "Solo se pueden agregar planes a una operación en estado SOLICITADA"
            )
        linea = LineaOperacion(
            recurso_id=plan.recurso_id,
            descripcion=plan.descripcion,
            precio_unitario=plan.precio_mxn,
            cantidad=cantidad,
            recurso_habilitado=plan.habilitado,
            stock_disponible=plan.capacidad_o_stock,
        )
        self.lineas.append(linea)

    @property
    def total_unidades(self) -> int:
        return sum(linea.cantidad for linea in self.lineas)

    @property
    def total_bruto(self) -> Money:
        total = Money(Decimal("0.00"), "MXN")
        for linea in self.lineas:
            total = total + linea.subtotal
        return total

    def puede_procesarse(self) -> bool:
        """Evalúa la Specification compuesta PUEDE_PROCESARSE_SPEC."""
        return PUEDE_PROCESARSE_SPEC.is_satisfied_by(self)

    def tiene_beneficio_preferente(self) -> bool:
        """Evalúa la Specification compuesta BENEFICIO_PREFERENTE_SPEC (VIP & total>=1500 & ~promo)."""
        return BENEFICIO_PREFERENTE_SPEC.is_satisfied_by(self)

    @property
    def tasa_descuento(self) -> Decimal:
        """Si cumple BENEFICIO_PREFERENTE_SPEC otorga 10% (0.10), de lo contrario 0%."""
        if self.tiene_beneficio_preferente():
            return Decimal("0.10")
        return Decimal("0.00")

    @property
    def monto_descuento(self) -> Money:
        return self.total_bruto.multiply(self.tasa_descuento)

    @property
    def total_neto(self) -> Money:
        return Money(self.total_bruto.amount - self.monto_descuento.amount, "MXN")

    # ==========================================================================
    # MÁQUINA DE ESTADOS: SOLICITADA -> ACTIVA -> SUSPENDIDA -> VENCIDA | CANCELADA
    # ==========================================================================

    def aprobar(self) -> None:
        """Transición SOLICITADA -> ACTIVA tras validar todas las Specifications."""
        if self.estado != EstadoOperacion.SOLICITADA:
            raise TransicionEstadoInvalidaError(
                f"No se puede aprobar/activar una operación desde el estado {self.estado.value}"
            )
        if not self.puede_procesarse():
            motivos = []
            if not self.socio.activo:
                motivos.append("socio inactivo")
            if not self.lineas:
                motivos.append("detalle vacío")
            if any(not l.recurso_habilitado for l in self.lineas):
                motivos.append("recurso deshabilitado")
            if any(l.cantidad > l.stock_disponible for l in self.lineas):
                motivos.append("stock insuficiente")
            if not self.autorizado:
                motivos.append("sin autorización")
            raise PrecondicionOperacionError(
                f"Operación {self.operacion_id} rechazada por precondiciones: {', '.join(motivos)}"
            )

        self.estado = EstadoOperacion.ACTIVA
        self.eventos.append(
            DomainEvent(
                "OperacionActivada",
                self.operacion_id,
                {
                    "actor_id": self.socio.actor_id,
                    "total_bruto": str(self.total_bruto.amount),
                    "descuento": str(self.monto_descuento.amount),
                    "total_neto": str(self.total_neto.amount),
                },
            )
        )

    def suspender(self, motivo: str = "Suspensión administrativa") -> None:
        """Transición ACTIVA -> SUSPENDIDA."""
        if self.estado != EstadoOperacion.ACTIVA:
            raise TransicionEstadoInvalidaError(
                f"Solo se puede suspender desde ACTIVA (estado actual: {self.estado.value})"
            )
        self.estado = EstadoOperacion.SUSPENDIDA
        self.eventos.append(
            DomainEvent("OperacionSuspendida", self.operacion_id, {"motivo": motivo})
        )

    def vencer(self) -> None:
        """Transición ACTIVA o SUSPENDIDA -> VENCIDA."""
        if self.estado not in (EstadoOperacion.ACTIVA, EstadoOperacion.SUSPENDIDA):
            raise TransicionEstadoInvalidaError(
                f"No se puede vencer directamente desde {self.estado.value}; requiere pasar por ACTIVA/SUSPENDIDA"
            )
        self.estado = EstadoOperacion.VENCIDA
        self.eventos.append(
            DomainEvent(
                "MembresiaVencida",
                self.operacion_id,
                {"actor_id": self.socio.actor_id},
            )
        )

    def cancelar(self, motivo: str = "Cancelada por solicitud") -> None:
        """Transición alternativa SOLICITADA -> CANCELADA."""
        if self.estado != EstadoOperacion.SOLICITADA:
            raise TransicionEstadoInvalidaError(
                f"Solo se puede cancelar una operación en estado SOLICITADA (actual: {self.estado.value})"
            )
        self.estado = EstadoOperacion.CANCELADA
        self.eventos.append(
            DomainEvent("OperacionCancelada", self.operacion_id, {"motivo": motivo})
        )

    def completarciclo(self) -> None:
        """Ejecuta el ciclo completo válido SOLICITADA -> ACTIVA -> SUSPENDIDA -> VENCIDA."""
        self.aprobar()
        self.suspender("Fin de periodo activo")
        self.vencer()

    def ejecutar_accion_transicion(self, accion: str) -> str:
        """Ejecuta una acción de transición del paquete de pruebas transiciones_prueba.csv."""
        accion_norm = accion.strip().lower()
        if accion_norm == "aprobar":
            self.aprobar()
            return f"OK:{self.estado.value}"
        if accion_norm == "cancelar":
            self.cancelar()
            return f"OK:{self.estado.value}"
        if accion_norm == "completar":
            self.completarciclo()
            return f"OK:{self.estado.value}"
        if accion_norm == "repetir_aprobacion":
            self.aprobar()
            self.aprobar()  # Lanzará TransicionEstadoInvalidaError en la segunda llamada
            return f"OK:{self.estado.value}"
        if accion_norm == "saltar_estado":
            self.vencer()  # Intentar pasar de SOLICITADA directo a VENCIDA lanza error
            return f"OK:{self.estado.value}"
        raise DatosInvalidosError(f"Acción de transición desconocida: {accion}")


@dataclass
class Reserva:
    """Entidad interna gestionada exclusivamente a través del Aggregate ClaseProgramada."""

    socio_id: str
    clase_id: str
    estado: EstadoReserva = EstadoReserva.CONFIRMADA
    es_drop_in: bool = False
    tarifa_drop_in: Money = field(default_factory=lambda: Money(Decimal("0.00")))


@dataclass
class ClaseProgramada:
    """Aggregate Root que protege el aforo, las reservas y la ListaDeEspera FIFO de una sesión."""

    clase_id: str
    disciplina: str
    horario: str
    capacidad_maxima: int
    instructor_id: str = "INST-01"
    incluida_en_plan_basico: bool = True
    planes_incluidos: set[str] | None = None
    capacidad_lista_espera: int = 15
    cut_off_horas_socio: float = 3.0
    cut_off_horas_instructor: float = 2.0
    cancelada: bool = False
    reservas: dict[str, Reserva] = field(default_factory=dict)
    lista_espera: list[str] = field(default_factory=list)
    promocion_pendiente_socio_id: str | None = None
    promocion_expira_en: datetime | None = None
    ventana_confirmacion_minutos: int = 30
    eventos: list[DomainEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.clase_id or not self.clase_id.strip():
            raise DatosInvalidosError("El ID de la clase no puede estar vacío")
        if self.capacidad_maxima <= 0:
            raise DatosInvalidosError("La capacidad máxima de la clase debe ser mayor a cero")
        if self.planes_incluidos is not None:
            self.planes_incluidos = {plan.strip().upper() for plan in self.planes_incluidos if plan.strip()}

    @property
    def reservas_confirmadas_ids(self) -> list[str]:
        return [
            r.socio_id
            for r in self.reservas.values()
            if r.estado in (EstadoReserva.CONFIRMADA, EstadoReserva.ASISTIDA, EstadoReserva.PROMOCION_PENDIENTE)
        ]

    @property
    def cupos_disponibles(self) -> int:
        return max(0, self.capacidad_maxima - len(self.reservas_confirmadas_ids))

    @property
    def porcentaje_ocupacion(self) -> float:
        return round((len(self.reservas_confirmadas_ids) / self.capacidad_maxima) * 100.0, 2)

    def actualizar_capacidad(self, nueva_capacidad: int) -> None:
        """US-012: permite al administrador ajustar el aforo sin invalidar reservas existentes."""
        if nueva_capacidad <= 0:
            raise DatosInvalidosError("La capacidad máxima debe ser mayor a cero")
        ocupacion = len(self.reservas_confirmadas_ids)
        if nueva_capacidad < ocupacion:
            raise DatosInvalidosError(
                f"La nueva capacidad ({nueva_capacidad}) no puede ser menor a las reservas activas ({ocupacion})"
            )
        anterior = self.capacidad_maxima
        self.capacidad_maxima = nueva_capacidad
        self.eventos.append(DomainEvent(
            "CapacidadClaseActualizada", self.clase_id,
            {"capacidad_anterior": anterior, "capacidad_nueva": nueva_capacidad}
        ))

    def reservar(self, socio: Socio, es_drop_in: bool = False, monto_drop_in: Decimal = Decimal("0.00")) -> str:
        """CU-01 / CU-02 (US-001, US-003, US-013): Procesa solicitud de reserva protegiendo invariantes."""
        self.expirar_promocion()
        if self.cancelada:
            raise TransicionEstadoInvalidaError("No se puede reservar en una clase cancelada")

        if not socio.activo:
            raise MembresiaInactivaError(f"El socio {socio.actor_id} no tiene una membresía activa")

        socio.actualizar_bloqueo()
        if socio.bloqueado_reservas:
            raise SocioBloqueadoError(
                f"El socio {socio.actor_id} tiene un bloqueo disciplinario activo por no-shows"
            )

        if socio.vigencia is None:
            raise MembresiaInactivaError(
                f"El socio {socio.actor_id} no tiene vigencia de membresía registrada"
            )
        if not socio.vigencia.esta_vigente(date.today()):
            raise MembresiaInactivaError(f"La membresía del socio {socio.actor_id} está vencida")

        if not es_drop_in:
            if self.planes_incluidos is not None and socio.tipo_plan.upper() not in self.planes_incluidos:
                raise MembresiaInactivaError(
                    f"La clase no está incluida en el plan {socio.tipo_plan}; use Drop-in si está disponible"
                )
            if self.planes_incluidos is None and not self.incluida_en_plan_basico and socio.tipo_plan.upper() == "BASICO":
                raise MembresiaInactivaError("La clase no está incluida en el Plan Básico; use Drop-in si está disponible")

        # El límite de anticipación se aplica cuando horario contiene fecha y hora ISO.
        try:
            inicio = datetime.fromisoformat(self.horario)
        except ValueError:
            inicio = None  # Horarios heredados HH:MM no contienen fecha suficiente para validar.
        if inicio is not None and inicio.date() > date.today() + timedelta(days=7):
            raise DatosInvalidosError("Las reservas solo pueden realizarse con máximo 7 días de anticipación")

        if not es_drop_in and not ELEGIBLE_PARA_RESERVAR_SPEC.is_satisfied_by(socio):
            raise LimiteReservasPlanError(
                f"El socio {socio.actor_id} alcanzó el límite de 2 reservas simultáneas de su Plan Básico"
            )

        if (
            socio.actor_id in self.reservas
            and self.reservas[socio.actor_id].estado in (EstadoReserva.CONFIRMADA, EstadoReserva.ASISTIDA, EstadoReserva.PROMOCION_PENDIENTE)
        ) or socio.actor_id in self.lista_espera:
            raise ReservaDuplicadaError(
                f"El socio {socio.actor_id} ya cuenta con registro activo en la clase {self.clase_id}"
            )

        if self.cupos_disponibles > 0:
            self.reservas[socio.actor_id] = Reserva(
                socio_id=socio.actor_id,
                clase_id=self.clase_id,
                estado=EstadoReserva.CONFIRMADA,
                es_drop_in=es_drop_in,
                tarifa_drop_in=Money(monto_drop_in),
            )
            socio.reservas_activas_count += 1
            self.eventos.append(
                DomainEvent(
                    "ReservaConfirmada",
                    self.clase_id,
                    {
                        "socio_id": socio.actor_id,
                        "cupos_disponibles": self.cupos_disponibles,
                        "es_drop_in": es_drop_in,
                    },
                )
            )
            return EstadoReserva.CONFIRMADA.value

        if len(self.lista_espera) < self.capacidad_lista_espera:
            self.lista_espera.append(socio.actor_id)
            posicion = len(self.lista_espera)
            self.eventos.append(
                DomainEvent(
                    "SocioEnListaDeEspera",
                    self.clase_id,
                    {"socio_id": socio.actor_id, "posicion_fifo": posicion},
                )
            )
            return EstadoReserva.LISTA_ESPERA.value

        raise ClaseSinCupoError(
            f"La clase {self.clase_id} y su lista de espera han alcanzado su capacidad máxima"
        )

    def cancelar_reserva(
        self, socio: Socio, horas_anticipacion: float
    ) -> dict[str, str | None]:
        """CU-03 (US-004, US-005): Libera el lugar y promueve en orden FIFO si aplica.
        Cut-off oficial de U2/U3: >= 3 horas sin penalización. Menos de 3 horas aplica sanción.
        """
        self.expirar_promocion()
        if (
            socio.actor_id not in self.reservas
            or self.reservas[socio.actor_id].estado != EstadoReserva.CONFIRMADA
        ):
            raise ReservaNoEncontradaError(
                f"El socio {socio.actor_id} no tiene una reserva confirmada en la clase {self.clase_id}"
            )

        # Liberar lugar y promover al primero de la lista de espera (FIFO)
        self.reservas[socio.actor_id].estado = EstadoReserva.CANCELADA
        socio.reservas_activas_count = max(0, socio.reservas_activas_count - 1)

        socio_promovido: str | None = None
        if self.lista_espera:
            socio_promovido = self.lista_espera.pop(0)
            self.reservas[socio_promovido] = Reserva(
                socio_id=socio_promovido, clase_id=self.clase_id,
                estado=EstadoReserva.PROMOCION_PENDIENTE,
            )
            self.promocion_pendiente_socio_id = socio_promovido
            self.promocion_expira_en = datetime.now() + timedelta(minutes=self.ventana_confirmacion_minutos)

        self.eventos.append(
            DomainEvent(
                "LugarLiberadoEnClase",
                self.clase_id,
                {
                    "socio_saliente": socio.actor_id,
                    "socio_promovido_fifo": socio_promovido,
                    "ventana_confirmacion_min": self.ventana_confirmacion_minutos,
                },
            )
        )

        if horas_anticipacion < self.cut_off_horas_socio:
            socio.registrar_no_show()
            raise CancelacionTardiaError(
                f"Cancelación con {horas_anticipacion}h (< {self.cut_off_horas_socio}h cut-off); se registra penalización"
            )

        return {
            "estado": EstadoReserva.CANCELADA.value,
            "socio_promovido": socio_promovido,
        }

    def confirmar_promocion(self, socio_id: str, ahora: datetime | None = None) -> None:
        ahora = ahora or datetime.now()
        if socio_id != self.promocion_pendiente_socio_id:
            raise ReservaNoEncontradaError("El socio no tiene una promoción pendiente en esta clase")
        if self.promocion_expira_en is None or ahora >= self.promocion_expira_en:
            self.expirar_promocion(ahora)
            raise ReservaNoEncontradaError("La ventana de confirmación de 30 minutos ha expirado")
        reserva = self.reservas[socio_id]
        reserva.estado = EstadoReserva.CONFIRMADA
        self.promocion_pendiente_socio_id = None
        self.promocion_expira_en = None
        self.eventos.append(DomainEvent("PromocionListaEsperaConfirmada", self.clase_id, {"socio_id": socio_id}))

    def expirar_promocion(self, ahora: datetime | None = None) -> str | None:
        ahora = ahora or datetime.now()
        if not self.promocion_pendiente_socio_id or not self.promocion_expira_en or ahora < self.promocion_expira_en:
            return None
        expirado = self.promocion_pendiente_socio_id
        self.reservas[expirado].estado = EstadoReserva.CANCELADA
        self.promocion_pendiente_socio_id = None
        self.promocion_expira_en = None
        siguiente = self.lista_espera.pop(0) if self.lista_espera else None
        if siguiente:
            self.reservas[siguiente] = Reserva(socio_id=siguiente, clase_id=self.clase_id, estado=EstadoReserva.PROMOCION_PENDIENTE)
            self.promocion_pendiente_socio_id = siguiente
            self.promocion_expira_en = ahora + timedelta(minutes=self.ventana_confirmacion_minutos)
        self.eventos.append(DomainEvent("PromocionListaEsperaExpirada", self.clase_id, {"socio_expirado": expirado, "siguiente_socio": siguiente}))
        return siguiente

    def registrar_asistencia(self, socio: Socio) -> None:
        reserva = self.reservas.get(socio.actor_id)
        if reserva is None or reserva.estado != EstadoReserva.CONFIRMADA:
            raise ReservaNoEncontradaError("No existe reserva confirmada para registrar asistencia")
        reserva.estado = EstadoReserva.ASISTIDA
        socio.reservas_activas_count = max(0, socio.reservas_activas_count - 1)
        socio.registrar_asistencia()
        self.eventos.append(DomainEvent("AsistenciaRegistrada", self.clase_id, {"socio_id": socio.actor_id}))

    def registrar_no_show(self, socio: Socio, fecha_actual: date | None = None) -> bool:
        reserva = self.reservas.get(socio.actor_id)
        if reserva is None or reserva.estado != EstadoReserva.CONFIRMADA:
            raise ReservaNoEncontradaError("No existe reserva confirmada para registrar no-show")
        reserva.estado = EstadoReserva.NO_SHOW
        socio.reservas_activas_count = max(0, socio.reservas_activas_count - 1)
        bloqueado = socio.registrar_no_show(fecha_actual)
        self.eventos.append(DomainEvent("NoShowRegistrado", self.clase_id, {"socio_id": socio.actor_id, "bloqueado": bloqueado}))
        return bloqueado

    def cancelar_por_vencimiento_membresia(self, socio: Socio) -> str | None:
        """US-018: Cuando vence la membresía de un socio, se cancelan sus reservas activas sin multa."""
        if (
            socio.actor_id in self.reservas
            and self.reservas[socio.actor_id].estado == EstadoReserva.CONFIRMADA
        ):
            res = self.cancelar_reserva(socio, horas_anticipacion=999.0)
            return res["socio_promovido"]
        return None

    def actualizar_planes_incluidos(self, planes: set[str]) -> None:
        """US-013: configura explícitamente los tipos de plan habilitados para la clase."""
        normalizados = {plan.strip().upper() for plan in planes if plan and plan.strip()}
        if len(normalizados) != len(planes):
            raise DatosInvalidosError("Los tipos de plan no pueden contener valores vacíos")
        anterior = sorted(self.planes_incluidos) if self.planes_incluidos is not None else None
        self.planes_incluidos = normalizados
        self.eventos.append(DomainEvent(
            "PlanesIncluidosActualizados", self.clase_id,
            {"planes_anteriores": anterior, "planes_nuevos": sorted(normalizados)},
        ))

    def reasignar_instructor(self, nuevo_instructor_id: str) -> None:
        """US-020 (N6): Asigna un instructor de respaldo para mantener la continuidad de la sesión."""
        if not nuevo_instructor_id or not nuevo_instructor_id.strip():
            raise DatosInvalidosError("El ID del instructor de respaldo no puede estar vacío")
        anterior = self.instructor_id
        self.instructor_id = nuevo_instructor_id
        self.eventos.append(
            DomainEvent(
                "InstructorReasignado",
                self.clase_id,
                {"instructor_anterior": anterior, "instructor_nuevo": nuevo_instructor_id},
            )
        )

    def cancelar_por_instructor(self, horas_anticipacion: float, motivo: str = "Fuerza mayor") -> None:
        """US-010 (N6): El instructor cancela con al menos 2 horas de anticipación."""
        if horas_anticipacion < self.cut_off_horas_instructor:
            raise CancelacionTardiaError(
                f"El instructor debe notificar con al menos {self.cut_off_horas_instructor} horas de anticipación"
            )
        self.cancelada = True
        inscritos = list(self.reservas_confirmadas_ids)
        for s_id in inscritos:
            self.reservas[s_id].estado = EstadoReserva.CANCELADA
        self.eventos.append(
            DomainEvent(
                "ClaseCanceladaPorInstructor",
                self.clase_id,
                {"motivo": motivo, "socios_afectados": inscritos, "accion": "Reagendar sin costo"},
            )
        )


class ServicioDeInscripcionExtraordinaria:
    """Domain Service (US-019) que orquesta el acceso 'Drop-in' a una clase fuera del plan del socio."""

    def __init__(self, tarifa_unica_mxn: Decimal = Decimal("180.00")) -> None:
        self.tarifa_unica = Money(tarifa_unica_mxn, "MXN")

    def inscribir_drop_in(
        self, socio: Socio, clase: ClaseProgramada, pago_confirmado: bool
    ) -> str:
        if not pago_confirmado:
            raise PrecondicionOperacionError(
                "El acceso extraordinario Drop-in requiere pago único confirmado"
            )
        return clase.reservar(
            socio=socio, es_drop_in=True, monto_drop_in=self.tarifa_unica.amount
        )
