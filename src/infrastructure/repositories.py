"""Implementaciones concretas de Repositorios SQLAlchemy y Unit of Work para FitZone."""

import json
from decimal import Decimal
from datetime import date, datetime, UTC

from sqlalchemy.orm import Session

from src.domain.events import DomainEvent
from src.domain.models import (
    ClaseProgramada,
    EstadoOperacion,
    EstadoReserva,
    OperacionMembresia,
    PlanDeportivo,
    Reserva,
    Socio,
)
from src.domain.value_objects import LineaOperacion, Money, Vigencia
from src.infrastructure.database import (
    ClaseProgramadaRow,
    OperacionMembresiaRow,
    PlanDeportivoRow,
    SocioRow,
    NotificacionOutboxRow,
)


class SqlAlchemyUnitOfWork:
    """Implementa el control transaccional explícito (commit / rollback)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()


class SqlSocioRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _to_domain(self, row: SocioRow) -> Socio:
        return Socio(
            actor_id=row.actor_id,
            nombre=row.nombre,
            es_preferente=bool(row.es_preferente),
            activo=bool(row.activo),
            ciudad=row.ciudad,
            tipo_plan=row.tipo_plan,
            no_shows_mes=int(row.no_shows_mes),
            bloqueado_reservas=bool(row.bloqueado_reservas),
            dias_bloqueo_restantes=int(row.dias_bloqueo_restantes),
            reservas_activas_count=int(row.reservas_activas_count),
            vigencia=(Vigencia(date.fromisoformat(row.vigencia_inicio), date.fromisoformat(row.vigencia_fin))
                      if row.vigencia_inicio and row.vigencia_fin else None),
            periodo_no_shows=row.periodo_no_shows or "",
            bloqueo_hasta=date.fromisoformat(row.bloqueo_hasta) if row.bloqueo_hasta else None,
        )

    def get_by_id(self, actor_id: str) -> Socio | None:
        row = self.session.get(SocioRow, actor_id)
        return self._to_domain(row) if row else None

    def list_all(self) -> list[Socio]:
        rows = self.session.query(SocioRow).order_by(SocioRow.actor_id).all()
        return [self._to_domain(r) for r in rows]

    def save(self, socio: Socio) -> None:
        row = SocioRow(
            actor_id=socio.actor_id,
            nombre=socio.nombre,
            es_preferente=socio.es_preferente,
            activo=socio.activo,
            ciudad=socio.ciudad,
            tipo_plan=socio.tipo_plan,
            no_shows_mes=socio.no_shows_mes,
            bloqueado_reservas=socio.bloqueado_reservas,
            dias_bloqueo_restantes=socio.dias_bloqueo_restantes,
            reservas_activas_count=socio.reservas_activas_count,
            vigencia_inicio=socio.vigencia.fecha_inicio.isoformat() if socio.vigencia else None,
            vigencia_fin=socio.vigencia.fecha_fin.isoformat() if socio.vigencia else None,
            periodo_no_shows=socio.periodo_no_shows,
            bloqueo_hasta=socio.bloqueo_hasta.isoformat() if socio.bloqueo_hasta else None,
        )
        self.session.merge(row)


class SqlCatalogoRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _to_domain(self, row: PlanDeportivoRow) -> PlanDeportivo:
        return PlanDeportivo(
            recurso_id=row.recurso_id,
            descripcion=row.descripcion,
            precio_mxn=Money(Decimal(row.precio_mxn), "MXN"),
            capacidad_o_stock=int(row.capacidad_o_stock),
            habilitado=bool(row.habilitado),
        )

    def get_by_id(self, recurso_id: str) -> PlanDeportivo | None:
        row = self.session.get(PlanDeportivoRow, recurso_id)
        return self._to_domain(row) if row else None

    def list_all(self) -> list[PlanDeportivo]:
        rows = self.session.query(PlanDeportivoRow).order_by(PlanDeportivoRow.recurso_id).all()
        return [self._to_domain(r) for r in rows]

    def save(self, plan: PlanDeportivo) -> None:
        row = PlanDeportivoRow(
            recurso_id=plan.recurso_id,
            descripcion=plan.descripcion,
            precio_mxn=str(plan.precio_mxn.amount),
            capacidad_o_stock=plan.capacidad_o_stock,
            habilitado=plan.habilitado,
        )
        self.session.merge(row)


class SqlOperacionRepository:
    def __init__(self, session: Session, socio_repo: SqlSocioRepository) -> None:
        self.session = session
        self.socio_repo = socio_repo

    def _to_domain(self, row: OperacionMembresiaRow) -> OperacionMembresia:
        socio = self.socio_repo.get_by_id(row.actor_id)
        if socio is None:
            socio = Socio(actor_id=row.actor_id, nombre=f"Socio {row.actor_id}")

        raw_lineas = json.loads(row.lineas_json or "[]")
        lineas = [
            LineaOperacion(
                recurso_id=item["recurso_id"],
                descripcion=item["descripcion"],
                precio_unitario=Money(Decimal(item["precio_unitario"]), "MXN"),
                cantidad=int(item["cantidad"]),
                recurso_habilitado=bool(item.get("recurso_habilitado", True)),
                stock_disponible=int(item.get("stock_disponible", 999)),
            )
            for item in raw_lineas
        ]

        raw_eventos = json.loads(row.eventos_json or "[]")
        eventos = [
            DomainEvent(
                nombre=ev["nombre"],
                entidad_id=ev["entidad_id"],
                detalles=ev.get("detalles", {}),
                ocurrido_en=ev.get("ocurrido_en", ""),
            )
            for ev in raw_eventos
        ]

        return OperacionMembresia(
            operacion_id=row.operacion_id,
            socio=socio,
            estado=EstadoOperacion(row.estado),
            fecha_solicitud=row.fecha_solicitud,
            promocion_activa=bool(row.promocion_activa),
            autorizado=bool(row.autorizado),
            referencia=row.referencia,
            lineas=lineas,
            eventos=eventos,
        )

    def get_by_id(self, operacion_id: str) -> OperacionMembresia | None:
        row = self.session.get(OperacionMembresiaRow, operacion_id)
        return self._to_domain(row) if row else None

    def list_all(self) -> list[OperacionMembresia]:
        rows = (
            self.session.query(OperacionMembresiaRow)
            .order_by(OperacionMembresiaRow.operacion_id)
            .all()
        )
        return [self._to_domain(r) for r in rows]

    def save(self, op: OperacionMembresia) -> None:
        self.socio_repo.save(op.socio)
        row = OperacionMembresiaRow(
            operacion_id=op.operacion_id,
            actor_id=op.socio.actor_id,
            estado=op.estado.value,
            fecha_solicitud=op.fecha_solicitud,
            promocion_activa=op.promocion_activa,
            autorizado=op.autorizado,
            referencia=op.referencia,
            lineas_json=json.dumps(
                [
                    {
                        "recurso_id": l.recurso_id,
                        "descripcion": l.descripcion,
                        "precio_unitario": str(l.precio_unitario.amount),
                        "cantidad": l.cantidad,
                        "recurso_habilitado": l.recurso_habilitado,
                        "stock_disponible": l.stock_disponible,
                    }
                    for l in op.lineas
                ]
            ),
            eventos_json=json.dumps(
                [
                    {
                        "nombre": ev.nombre,
                        "entidad_id": ev.entidad_id,
                        "detalles": ev.detalles,
                        "ocurrido_en": ev.ocurrido_en,
                    }
                    for ev in op.eventos
                ]
            ),
        )
        self.session.merge(row)


class SqlClaseProgramadaRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _to_domain(self, row: ClaseProgramadaRow) -> ClaseProgramada:
        raw_res = json.loads(row.reservas_json or "{}")
        reservas: dict[str, Reserva] = {}
        for s_id, r_data in raw_res.items():
            reservas[s_id] = Reserva(
                socio_id=r_data["socio_id"],
                clase_id=r_data["clase_id"],
                estado=EstadoReserva(r_data["estado"]),
                es_drop_in=bool(r_data.get("es_drop_in", False)),
                tarifa_drop_in=Money(Decimal(r_data.get("tarifa_drop_in", "0.00")), "MXN"),
            )

        lista_espera = json.loads(row.lista_espera_json or "[]")
        raw_ev = json.loads(row.eventos_json or "[]")
        eventos = [
            DomainEvent(
                nombre=ev["nombre"],
                entidad_id=ev["entidad_id"],
                detalles=ev.get("detalles", {}),
                ocurrido_en=ev.get("ocurrido_en", ""),
            )
            for ev in raw_ev
        ]

        return ClaseProgramada(
            clase_id=row.clase_id,
            disciplina=row.disciplina,
            horario=row.horario,
            capacidad_maxima=int(row.capacidad_maxima),
            instructor_id=row.instructor_id,
            incluida_en_plan_basico=bool(row.incluida_en_plan_basico),
            planes_incluidos=set(json.loads(row.planes_incluidos_json)) if row.planes_incluidos_json is not None else None,
            cancelada=bool(row.cancelada),
            cut_off_horas_socio=float(row.cut_off_horas_socio),
            reservas=reservas,
            lista_espera=lista_espera,
            promocion_pendiente_socio_id=row.promocion_pendiente_socio_id,
            promocion_expira_en=datetime.fromisoformat(row.promocion_expira_en) if row.promocion_expira_en else None,
            eventos=eventos,
        )

    def get_by_id(self, clase_id: str) -> ClaseProgramada | None:
        row = self.session.get(ClaseProgramadaRow, clase_id)
        return self._to_domain(row) if row else None

    def list_all(self) -> list[ClaseProgramada]:
        rows = (
            self.session.query(ClaseProgramadaRow)
            .order_by(ClaseProgramadaRow.clase_id)
            .all()
        )
        return [self._to_domain(r) for r in rows]

    def save(self, clase: ClaseProgramada) -> None:
        row = ClaseProgramadaRow(
            clase_id=clase.clase_id,
            disciplina=clase.disciplina,
            horario=clase.horario,
            capacidad_maxima=clase.capacidad_maxima,
            instructor_id=clase.instructor_id,
            incluida_en_plan_basico=clase.incluida_en_plan_basico,
            planes_incluidos_json=(json.dumps(sorted(clase.planes_incluidos)) if clase.planes_incluidos is not None else None),
            cancelada=clase.cancelada,
            cut_off_horas_socio=clase.cut_off_horas_socio,
            reservas_json=json.dumps(
                {
                    s_id: {
                        "socio_id": r.socio_id,
                        "clase_id": r.clase_id,
                        "estado": r.estado.value,
                        "es_drop_in": r.es_drop_in,
                        "tarifa_drop_in": str(r.tarifa_drop_in.amount),
                    }
                    for s_id, r in clase.reservas.items()
                }
            ),
            lista_espera_json=json.dumps(clase.lista_espera),
            promocion_pendiente_socio_id=clase.promocion_pendiente_socio_id,
            promocion_expira_en=clase.promocion_expira_en.isoformat() if clase.promocion_expira_en else None,
            eventos_json=json.dumps(
                [
                    {
                        "nombre": ev.nombre,
                        "entidad_id": ev.entidad_id,
                        "detalles": ev.detalles,
                        "ocurrido_en": ev.ocurrido_en,
                    }
                    for ev in clase.eventos
                ]
            ),
        )
        self.session.merge(row)


class SqlOutboxNotificador:
    """Guarda notificaciones pendientes en una outbox transaccional.

    No envía correo/SMS por sí mismo; permite persistir y auditar los mensajes
    para que un adaptador externo los entregue posteriormente.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def enviar_notificacion(self, destinatario_id: str, asunto: str, mensaje: str) -> bool:
        self.session.add(NotificacionOutboxRow(
            destinatario_id=destinatario_id,
            asunto=asunto,
            mensaje=mensaje,
            estado="PENDIENTE",
            creado_en=datetime.now(UTC).isoformat(),
        ))
        return True

    def listar_pendientes(self) -> list[dict[str, str | int]]:
        rows = (
            self.session.query(NotificacionOutboxRow)
            .filter(NotificacionOutboxRow.estado == "PENDIENTE")
            .order_by(NotificacionOutboxRow.id)
            .all()
        )
        return [{
            "id": row.id,
            "destinatario_id": row.destinatario_id,
            "asunto": row.asunto,
            "mensaje": row.mensaje,
            "estado": row.estado,
            "creado_en": row.creado_en,
        } for row in rows]
