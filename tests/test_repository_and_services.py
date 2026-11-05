"""Pruebas de Integración de Base de Datos SQLite (Commit / Rollback) y Dobles de Prueba (Mocks)."""

from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from src.application import (
    AsistenciaAppService,
    ControlAccesoAppService,
    MembresiaAppService,
    NotificadorPort,
    PasarelaPagoPort,
    ReportesQueryService,
    ReservaAppService,
    TorniquetePort,
)
from src.domain import (
    CancelacionTardiaError,
    ClaseProgramada,
    OperacionMembresia,
    PlanDeportivo,
    PrecondicionOperacionError,
    RecursoNoDisponibleError,
    Socio,
    TransicionEstadoInvalidaError,
)
from src.domain.value_objects import Money
from src.infrastructure import (
    SqlAlchemyUnitOfWork,
    SqlCatalogoRepository,
    SqlClaseProgramadaRepository,
    SqlOperacionRepository,
    SqlSocioRepository,
    make_engine,
    make_session,
    poblar_base_de_datos,
)


def _fresh_db():
    engine = make_engine("sqlite:///:memory:")
    session = make_session(engine)
    return session


def test_repository_commit_and_rollback_acid():
    session = _fresh_db()
    socio_repo = SqlSocioRepository(session)
    cat_repo = SqlCatalogoRepository(session)
    op_repo = SqlOperacionRepository(session, socio_repo)
    uow = SqlAlchemyUnitOfWork(session)

    # 1. Commit exitoso
    socio = Socio("FIT-C999", "Socio Transaccional", es_preferente=True, activo=True)
    plan = PlanDeportivo("FIT-P999", "Anual VIP", Money(Decimal("2000.00")), 10, True)
    op = OperacionMembresia("FIT-O999", socio)
    op.agregar_linea(plan, 1)

    socio_repo.save(socio)
    cat_repo.save(plan)
    op_repo.save(op)
    uow.commit()

    assert socio_repo.get_by_id("FIT-C999") is not None
    assert cat_repo.get_by_id("FIT-P999") is not None
    assert op_repo.get_by_id("FIT-O999") is not None

    # 2. Rollback ante error no persiste cambios sucios
    socio_temp = Socio("FIT-TEMP", "Socio Temporal", activo=True)
    socio_repo.save(socio_temp)
    uow.rollback()
    assert socio_repo.get_by_id("FIT-TEMP") is None

    # Verificar reconstrucción de socio implícito cuando no existe previamente en tabla socios
    op_orphan = OperacionMembresia("FIT-ORPHAN", Socio("FIT-GHOST", "Ghost"))
    op_repo.save(op_orphan)
    uow.commit()
    from src.infrastructure.database import SocioRow
    session.query(SocioRow).filter_by(actor_id="FIT-GHOST").delete()
    uow.commit()
    recovered_op = op_repo.get_by_id("FIT-ORPHAN")
    assert recovered_op is not None
    assert recovered_op.socio.actor_id == "FIT-GHOST"
    engine = session.get_bind()
    session.close()
    engine.dispose()


def test_application_services_with_mocks_and_uow():
    session = _fresh_db()
    resumen = poblar_base_de_datos(session)
    assert resumen["socios"] == 40
    assert resumen["operaciones"] == 60

    socio_repo = SqlSocioRepository(session)
    from src.domain.value_objects import Vigencia
    from datetime import date, timedelta
    for socio_demo in socio_repo.list_all():
        socio_demo.vigencia = Vigencia(date.today() - timedelta(days=1), date.today() + timedelta(days=365))
        socio_repo.save(socio_demo)
    session.commit()
    cat_repo = SqlCatalogoRepository(session)
    op_repo = SqlOperacionRepository(session, socio_repo)
    clase_repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)

    mock_notif = Mock(spec=NotificadorPort)
    mock_notif.enviar_notificacion.return_value = True
    mock_pago = Mock(spec=PasarelaPagoPort)
    mock_pago.cobrar.return_value = True
    mock_torniquete = Mock(spec=TorniquetePort)
    mock_torniquete.abrir_barrera.return_value = True

    membresia_srv = MembresiaAppService(op_repo, socio_repo, cat_repo, uow, notificador=mock_notif)
    reserva_srv = ReservaAppService(
        socio_repo, clase_repo, uow, notificador=mock_notif, pasarela_pago=mock_pago
    )
    asistencia_srv = AsistenciaAppService(socio_repo, clase_repo, uow, notificador=mock_notif)
    acceso_srv = ControlAccesoAppService(socio_repo, torniquete=mock_torniquete)
    query_srv = ReportesQueryService(socio_repo, clase_repo, op_repo)

    # Evaluar y aprobar operación válida FIT-O004 (VIP)
    eval_res = membresia_srv.evaluar_operacion("FIT-O004")
    assert eval_res["puede_procesarse"] is True
    assert eval_res["beneficio_preferente"] is True

    op_act = membresia_srv.aprobar_operacion("FIT-O004")
    assert op_act.estado.value == "ACTIVA"
    mock_notif.enviar_notificacion.assert_called()

    # Suspender y vencer operación, cancelando reservas activas del socio (US-018)
    reserva_srv.reservar_clase("FIT-C040", "CLASE-01")
    membresia_srv.suspender_operacion("FIT-O004", "Revisión")
    op_venc = membresia_srv.vencer_operacion("FIT-O004", clase_repo=clase_repo)
    assert op_venc.estado.value == "VENCIDA"
    assert "FIT-C040" not in clase_repo.get_by_id("CLASE-01").reservas_confirmadas_ids

    # Cancelar operación en estado SOLICITADA (FIT-O002)
    op_canc = membresia_srv.cancelar_operacion("FIT-O002", "Ya no desea el plan")
    assert op_canc.estado.value == "CANCELADA"

    # Errores de negocio y rollback en MembresiaAppService
    with pytest.raises(RecursoNoDisponibleError):
        membresia_srv.evaluar_operacion("FIT-INEXISTENTE")
    with pytest.raises(RecursoNoDisponibleError):
        membresia_srv.aprobar_operacion("FIT-INEXISTENTE")
    with pytest.raises(PrecondicionOperacionError):
        membresia_srv.aprobar_operacion("FIT-O005")
    with pytest.raises(RecursoNoDisponibleError):
        membresia_srv.suspender_operacion("FIT-INEXISTENTE")
    with pytest.raises(TransicionEstadoInvalidaError):
        membresia_srv.suspender_operacion("FIT-O001")
    with pytest.raises(RecursoNoDisponibleError):
        membresia_srv.vencer_operacion("FIT-INEXISTENTE")
    with pytest.raises(TransicionEstadoInvalidaError):
        membresia_srv.vencer_operacion("FIT-O001")
    with pytest.raises(RecursoNoDisponibleError):
        membresia_srv.cancelar_operacion("FIT-INEXISTENTE")
    with pytest.raises(TransicionEstadoInvalidaError):
        membresia_srv.cancelar_operacion("FIT-O004")

    # Reserva normal, lista de espera FIFO y promoción con notificación
    # CLASE-02 tiene capacidad_maxima=2
    reserva_srv.reservar_clase("FIT-C001", "CLASE-02")
    reserva_srv.reservar_clase("FIT-C002", "CLASE-02")
    res_espera = reserva_srv.reservar_clase("FIT-C003", "CLASE-02")
    assert res_espera["resultado"] == "LISTA_ESPERA"

    # Cancelar FIT-C001 promueve a FIT-C003 y le envía notificación
    res_prom = reserva_srv.cancelar_reserva("FIT-C001", "CLASE-02", horas_anticipacion=5.0)
    assert res_prom["socio_promovido"] == "FIT-C003"
    clase_repo.get_by_id("CLASE-02").confirmar_promocion("FIT-C003")
    clase_confirmada = clase_repo.get_by_id("CLASE-02")
    clase_repo.save(clase_confirmada)
    uow.commit()

    # Reserva Drop-in con pasarela mockeada
    res_drop = reserva_srv.reservar_clase("FIT-C001", "CLASE-01", es_drop_in=True)
    assert res_drop["resultado"] == "CONFIRMADA"
    mock_pago.cobrar.assert_called_once()

    # Errores en ReservaAppService
    with pytest.raises(RecursoNoDisponibleError):
        reserva_srv.reservar_clase("NO-EXISTE", "CLASE-01")
    with pytest.raises(RecursoNoDisponibleError):
        reserva_srv.reservar_clase("FIT-C001", "NO-EXISTE")
    with pytest.raises(RecursoNoDisponibleError):
        reserva_srv.cancelar_reserva("NO-EXISTE", "CLASE-01")
    with pytest.raises(RecursoNoDisponibleError):
        reserva_srv.cancelar_reserva("FIT-C001", "NO-EXISTE")
    with pytest.raises(CancelacionTardiaError):
        reserva_srv.cancelar_reserva("FIT-C001", "CLASE-01", horas_anticipacion=1.0)

    # Cada no-show requiere una reserva confirmada distinta.
    for idx in range(1, 4):
        clase_ns = ClaseProgramada(f"CLASE-NS-{idx}", "Yoga", "2026-11-07 10:00", 5)
        clase_repo.save(clase_ns)
        socio_ns = socio_repo.get_by_id("FIT-C008")
        clase_ns.reservar(socio_ns)
        socio_repo.save(socio_ns)
        clase_repo.save(clase_ns)
        uow.commit()
        res_ns3 = asistencia_srv.registrar_no_show("FIT-C008", f"CLASE-NS-{idx}")
    assert res_ns3["bloqueado_reservas"] is True

    with pytest.raises(RecursoNoDisponibleError):
        asistencia_srv.registrar_no_show("NO-EXISTE", "CLASE-01")
    with pytest.raises(RecursoNoDisponibleError):
        asistencia_srv.registrar_no_show("FIT-C008", "NO-EXISTE")

    # ControlAccesoAppService: acceso permitido solo con vigencia registrada y vigente.
    socio_con_vigencia = socio_repo.get_by_id("FIT-C001")
    from src.domain.value_objects import Vigencia
    socio_con_vigencia.vigencia = Vigencia(date.today() - timedelta(days=1), date.today() + timedelta(days=30))
    socio_repo.save(socio_con_vigencia)
    uow.commit()
    acc_ok = acceso_srv.validar_ingreso("FIT-C001")
    assert acc_ok["permitido"] is True
    assert acc_ok["barrera_abierta"] is True
    mock_torniquete.abrir_barrera.assert_called_once_with("FIT-C001")

    with pytest.raises(RecursoNoDisponibleError):
        acceso_srv.validar_ingreso("NO-EXISTE")

    # Reportes CQRS
    rep_ocup = query_srv.reporte_ocupacion_clases()
    rep_ns = query_srv.reporte_no_shows_socios()
    assert len(rep_ocup) >= 3
    assert len(rep_ns) == 40
    engine = session.get_bind()
    session.close()
    engine.dispose()
