"""Casos de uso invocados por el worker programado de FitZone."""
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from src.domain.models import EstadoOperacion, EstadoReserva, Reserva
from src.infrastructure.repositories import (
    SqlAlchemyUnitOfWork,
    SqlClaseProgramadaRepository,
    SqlOperacionRepository,
    SqlOutboxNotificador,
    SqlSocioRepository,
)


def procesar_promociones_expiradas(session: Session, ahora: datetime | None = None) -> dict[str, Any]:
    """Expira promociones vencidas y promueve al siguiente socio respetando FIFO."""
    ahora = ahora or datetime.now()
    repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)
    procesadas: list[dict[str, str | None]] = []

    try:
        for clase in repo.list_all():
            socio_pendiente = clase.promocion_pendiente_socio_id
            fecha_expiracion = clase.promocion_expira_en
            if socio_pendiente and fecha_expiracion and ahora >= fecha_expiracion:
                siguiente = clase.expirar_promocion(ahora)
                socio_expirado = SqlSocioRepository(session).get_by_id(socio_pendiente)
                if socio_expirado:
                    socio_expirado.reservas_activas_count = max(0, socio_expirado.reservas_activas_count - 1)
                    SqlSocioRepository(session).save(socio_expirado)
                if siguiente:
                    socio_siguiente = SqlSocioRepository(session).get_by_id(siguiente)
                    if socio_siguiente:
                        socio_siguiente.reservas_activas_count += 1
                        SqlSocioRepository(session).save(socio_siguiente)
                    SqlOutboxNotificador(session).enviar_notificacion(
                        siguiente, "Lugar disponible en lista de espera",
                        f"Fuiste promovido a la clase {clase.disciplina}. Tienes {clase.ventana_confirmacion_minutos} minutos para confirmar."
                    )
                repo.save(clase)
                procesadas.append({
                    "clase_id": clase.clase_id,
                    "socio_expirado": socio_pendiente,
                    "siguiente_socio_promovido": siguiente,
                })
        if procesadas:
            uow.commit()
        return {"procesadas": len(procesadas), "detalle": procesadas}
    except Exception:
        uow.rollback()
        raise


def generar_alertas_vencimiento(
    session: Session,
    dias_anticipacion: int = 7,
    hoy: date | None = None,
) -> dict[str, Any]:
    """Genera el conjunto diario de alertas para membresías próximas a vencer."""
    if not 0 <= dias_anticipacion <= 365:
        raise ValueError("dias_anticipacion debe estar entre 0 y 365")
    hoy = hoy or date.today()
    limite = hoy + timedelta(days=dias_anticipacion)
    socios = SqlSocioRepository(session).list_all()
    alertas = [
        {
            "socio_id": socio.actor_id,
            "nombre": socio.nombre,
            "fecha_vencimiento": socio.vigencia.fecha_fin.isoformat(),
            "dias_restantes": (socio.vigencia.fecha_fin - hoy).days,
        }
        for socio in socios
        if socio.activo and socio.vigencia is not None and hoy <= socio.vigencia.fecha_fin <= limite
    ]
    return {
        "fecha_consulta": hoy.isoformat(),
        "dias_anticipacion": dias_anticipacion,
        "total_alertas": len(alertas),
        "alertas": alertas,
    }


def procesar_membresias_vencidas(session: Session, hoy: date | None = None) -> dict[str, Any]:
    """US-018: desactiva socios vencidos y libera sus reservas confirmadas o promociones.

    La vigencia termina al cierre de fecha_fin; por ello se procesa cuando hoy > fecha_fin.
    Las plazas liberadas se ofrecen respetando FIFO y la ventana de confirmación existente.
    """
    hoy = hoy or date.today()
    socio_repo = SqlSocioRepository(session)
    clase_repo = SqlClaseProgramadaRepository(session)
    operacion_repo = SqlOperacionRepository(session, socio_repo)
    uow = SqlAlchemyUnitOfWork(session)
    procesados: list[dict[str, Any]] = []

    try:
        socios_vencidos = [
            socio for socio in socio_repo.list_all()
            if socio.activo and socio.vigencia is not None and hoy > socio.vigencia.fecha_fin
        ]
        if not socios_vencidos:
            return {"procesadas": 0, "detalle": []}

        clases = clase_repo.list_all()
        operaciones = operacion_repo.list_all()
        for socio in socios_vencidos:
            socio.activo = False
            reservas_liberadas = 0
            promociones: list[dict[str, str | None]] = []

            for clase in clases:
                estado = clase.reservas.get(socio.actor_id)
                if estado is not None and estado.estado == EstadoReserva.CONFIRMADA:
                    promovido = clase.cancelar_por_vencimiento_membresia(socio)
                    reservas_liberadas += 1
                    if promovido:
                        socio_promovido = socio_repo.get_by_id(promovido)
                        if socio_promovido:
                            socio_promovido.reservas_activas_count += 1
                            socio_repo.save(socio_promovido)
                        SqlOutboxNotificador(session).enviar_notificacion(
                            promovido, "Lugar disponible por vencimiento de membresía",
                            f"Fuiste promovido a la clase {clase.disciplina}. Tienes {clase.ventana_confirmacion_minutos} minutos para confirmar."
                        )
                        promociones.append({"clase_id": clase.clase_id, "socio_promovido": promovido})
                elif estado is not None and estado.estado == EstadoReserva.PROMOCION_PENDIENTE:
                    estado.estado = EstadoReserva.CANCELADA
                    socio.reservas_activas_count = max(0, socio.reservas_activas_count - 1)
                    if clase.promocion_pendiente_socio_id == socio.actor_id:
                        clase.promocion_pendiente_socio_id = None
                        clase.promocion_expira_en = None
                        siguiente = clase.lista_espera.pop(0) if clase.lista_espera else None
                        if siguiente:
                            clase.reservas[siguiente] = Reserva(
                                socio_id=siguiente, clase_id=clase.clase_id,
                                estado=EstadoReserva.PROMOCION_PENDIENTE,
                            )
                            clase.promocion_pendiente_socio_id = siguiente
                            clase.promocion_expira_en = datetime.now() + timedelta(minutes=clase.ventana_confirmacion_minutos)
                            socio_siguiente = socio_repo.get_by_id(siguiente)
                            if socio_siguiente:
                                socio_siguiente.reservas_activas_count += 1
                                socio_repo.save(socio_siguiente)
                            SqlOutboxNotificador(session).enviar_notificacion(
                                siguiente, "Lugar disponible por vencimiento de membresía",
                                f"Fuiste promovido a la clase {clase.disciplina}. Tienes {clase.ventana_confirmacion_minutos} minutos para confirmar."
                            )
                            promociones.append({"clase_id": clase.clase_id, "socio_promovido": siguiente})
                    reservas_liberadas += 1
                elif socio.actor_id in clase.lista_espera:
                    clase.lista_espera.remove(socio.actor_id)
                    if estado is not None:
                        estado.estado = EstadoReserva.CANCELADA

            for operacion in operaciones:
                if operacion.socio.actor_id == socio.actor_id and operacion.estado in (EstadoOperacion.ACTIVA, EstadoOperacion.SUSPENDIDA):
                    operacion.vencer()
                    operacion_repo.save(operacion)

            socio_repo.save(socio)
            procesados.append({
                "socio_id": socio.actor_id,
                "fecha_vencimiento": socio.vigencia.fecha_fin.isoformat(),
                "reservas_liberadas": reservas_liberadas,
                "promociones_fifo": promociones,
            })

        for clase in clases:
            clase_repo.save(clase)
        uow.commit()
        return {"procesadas": len(procesados), "detalle": procesados}
    except Exception:
        uow.rollback()
        raise
