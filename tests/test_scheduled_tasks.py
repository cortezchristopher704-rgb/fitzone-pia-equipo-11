from datetime import date, datetime, timedelta

from src.application.scheduled_tasks import (
    generar_alertas_vencimiento,
    procesar_promociones_expiradas,
)
from src.domain.models import ClaseProgramada, EstadoReserva, Reserva, Socio
from src.domain.value_objects import Vigencia
from src.infrastructure.database import make_engine, make_session
from src.infrastructure.repositories import SqlClaseProgramadaRepository, SqlSocioRepository


def test_worker_expires_promotion_and_promotes_next_fifo():
    engine = make_engine("sqlite:///:memory:")
    session = make_session(engine)
    try:
        ahora = datetime(2026, 11, 5, 10, 0)
        clase = ClaseProgramada(
            clase_id="CLASE-WORKER-01",
            disciplina="Spinning",
            horario="2026-11-06 10:00",
            capacidad_maxima=1,
            reservas={
                "FIT-C001": Reserva("FIT-C001", "CLASE-WORKER-01", EstadoReserva.PROMOCION_PENDIENTE),
            },
            lista_espera=["FIT-C002", "FIT-C003"],
            promocion_pendiente_socio_id="FIT-C001",
            promocion_expira_en=ahora - timedelta(minutes=1),
        )
        repo = SqlClaseProgramadaRepository(session)
        repo.save(clase)
        session.commit()

        resultado = procesar_promociones_expiradas(session, ahora)
        assert resultado["procesadas"] == 1
        assert resultado["detalle"][0]["socio_expirado"] == "FIT-C001"
        assert resultado["detalle"][0]["siguiente_socio_promovido"] == "FIT-C002"

        actualizada = SqlClaseProgramadaRepository(session).get_by_id("CLASE-WORKER-01")
        assert actualizada.promocion_pendiente_socio_id == "FIT-C002"
        assert actualizada.lista_espera == ["FIT-C003"]
        assert actualizada.reservas["FIT-C001"].estado == EstadoReserva.CANCELADA
        from src.infrastructure.database import NotificacionOutboxRow
        aviso = session.query(NotificacionOutboxRow).filter_by(destinatario_id="FIT-C002").one()
        assert "30 minutos" in aviso.mensaje
    finally:
        session.close()
        engine.dispose()


def test_daily_expiry_alerts_include_only_active_members_within_window():
    engine = make_engine("sqlite:///:memory:")
    session = make_session(engine)
    try:
        hoy = date(2026, 11, 5)
        repo = SqlSocioRepository(session)
        repo.save(Socio("FIT-C001", "Ana", vigencia=Vigencia(hoy - timedelta(days=20), hoy + timedelta(days=3))))
        repo.save(Socio("FIT-C002", "Bruno", activo=False, vigencia=Vigencia(hoy - timedelta(days=20), hoy + timedelta(days=2))))
        repo.save(Socio("FIT-C003", "Carla", vigencia=Vigencia(hoy - timedelta(days=20), hoy + timedelta(days=10))))
        repo.save(Socio("FIT-C004", "Diego", vigencia=Vigencia(hoy - timedelta(days=20), hoy - timedelta(days=1))))
        session.commit()

        resultado = generar_alertas_vencimiento(session, dias_anticipacion=7, hoy=hoy)
        assert resultado["total_alertas"] == 1
        assert resultado["alertas"][0]["socio_id"] == "FIT-C001"
        assert resultado["alertas"][0]["dias_restantes"] == 3
    finally:
        session.close()
        engine.dispose()


def test_worker_cycle_runs_promotion_scan(monkeypatch):
    from src.jobs.worker import ejecutar_ciclo

    monkeypatch.setenv("FITZONE_ALERTA_HORA", "23:59")
    engine = make_engine("sqlite:///:memory:")
    session = make_session(engine)
    try:
        ahora = datetime.now()
        clase = ClaseProgramada(
            clase_id="CLASE-WORKER-CYCLE",
            disciplina="Yoga",
            horario="2026-11-06 10:00",
            capacidad_maxima=1,
            reservas={"FIT-C010": Reserva("FIT-C010", "CLASE-WORKER-CYCLE", EstadoReserva.PROMOCION_PENDIENTE)},
            promocion_pendiente_socio_id="FIT-C010",
            promocion_expira_en=ahora - timedelta(minutes=1),
        )
        SqlClaseProgramadaRepository(session).save(clase)
        SqlSocioRepository(session).save(Socio(
            "FIT-WORKER-EXPIRED", "Socio expirado", activo=True,
            vigencia=Vigencia(date(2026, 1, 1), date(2026, 1, 31)),
        ))
        session.commit()
    finally:
        session.close()

    try:
        ultima_fecha = ejecutar_ciclo(engine, None)
        assert ultima_fecha is None
        session = make_session(engine)
        actualizada = SqlClaseProgramadaRepository(session).get_by_id("CLASE-WORKER-CYCLE")
        assert actualizada.promocion_pendiente_socio_id is None
        assert actualizada.reservas["FIT-C010"].estado == EstadoReserva.CANCELADA
        assert SqlSocioRepository(session).get_by_id("FIT-WORKER-EXPIRED").activo is False
    finally:
        session.close()
        engine.dispose()


def test_worker_rejects_invalid_alert_schedule(monkeypatch):
    from src.jobs.worker import _hora_alertas

    monkeypatch.setenv("FITZONE_ALERTA_HORA", "25:99")
    try:
        _hora_alertas()
        assert False, "Se esperaba ValueError para hora inválida"
    except ValueError as exc:
        assert "HH:MM" in str(exc)


def test_api_cutoff_calculation_uses_persisted_schedule():
    from src.api.main import _calcular_horas_hasta_clase

    ahora = datetime(2026, 11, 5, 10, 0)
    assert _calcular_horas_hasta_clase("2026-11-05 14:00", ahora) == 4.0
    assert _calcular_horas_hasta_clase("11:00", ahora) == 1.0
    assert _calcular_horas_hasta_clase("09:00", ahora) == 23.0


def test_worker_expires_membership_cancels_reservation_and_promotes_fifo():
    from src.application.scheduled_tasks import procesar_membresias_vencidas

    engine = make_engine("sqlite:///:memory:")
    session = make_session(engine)
    try:
        hoy = date(2026, 11, 5)
        socios = SqlSocioRepository(session)
        socios.save(Socio(
            "FIT-EXP-01", "Socio vencido", activo=True,
            vigencia=Vigencia(date(2026, 10, 1), date(2026, 11, 4)),
            reservas_activas_count=1,
        ))
        socios.save(Socio(
            "FIT-EXP-02", "Socio en espera", activo=True,
            vigencia=Vigencia(date(2026, 10, 1), date(2026, 12, 1)),
        ))
        clase = ClaseProgramada(
            clase_id="CLASE-EXP-01", disciplina="Yoga", horario="2026-11-06 10:00",
            capacidad_maxima=1,
            reservas={"FIT-EXP-01": Reserva("FIT-EXP-01", "CLASE-EXP-01", EstadoReserva.CONFIRMADA)},
            lista_espera=["FIT-EXP-02"],
        )
        clases = SqlClaseProgramadaRepository(session)
        clases.save(clase)
        session.commit()

        resultado = procesar_membresias_vencidas(session, hoy=hoy)
        assert resultado["procesadas"] == 1
        assert resultado["detalle"][0]["reservas_liberadas"] == 1
        assert resultado["detalle"][0]["promociones_fifo"] == [
            {"clase_id": "CLASE-EXP-01", "socio_promovido": "FIT-EXP-02"}
        ]

        socio_vencido = socios.get_by_id("FIT-EXP-01")
        clase_actualizada = clases.get_by_id("CLASE-EXP-01")
        assert socio_vencido.activo is False
        assert socio_vencido.reservas_activas_count == 0
        assert clase_actualizada.reservas["FIT-EXP-01"].estado == EstadoReserva.CANCELADA
        assert clase_actualizada.promocion_pendiente_socio_id == "FIT-EXP-02"
        assert clase_actualizada.lista_espera == []
        assert socios.get_by_id("FIT-EXP-02").reservas_activas_count == 1

        # El barrido diario es idempotente: no vuelve a procesar al socio inactivo.
        segundo = procesar_membresias_vencidas(session, hoy=hoy)
        assert segundo["procesadas"] == 0
    finally:
        session.close()
        engine.dispose()


def test_membership_expiry_does_not_disable_on_final_valid_day():
    from src.application.scheduled_tasks import procesar_membresias_vencidas

    engine = make_engine("sqlite:///:memory:")
    session = make_session(engine)
    try:
        hoy = date(2026, 11, 5)
        SqlSocioRepository(session).save(Socio(
            "FIT-EXP-03", "Socio vigente", activo=True,
            vigencia=Vigencia(date(2026, 10, 1), hoy),
        ))
        session.commit()
        resultado = procesar_membresias_vencidas(session, hoy=hoy)
        assert resultado["procesadas"] == 0
        assert SqlSocioRepository(session).get_by_id("FIT-EXP-03").activo is True
    finally:
        session.close()
        engine.dispose()


def test_membership_expiry_transitions_active_contract_to_expired():
    from src.application.scheduled_tasks import procesar_membresias_vencidas
    from src.domain.models import EstadoOperacion, OperacionMembresia
    from src.infrastructure.repositories import SqlOperacionRepository

    engine = make_engine("sqlite:///:memory:")
    session = make_session(engine)
    try:
        hoy = date(2026, 11, 5)
        socio = Socio(
            "FIT-EXP-04", "Socio con contrato", activo=True,
            vigencia=Vigencia(date(2026, 10, 1), date(2026, 11, 4)),
        )
        socio_repo = SqlSocioRepository(session)
        socio_repo.save(socio)
        SqlOperacionRepository(session, socio_repo).save(OperacionMembresia(
            "OP-EXP-04", socio, estado=EstadoOperacion.ACTIVA,
        ))
        session.commit()

        resultado = procesar_membresias_vencidas(session, hoy=hoy)
        assert resultado["procesadas"] == 1
        operacion = SqlOperacionRepository(session, socio_repo).get_by_id("OP-EXP-04")
        assert operacion.estado == EstadoOperacion.VENCIDA
        assert socio_repo.get_by_id("FIT-EXP-04").activo is False
    finally:
        session.close()
        engine.dispose()


def test_worker_daily_alerts_are_persisted_to_admin_outbox(monkeypatch):
    from src.jobs.worker import ejecutar_ciclo
    from src.infrastructure.database import NotificacionOutboxRow

    ahora = datetime.now()
    monkeypatch.setenv("FITZONE_ALERTA_HORA", f"{ahora.hour:02d}:00")
    monkeypatch.setenv("FITZONE_ALERTA_DIAS", "7")
    engine = make_engine("sqlite:///:memory:")
    session = make_session(engine)
    try:
        SqlSocioRepository(session).save(Socio(
            "FIT-ALERT-01", "Socio por vencer", activo=True,
            vigencia=Vigencia(date.today() - timedelta(days=20), date.today() + timedelta(days=3)),
        ))
        session.commit()
    finally:
        session.close()

    try:
        ejecutar_ciclo(engine, None)
        session = make_session(engine)
        avisos = session.query(NotificacionOutboxRow).filter_by(destinatario_id="ADMIN").all()
        assert len(avisos) == 1
        assert avisos[0].estado == "PENDIENTE"
        assert "FIT-ALERT-01" in avisos[0].mensaje
    finally:
        session.close()
        engine.dispose()
