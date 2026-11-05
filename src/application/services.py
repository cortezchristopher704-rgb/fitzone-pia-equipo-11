"""Servicios de Aplicación y Casos de Uso (Service Layer + CQRS) de FitZone."""

from datetime import date
from typing import Any

from src.application.ports import (
    CatalogoRepositoryPort,
    ClaseProgramadaRepositoryPort,
    NotificadorPort,
    OperacionRepositoryPort,
    PasarelaPagoPort,
    SocioRepositoryPort,
    TorniquetePort,
    UnitOfWorkPort,
)
from src.domain.exceptions import (
    CancelacionTardiaError,
    RecursoNoDisponibleError,
)
from src.domain.models import (
    OperacionMembresia,
    ServicioDeInscripcionExtraordinaria,
)


class MembresiaAppService:
    """Coordina la contratación, evaluación de Specifications y transiciones de OperacionMembresia."""

    def __init__(
        self,
        operacion_repo: OperacionRepositoryPort,
        socio_repo: SocioRepositoryPort,
        catalogo_repo: CatalogoRepositoryPort,
        uow: UnitOfWorkPort,
        notificador: NotificadorPort | None = None,
    ) -> None:
        self.operacion_repo = operacion_repo
        self.socio_repo = socio_repo
        self.catalogo_repo = catalogo_repo
        self.uow = uow
        self.notificador = notificador

    def evaluar_operacion(self, operacion_id: str) -> dict[str, Any]:
        """Evalúa precondiciones y beneficio preferente sobre una operación existente."""
        op = self.operacion_repo.get_by_id(operacion_id)
        if op is None:
            raise RecursoNoDisponibleError(f"Operación {operacion_id} no encontrada")

        return {
            "operacion_id": op.operacion_id,
            "actor_id": op.socio.actor_id,
            "estado": op.estado.value,
            "puede_procesarse": op.puede_procesarse(),
            "beneficio_preferente": op.tiene_beneficio_preferente(),
            "tasa_descuento": str(op.tasa_descuento),
            "total_bruto": str(op.total_bruto.amount),
            "monto_descuento": str(op.monto_descuento.amount),
            "total_neto": str(op.total_neto.amount),
            "unidades": op.total_unidades,
        }

    def aprobar_operacion(self, operacion_id: str) -> OperacionMembresia:
        """Aprueba una operación (SOLICITADA -> ACTIVA) dentro de un límite transaccional UoW."""
        op = self.operacion_repo.get_by_id(operacion_id)
        if op is None:
            raise RecursoNoDisponibleError(f"Operación {operacion_id} no encontrada")
        try:
            op.aprobar()
            self.operacion_repo.save(op)
            self.uow.commit()
            if self.notificador:
                self.notificador.enviar_notificacion(
                    op.socio.actor_id,
                    "Membresía Activada",
                    f"Su operación {op.operacion_id} ha sido activada con total {op.total_neto.amount} MXN.",
                )
            return op
        except Exception:
            self.uow.rollback()
            raise

    def suspender_operacion(self, operacion_id: str, motivo: str = "Suspensión administrativa") -> OperacionMembresia:
        op = self.operacion_repo.get_by_id(operacion_id)
        if op is None:
            raise RecursoNoDisponibleError(f"Operación {operacion_id} no encontrada")
        try:
            op.suspender(motivo)
            self.operacion_repo.save(op)
            self.uow.commit()
            return op
        except Exception:
            self.uow.rollback()
            raise

    def vencer_operacion(
        self,
        operacion_id: str,
        clase_repo: ClaseProgramadaRepositoryPort | None = None,
    ) -> OperacionMembresia:
        """Transita a VENCIDA y, conforme a US-018, cancela reservas activas del socio."""
        op = self.operacion_repo.get_by_id(operacion_id)
        if op is None:
            raise RecursoNoDisponibleError(f"Operación {operacion_id} no encontrada")
        try:
            op.vencer()
            op.socio.activo = False
            self.socio_repo.save(op.socio)
            self.operacion_repo.save(op)

            if clase_repo is not None:
                for clase in clase_repo.list_all():
                    promovido_id = clase.cancelar_por_vencimiento_membresia(op.socio)
                    if promovido_id:
                        promovido = self.socio_repo.get_by_id(promovido_id)
                        if promovido:
                            promovido.reservas_activas_count += 1
                            self.socio_repo.save(promovido)
                        if self.notificador:
                            self.notificador.enviar_notificacion(promovido_id, "Lugar liberado por vencimiento",
                                f"Tienes {clase.ventana_confirmacion_minutos} minutos para confirmar la clase {clase.disciplina}.")
                    clase_repo.save(clase)

            self.uow.commit()
            return op
        except Exception:
            self.uow.rollback()
            raise

    def cancelar_operacion(self, operacion_id: str, motivo: str = "Cancelación solicitada") -> OperacionMembresia:
        op = self.operacion_repo.get_by_id(operacion_id)
        if op is None:
            raise RecursoNoDisponibleError(f"Operación {operacion_id} no encontrada")
        try:
            op.cancelar(motivo)
            self.operacion_repo.save(op)
            self.uow.commit()
            return op
        except Exception:
            self.uow.rollback()
            raise


class ReservaAppService:
    """Coordina los casos de uso CU-01 (Reservar), CU-02 (Lista de espera), CU-03 (Cancelar) y Drop-in."""

    def __init__(
        self,
        socio_repo: SocioRepositoryPort,
        clase_repo: ClaseProgramadaRepositoryPort,
        uow: UnitOfWorkPort,
        notificador: NotificadorPort | None = None,
        pasarela_pago: PasarelaPagoPort | None = None,
    ) -> None:
        self.socio_repo = socio_repo
        self.clase_repo = clase_repo
        self.uow = uow
        self.notificador = notificador
        self.pasarela_pago = pasarela_pago
        self.drop_in_service = ServicioDeInscripcionExtraordinaria()

    def reservar_clase(
        self, socio_id: str, clase_id: str, es_drop_in: bool = False
    ) -> dict[str, Any]:
        socio = self.socio_repo.get_by_id(socio_id)
        if socio is None:
            raise RecursoNoDisponibleError(f"Socio {socio_id} no encontrado")
        clase = self.clase_repo.get_by_id(clase_id)
        if clase is None:
            raise RecursoNoDisponibleError(f"Clase {clase_id} no encontrada")

        try:
            if es_drop_in:
                # No se simula un pago exitoso cuando no existe pasarela configurada.
                pago_ok = False
                if self.pasarela_pago is not None:
                    pago_ok = self.pasarela_pago.cobrar(
                        f"DROPIN-{socio_id}-{clase_id}",
                        self.drop_in_service.tarifa_unica.amount,
                    )
                resultado = self.drop_in_service.inscribir_drop_in(socio, clase, pago_ok)
            else:
                resultado = clase.reservar(socio)

            self.socio_repo.save(socio)
            self.clase_repo.save(clase)
            if self.notificador:
                self.notificador.enviar_notificacion(
                    socio.actor_id,
                    f"Estado de Reserva: {resultado}",
                    f"Su solicitud en la clase {clase.disciplina} quedó en estado {resultado}.",
                )
            self.uow.commit()
            return {
                "socio_id": socio.actor_id,
                "clase_id": clase.clase_id,
                "resultado": resultado,
                "cupos_disponibles": clase.cupos_disponibles,
                "en_lista_espera": len(clase.lista_espera),
            }
        except Exception:
            self.uow.rollback()
            raise

    def cancelar_reserva(
        self, socio_id: str, clase_id: str, horas_anticipacion: float = 4.0
    ) -> dict[str, Any]:
        socio = self.socio_repo.get_by_id(socio_id)
        if socio is None:
            raise RecursoNoDisponibleError(f"Socio {socio_id} no encontrado")
        clase = self.clase_repo.get_by_id(clase_id)
        if clase is None:
            raise RecursoNoDisponibleError(f"Clase {clase_id} no encontrada")

        try:
            res = clase.cancelar_reserva(socio, horas_anticipacion)
            promovido_id = res.get("socio_promovido")
            if promovido_id:
                socio_promovido = self.socio_repo.get_by_id(promovido_id)
                if socio_promovido:
                    socio_promovido.reservas_activas_count += 1
                    self.socio_repo.save(socio_promovido)
                if self.notificador:
                    self.notificador.enviar_notificacion(
                        promovido_id,
                        "Lugar Liberado en Clase",
                        f"Has sido promovido en la clase {clase.disciplina}. Tienes 30 minutos para confirmar.",
                    )

            self.socio_repo.save(socio)
            self.clase_repo.save(clase)
            self.uow.commit()
            return {
                "socio_id": socio.actor_id,
                "clase_id": clase.clase_id,
                "estado": res["estado"],
                "socio_promovido": promovido_id,
                "cupos_disponibles": clase.cupos_disponibles,
            }
        except CancelacionTardiaError:
            # La cancelación tardía y la sanción son hechos de negocio que deben persistirse.
            promovido_id = clase.promocion_pendiente_socio_id
            if promovido_id:
                promovido = self.socio_repo.get_by_id(promovido_id)
                if promovido:
                    promovido.reservas_activas_count += 1
                    self.socio_repo.save(promovido)
                if self.notificador:
                    self.notificador.enviar_notificacion(promovido_id, "Lugar liberado",
                        f"Tienes {clase.ventana_confirmacion_minutos} minutos para confirmar la clase {clase.disciplina}.")
            self.socio_repo.save(socio)
            self.clase_repo.save(clase)
            self.uow.commit()
            raise
        except Exception:
            self.uow.rollback()
            raise


class AsistenciaAppService:
    """Coordina CU-05: registro de asistencia, conteo de no-shows y bloqueo de 7 días."""

    def __init__(
        self,
        socio_repo: SocioRepositoryPort,
        clase_repo: ClaseProgramadaRepositoryPort,
        uow: UnitOfWorkPort,
        notificador: NotificadorPort | None = None,
    ) -> None:
        self.socio_repo = socio_repo
        self.clase_repo = clase_repo
        self.uow = uow
        self.notificador = notificador

    def registrar_asistencia(self, socio_id: str, clase_id: str) -> dict[str, Any]:
        socio = self.socio_repo.get_by_id(socio_id)
        clase = self.clase_repo.get_by_id(clase_id)
        if socio is None or clase is None:
            raise RecursoNoDisponibleError("Socio o clase no encontrados")
        try:
            clase.registrar_asistencia(socio)
            self.socio_repo.save(socio)
            self.clase_repo.save(clase)
            self.uow.commit()
            return {"socio_id": socio_id, "clase_id": clase_id, "estado": "ASISTIDA", "no_shows_mes": socio.no_shows_mes}
        except Exception:
            self.uow.rollback()
            raise

    def registrar_no_show(self, socio_id: str, clase_id: str) -> dict[str, Any]:
        socio = self.socio_repo.get_by_id(socio_id)
        if socio is None:
            raise RecursoNoDisponibleError(f"Socio {socio_id} no encontrado")
        clase = self.clase_repo.get_by_id(clase_id)
        if clase is None:
            raise RecursoNoDisponibleError(f"Clase {clase_id} no encontrada")

        try:
            bloqueado = clase.registrar_no_show(socio)
            self.socio_repo.save(socio)
            self.clase_repo.save(clase)
            self.uow.commit()
            if bloqueado and self.notificador:
                self.notificador.enviar_notificacion(
                    socio.actor_id,
                    "Bloqueo Disciplinario de Reservas (7 días)",
                    "Acumuló 3 no-shows en el mes. Sus reservas están bloqueadas por 7 días; su acceso físico al gimnasio sigue permitido.",
                )
            return {
                "socio_id": socio.actor_id,
                "no_shows_mes": socio.no_shows_mes,
                "bloqueado_reservas": socio.bloqueado_reservas,
                "dias_bloqueo": socio.dias_bloqueo_restantes,
            }
        except Exception:
            self.uow.rollback()
            raise


class ControlAccesoAppService:
    """Coordina CU-04 (US-006, US-007): validación automática de ingreso físico en torniquete."""

    def __init__(
        self,
        socio_repo: SocioRepositoryPort,
        torniquete: TorniquetePort | None = None,
    ) -> None:
        self.socio_repo = socio_repo
        self.torniquete = torniquete

    def validar_ingreso(
        self, socio_id: str, fecha_actual: date | None = None
    ) -> dict[str, Any]:
        socio = self.socio_repo.get_by_id(socio_id)
        if socio is None:
            raise RecursoNoDisponibleError(f"Socio {socio_id} no encontrado")

        resultado = socio.verificar_acceso_fisico(fecha_actual)
        barrera_abierta = False
        if resultado["permitido"] and self.torniquete is not None:
            barrera_abierta = self.torniquete.abrir_barrera(socio.actor_id)

        return {
            "socio_id": socio.actor_id,
            "nombre": socio.nombre,
            "permitido": resultado["permitido"],
            "motivo": resultado["motivo"],
            "barrera_abierta": barrera_abierta,
        }


class ReportesQueryService:
    """Servicio de Consultas (CQRS Query) para reportes de ocupación, demanda y no-shows (N5)."""

    def __init__(
        self,
        socio_repo: SocioRepositoryPort,
        clase_repo: ClaseProgramadaRepositoryPort,
        operacion_repo: OperacionRepositoryPort,
    ) -> None:
        self.socio_repo = socio_repo
        self.clase_repo = clase_repo
        self.operacion_repo = operacion_repo

    def reporte_ocupacion_clases(self) -> list[dict[str, Any]]:
        clases = self.clase_repo.list_all()
        return [
            {
                "clase_id": c.clase_id,
                "disciplina": c.disciplina,
                "horario": c.horario,
                "instructor_id": c.instructor_id,
                "capacidad_maxima": c.capacidad_maxima,
                "reservas_confirmadas": len(c.reservas_confirmadas_ids),
                "cupos_disponibles": c.cupos_disponibles,
                "en_lista_espera": len(c.lista_espera),
                "porcentaje_ocupacion": c.porcentaje_ocupacion,
                "cancelada": c.cancelada,
            }
            for c in clases
        ]

    def reporte_no_shows_socios(self) -> list[dict[str, Any]]:
        socios = self.socio_repo.list_all()
        clases = self.clase_repo.list_all()
        reporte = []
        for socio in socios:
            no_shows = 0
            asistencias = 0
            for clase in clases:
                reserva = clase.reservas.get(socio.actor_id)
                if reserva is None:
                    continue
                if reserva.estado.value == "NO_SHOW":
                    no_shows += 1
                elif reserva.estado.value == "ASISTIDA":
                    asistencias += 1
            total_registros = no_shows + asistencias
            tasa = round((no_shows / total_registros) * 100, 2) if total_registros else 0.0
            reporte.append({
                "actor_id": socio.actor_id,
                "nombre": socio.nombre,
                "activo": socio.activo,
                "es_preferente": socio.es_preferente,
                "no_shows_mes": socio.no_shows_mes,
                "no_shows_historicos": no_shows,
                "asistencias_historicas": asistencias,
                "reservas_con_resultado": total_registros,
                "tasa_no_show_porcentaje": tasa,
                "bloqueado_reservas": socio.bloqueado_reservas,
                "dias_bloqueo_restantes": socio.dias_bloqueo_restantes,
            })
        return reporte
