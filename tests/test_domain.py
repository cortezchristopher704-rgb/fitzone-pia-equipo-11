"""Pruebas Unitarias de Dominio Puro, Value Objects, Specifications, Máquina de Estados y Aggregates."""

from datetime import date
from decimal import Decimal

import pytest

from src.domain import (
    BENEFICIO_PREFERENTE_SPEC,
    PUEDE_PROCESARSE_SPEC,
    CancelacionTardiaError,
    ClaseProgramada,
    ClaseSinCupoError,
    DatosInvalidosError,
    EstadoOperacion,
    EstadoReserva,
    LimiteReservasPlanError,
    LineaOperacion,
    MembresiaInactivaError,
    Money,
    MontoMinimoSpec,
    OperacionMembresia,
    PlanDeportivo,
    PrecondicionOperacionError,
    PromocionActivaSpec,
    RecursosHabilitadosYConStockSpec,
    ReservaDuplicadaError,
    ReservaNoEncontradaError,
    ServicioDeInscripcionExtraordinaria,
    Socio,
    SocioActivoSpec,
    SocioBloqueadoError,
    SocioPreferenteSpec,
    TransicionEstadoInvalidaError,
    Vigencia,
)


def socio_vigente(actor_id: str, nombre: str, **kwargs) -> Socio:
    """Socio de prueba con vigencia contractual explícita."""
    kwargs.setdefault("vigencia", Vigencia(date.today(), date.today().replace(year=date.today().year + 1)))
    return Socio(actor_id, nombre, **kwargs)


def test_money_value_object_validations_and_arithmetic():
    m1 = Money(Decimal("474.00"), "MXN")
    m2 = Money(Decimal("526.00"), "MXN")
    assert (m1 + m2).amount == Decimal("1000.00")
    assert m1.multiply(3).amount == Decimal("1422.00")

    with pytest.raises(DatosInvalidosError):
        Money(474.00, "MXN")  # type: ignore[arg-type]
    with pytest.raises(DatosInvalidosError):
        Money(Decimal("-1.00"), "MXN")
    with pytest.raises(DatosInvalidosError):
        Money(Decimal("10.00"), "")
    with pytest.raises(DatosInvalidosError):
        _ = m1 + Money(Decimal("10.00"), "USD")
    with pytest.raises(DatosInvalidosError):
        m1.multiply(-2)


def test_vigencia_and_linea_operacion_validations():
    vig = Vigencia(date(2026, 10, 1), date(2026, 10, 31))
    assert vig.esta_vigente(date(2026, 10, 15)) is True
    assert vig.esta_vigente(date(2026, 11, 1)) is False
    assert vig.dias_para_vencer(date(2026, 10, 21)) == 10

    with pytest.raises(DatosInvalidosError):
        Vigencia(date(2026, 10, 31), date(2026, 10, 1))

    with pytest.raises(DatosInvalidosError):
        LineaOperacion("", "Plan", Money(Decimal(100)), 1)
    with pytest.raises(DatosInvalidosError):
        LineaOperacion("FIT-P001", "Plan", Money(Decimal(100)), 0)


def test_entity_basic_validations():
    with pytest.raises(DatosInvalidosError):
        PlanDeportivo("", "Mensual", Money(Decimal(500)), 10)
    with pytest.raises(DatosInvalidosError):
        PlanDeportivo("FIT-P001", "Mensual", Money(Decimal(500)), -1)
    with pytest.raises(DatosInvalidosError):
        Socio("", "Nombre")
    with pytest.raises(DatosInvalidosError):
        Socio("FIT-C001", "   ")
    with pytest.raises(DatosInvalidosError):
        OperacionMembresia("", Socio("FIT-C001", "Socio 01"))
    with pytest.raises(DatosInvalidosError):
        ClaseProgramada("", "CrossFit", "08:00", 10)
    with pytest.raises(DatosInvalidosError):
        ClaseProgramada("CLASE-01", "CrossFit", "08:00", 0)


def test_specifications_boolean_composition_and_or_not():
    socio_vip = Socio("FIT-C005", "Socio VIP", es_preferente=True, activo=True)
    plan_ok = PlanDeportivo("FIT-P016", "Anual 16", Money(Decimal("1539.00")), 13, True)

    op = OperacionMembresia("FIT-O900", socio_vip, promocion_activa=False, autorizado=True)
    op.agregar_linea(plan_ok, 1)

    assert PUEDE_PROCESARSE_SPEC.is_satisfied_by(op) is True
    assert BENEFICIO_PREFERENTE_SPEC.is_satisfied_by(op) is True
    assert op.tasa_descuento == Decimal("0.10")
    assert op.monto_descuento.amount == Decimal("153.90")
    assert op.total_neto.amount == Decimal("1385.10")

    # Operador OR (|) explícito
    spec_or = SocioPreferenteSpec() | PromocionActivaSpec()
    assert spec_or.is_satisfied_by(op) is True
    assert SocioActivoSpec().is_satisfied_by(socio_vip) is True
    assert SocioPreferenteSpec().is_satisfied_by(socio_vip) is True
    assert MontoMinimoSpec().is_satisfied_by(object()) is False
    assert RecursosHabilitadosYConStockSpec().is_satisfied_by(object()) is False


def test_operacion_state_machine_and_domain_events():
    socio = Socio("FIT-C001", "Socio 01", es_preferente=False, activo=True)
    plan = PlanDeportivo("FIT-P001", "Mensual 01", Money(Decimal("474.00")), 13, True)
    op = OperacionMembresia("FIT-O001", socio, estado="SOLICITADA")
    op.agregar_linea(plan, 2)

    # Ciclo completo SOLICITADA -> ACTIVA -> SUSPENDIDA -> VENCIDA
    assert op.ejecutar_accion_transicion("completar") == "OK:VENCIDA"
    assert op.estado == EstadoOperacion.VENCIDA
    assert [e.nombre for e in op.eventos] == [
        "OperacionActivada",
        "OperacionSuspendida",
        "MembresiaVencida",
    ]

    # No se pueden agregar líneas fuera de SOLICITADA
    with pytest.raises(TransicionEstadoInvalidaError):
        op.agregar_linea(plan, 1)

    with pytest.raises(TransicionEstadoInvalidaError):
        op.suspender()

    with pytest.raises(TransicionEstadoInvalidaError):
        op.cancelar()

    with pytest.raises(DatosInvalidosError):
        op.ejecutar_accion_transicion("accion_inexistente")


def test_operacion_rejection_reasons():
    socio_inactivo = Socio("FIT-C007", "Socio 07", activo=False)
    plan_deshab = PlanDeportivo("FIT-P011", "Semestral 11", Money(Decimal("1184.00")), 2, False)
    op = OperacionMembresia("FIT-O005", socio_inactivo, autorizado=False)
    op.agregar_linea(plan_deshab, 5)  # Excede stock y está deshabilitado

    with pytest.raises(PrecondicionOperacionError) as exc_info:
        op.aprobar()
    msg = str(exc_info.value)
    assert "socio inactivo" in msg
    assert "recurso deshabilitado" in msg
    assert "stock insuficiente" in msg
    assert "sin autorización" in msg


def test_clase_programada_reserva_fifo_cutoff_and_drop_in():
    s1 = socio_vigente("FIT-C001", "Socio 1", activo=True, tipo_plan="BASICO")
    s2 = socio_vigente("FIT-C002", "Socio 2", activo=True, tipo_plan="BASICO")
    s3 = socio_vigente("FIT-C003", "Socio 3", activo=True, tipo_plan="PREMIUM")
    clase = ClaseProgramada("CLASE-SPIN", "Spinning", "08:00", capacidad_maxima=1, capacidad_lista_espera=1)

    # s1 ocupa el único cupo
    assert clase.reservar(s1) == EstadoReserva.CONFIRMADA.value
    assert clase.cupos_disponibles == 0
    assert clase.porcentaje_ocupacion == 100.0

    # Reserva duplicada rechazada
    with pytest.raises(ReservaDuplicadaError):
        clase.reservar(s1)

    # s2 entra a lista de espera FIFO
    assert clase.reservar(s2) == EstadoReserva.LISTA_ESPERA.value
    assert clase.lista_espera == ["FIT-C002"]

    # s3 intenta entrar pero tanto clase como lista de espera están llenas
    with pytest.raises(ClaseSinCupoError):
        clase.reservar(s3)

    # s1 cancela con 4h (>= 3h cut-off): sin penalización y s2 es promovido automáticamente (FIFO)
    res_canc = clase.cancelar_reserva(s1, horas_anticipacion=4.0)
    assert res_canc["socio_promovido"] == "FIT-C002"
    assert "FIT-C002" in clase.reservas_confirmadas_ids

    # El socio promovido debe confirmar antes de que su reserva sea cancelable.
    clase.confirmar_promocion("FIT-C002")
    # s2 cancela tardíamente con 1h (< 3h cut-off): lanza CancelacionTardiaError y suma no-show
    with pytest.raises(CancelacionTardiaError):
        clase.cancelar_reserva(s2, horas_anticipacion=1.0)
    assert s2.no_shows_mes == 1

    # Cancelar reserva inexistente
    with pytest.raises(ReservaNoEncontradaError):
        clase.cancelar_reserva(s3, horas_anticipacion=5.0)

    # Inscripción extraordinaria Drop-in (US-019)
    drop_service = ServicioDeInscripcionExtraordinaria()
    with pytest.raises(PrecondicionOperacionError):
        drop_service.inscribir_drop_in(s3, clase, pago_confirmado=False)
    assert drop_service.inscribir_drop_in(s3, clase, pago_confirmado=True) == "CONFIRMADA"


def test_socio_plan_basico_limit_no_shows_and_physical_access():
    socio = Socio(
        "FIT-C001",
        "Socio Básico",
        activo=True,
        tipo_plan="BASICO",
        vigencia=Vigencia(date(2026, 11, 1), date(2026, 12, 31)),
    )
    c1 = ClaseProgramada("C1", "Yoga", "08:00", 10)
    c2 = ClaseProgramada("C2", "Pilates", "09:00", 10)
    c3 = ClaseProgramada("C3", "Box", "10:00", 10)

    c1.reservar(socio)
    c2.reservar(socio)
    # 3ra reserva simultánea en Plan Básico debe fallar (BRD P4 / US-013)
    with pytest.raises(LimiteReservasPlanError):
        c3.reservar(socio)

    # La asistencia no borra no-shows previos del mes (BRD P6 / US-011).
    socio.registrar_no_show(date(2026, 11, 4))
    socio.registrar_asistencia()
    assert socio.no_shows_mes == 1

    # Dos faltas adicionales completan el umbral mensual y activan siete días.
    assert socio.registrar_no_show(date(2026, 11, 4)) is False
    assert socio.registrar_no_show(date(2026, 11, 4)) is True
    assert socio.bloqueado_reservas is True
    assert socio.dias_bloqueo_restantes == 7

    with pytest.raises(SocioBloqueadoError):
        c3.reservar(socio)

    # Acceso físico en torniquete sigue permitido mientras su membresía esté vigente
    acceso_ok = socio.verificar_acceso_fisico(date(2026, 11, 15))
    assert acceso_ok["permitido"] is True

    # Si la fecha está fuera de vigencia, se rechaza con motivo "Membresía Vencida"
    acceso_venc = socio.verificar_acceso_fisico(date(2027, 1, 5))
    assert acceso_venc["permitido"] is False
    assert acceso_venc["motivo"] == "Membresía Vencida"

    # Si el socio está inactivo/suspendido
    socio.activo = False
    acceso_inact = socio.verificar_acceso_fisico(date(2026, 11, 15))
    assert acceso_inact["permitido"] is False
    with pytest.raises(MembresiaInactivaError):
        c3.reservar(socio)


def test_instructor_reasignacion_y_cancelacion():
    clase = ClaseProgramada("CLASE-BOX", "Box", "19:00", 10, instructor_id="INST-01")
    socio = socio_vigente("FIT-C010", "Socio VIP", es_preferente=True, activo=True)
    clase.reservar(socio)

    with pytest.raises(DatosInvalidosError):
        clase.reasignar_instructor("")

    clase.reasignar_instructor("INST-SUPLENTE-02")
    assert clase.instructor_id == "INST-SUPLENTE-02"

    # Instructor intenta cancelar con menos de 2h de anticipación -> falla
    with pytest.raises(CancelacionTardiaError):
        clase.cancelar_por_instructor(horas_anticipacion=1.0)

    # Cancelación válida >= 2h
    clase.cancelar_por_instructor(horas_anticipacion=2.5, motivo="Emergencia")
    assert clase.cancelada is True

    with pytest.raises(TransicionEstadoInvalidaError):
        clase.reservar(socio)


def test_waitlist_promotion_requires_confirmation_and_expires_fifo():
    from datetime import datetime, timedelta

    titular = socio_vigente("S-1", "Titular", tipo_plan="PREMIUM")
    primero = socio_vigente("S-2", "Primero", tipo_plan="PREMIUM")
    segundo = socio_vigente("S-3", "Segundo", tipo_plan="PREMIUM")
    clase = ClaseProgramada("C-FIFO", "Yoga", "08:00", 1)
    clase.reservar(titular)
    clase.reservar(primero)
    clase.reservar(segundo)
    clase.cancelar_reserva(titular, 4)
    assert clase.reservas["S-2"].estado == EstadoReserva.PROMOCION_PENDIENTE
    assert clase.cupos_disponibles == 0
    clase.promocion_expira_en = datetime.now() - timedelta(seconds=1)
    assert clase.expirar_promocion() == "S-3"
    assert clase.reservas["S-2"].estado == EstadoReserva.CANCELADA
    assert clase.reservas["S-3"].estado == EstadoReserva.PROMOCION_PENDIENTE
    clase.confirmar_promocion("S-3")
    assert clase.reservas["S-3"].estado == EstadoReserva.CONFIRMADA


def test_monthly_no_show_counter_resets_by_month_and_block_expires():
    socio = Socio("S-MES", "Socio", tipo_plan="PREMIUM")
    assert socio.registrar_no_show(date(2026, 10, 31)) is False
    assert socio.no_shows_mes == 1
    assert socio.registrar_no_show(date(2026, 11, 1)) is False
    assert socio.no_shows_mes == 1
    socio.registrar_no_show(date(2026, 11, 2))
    assert socio.registrar_no_show(date(2026, 11, 3)) is True
    assert socio.bloqueado_reservas is True
    socio.actualizar_bloqueo(date(2026, 11, 10))
    assert socio.bloqueado_reservas is False
    assert socio.dias_bloqueo_restantes == 0


def test_attendance_updates_reservation_state_without_erasing_monthly_no_shows():
    socio = socio_vigente("S-ASIS", "Socio", tipo_plan="PREMIUM")
    clase = ClaseProgramada("C-ASIS", "Spinning", "08:00", 3)
    clase.reservar(socio)
    socio.registrar_no_show(date(2026, 11, 1))
    # Simulamos una nueva reserva en otra clase y registramos asistencia.
    otra = ClaseProgramada("C-ASIS-2", "Yoga", "09:00", 3)
    otra.reservar(socio)
    otra.registrar_asistencia(socio)
    assert otra.reservas["S-ASIS"].estado == EstadoReserva.ASISTIDA
    assert socio.no_shows_mes == 1
    assert socio.reservas_activas_count == 1


def test_reservation_rejects_class_more_than_seven_days_ahead_and_unincluded_basic_class():
    from datetime import timedelta

    socio = socio_vigente("S-7D", "Socio", tipo_plan="BASICO")
    fuera_plazo = (date.today() + timedelta(days=8)).isoformat() + " 09:00"
    clase_futura = ClaseProgramada("C-8D", "Yoga", fuera_plazo, 5)
    with pytest.raises(DatosInvalidosError, match="7 días"):
        clase_futura.reservar(socio)

    clase_premium = ClaseProgramada("C-PREM", "Box", "08:00", 5, incluida_en_plan_basico=False)
    with pytest.raises(MembresiaInactivaError, match="Plan Básico"):
        clase_premium.reservar(socio)
    assert clase_premium.reservar(socio, es_drop_in=True, monto_drop_in=Decimal("180.00")) == "CONFIRMADA"


def test_actualizar_capacidad_rechaza_aforo_menor_a_reservas_activas():
    clase = ClaseProgramada("CAP-01", "Yoga", "2026-11-05 10:00", 2)
    clase.reservar(socio_vigente("SOC-01", "Socio Uno"))
    clase.actualizar_capacidad(3)
    assert clase.capacidad_maxima == 3
    assert clase.cupos_disponibles == 2
    with pytest.raises(DatosInvalidosError):
        clase.actualizar_capacidad(0)
    with pytest.raises(DatosInvalidosError):
        clase.actualizar_capacidad(0)  # no se permite capacidad nula
