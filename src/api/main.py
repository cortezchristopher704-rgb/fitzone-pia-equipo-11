"""API REST FastAPI para el Sistema Integral FitZone (Caso 11 PIA).
Expone endpoints para Operaciones de Membresía, Reservación de Clases, Lista de Espera FIFO,
Control de Acceso en Torniquete, Asistencia/No-Shows y Reportes Analíticos CQRS.
"""

import base64
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time as time_type, timedelta
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.application.services import (
    AsistenciaAppService,
    ControlAccesoAppService,
    MembresiaAppService,
    ReportesQueryService,
    ReservaAppService,
)
from src.domain.exceptions import (
    CancelacionTardiaError,
    ClaseSinCupoError,
    DatosInvalidosError,
    FitZoneDomainError,
    LimiteReservasPlanError,
    MembresiaInactivaError,
    PrecondicionOperacionError,
    RecursoNoDisponibleError,
    ReservaDuplicadaError,
    ReservaNoEncontradaError,
    SocioBloqueadoError,
    TransicionEstadoInvalidaError,
)
from src.domain.models import ClaseProgramada, OperacionMembresia
from src.domain.value_objects import Vigencia
from src.infrastructure.csv_loader import (
    evaluar_casos_prueba_csv,
    evaluar_transiciones_csv,
    poblar_base_de_datos,
)
from src.infrastructure.database import make_engine, make_session
from src.infrastructure.repositories import (
    SqlAlchemyUnitOfWork,
    SqlCatalogoRepository,
    SqlClaseProgramadaRepository,
    SqlOperacionRepository,
    SqlSocioRepository,
    SqlOutboxNotificador,
)

# Motor global reutilizable
_ENGINE = make_engine()


def get_db_session():
    session = make_session(_ENGINE)
    try:
        yield session
    finally:
        session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    session = make_session(_ENGINE)
    try:
        socios_actuales = SqlSocioRepository(session).list_all()
        if not socios_actuales:
            poblar_base_de_datos(session)
    finally:
        session.close()
    try:
        yield
    finally:
        # Libera conexiones al apagar la aplicación y evita conexiones SQLite huérfanas.
        _ENGINE.dispose()


app = FastAPI(
    title="FitZone — API de Lógica de Negocio (PIA Equipo 11)",
    description=(
        "Solución integral de software basada en Domain-Driven Design (DDD), Specification Pattern, "
        "State Machine, Unit of Work y CQRS para FitZone (Caso 11)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ==============================================================================
# DTOs / ESQUEMAS PYDANTIC DE ENTRADA Y SALIDA
# ==============================================================================


class LoginRequestDTO(BaseModel):
    usuario: str = Field(..., min_length=1, max_length=80)
    contrasena: str = Field(..., min_length=1, max_length=200)


class LineaOperacionRequestDTO(BaseModel):
    recurso_id: str = Field(..., min_length=1, max_length=80)
    cantidad: int = Field(..., gt=0, le=100)


class CrearOperacionRequestDTO(BaseModel):
    operacion_id: str = Field(..., min_length=1, max_length=80)
    socio_id: str = Field(..., min_length=1, max_length=80)
    lineas: list[LineaOperacionRequestDTO] = Field(..., min_length=1, max_length=20)
    promocion_activa: bool = False


class ReservaRequestDTO(BaseModel):
    socio_id: str = Field(..., examples=["FIT-C001"], description="ID del socio solicitante")
    es_drop_in: bool = Field(False, description="Indica si es inscripción extraordinaria Drop-in (US-019)")


class CancelarReservaRequestDTO(BaseModel):
    horas_anticipacion: float = Field(
        4.0, examples=[4.0], description="Campo legacy ignorado; la API calcula la anticipación con el horario persistido de la clase."
    )


class CrearClaseRequestDTO(BaseModel):
    clase_id: str = Field(..., examples=["CLASE-04"])
    disciplina: str = Field(..., examples=["Box Funcional"])
    horario: str = Field(..., examples=["2026-11-06 09:00"])
    capacidad_maxima: int = Field(..., examples=[15])
    instructor_id: str = Field("INST-01", examples=["INST-01"])


class MotivoRequestDTO(BaseModel):
    motivo: str = Field("Solicitud administrativa", examples=["Fin de vigencia / Ajuste"])


class CancelarInstructorDTO(BaseModel):
    horas_anticipacion: float = Field(2.5, examples=[2.5], description="Campo legacy ignorado; la API calcula la anticipación con el horario persistido de la clase.")
    motivo: str = Field("Fuerza mayor del instructor", examples=["Incapacidad médica"])


class ReasignarInstructorDTO(BaseModel):
    nuevo_instructor_id: str = Field(..., examples=["INST-SUPLENTE-09"])


class ReservaRecepcionDTO(BaseModel):
    socio_id: str = Field(..., examples=["FIT-C001"])
    empleado_id: str = Field(..., examples=["REC-01"])


class ActualizarCapacidadDTO(BaseModel):
    capacidad_maxima: int = Field(..., gt=0, examples=[20])


class ActualizarPlanesIncluidosDTO(BaseModel):
    planes_incluidos: list[str] = Field(..., max_length=20, examples=[["BASICO", "PREMIUM"]])


class AlertasVencimientoDTO(BaseModel):
    dias_anticipacion: int = Field(7, ge=0, le=365, examples=[7])


class ActualizarVigenciaDTO(BaseModel):
    fecha_inicio: date = Field(..., examples=["2026-11-01"])
    fecha_fin: date = Field(..., examples=["2026-11-30"])



def _calcular_horas_hasta_clase(horario: str, ahora: datetime | None = None) -> float:
    """Calcula anticipación desde el horario persistido; nunca confía en el cliente."""
    ahora = ahora or datetime.now()
    try:
        inicio = datetime.fromisoformat(horario)
    except ValueError:
        try:
            hora = time_type.fromisoformat(horario)
        except ValueError as exc:
            raise DatosInvalidosError(
                f"Horario de clase inválido para calcular anticipación: {horario}"
            ) from exc
        inicio = datetime.combine(ahora.date(), hora)
        if inicio <= ahora:
            inicio += timedelta(days=1)
    if inicio.tzinfo is not None and ahora.tzinfo is None:
        ahora = datetime.now(inicio.tzinfo)
    elif inicio.tzinfo is None and ahora.tzinfo is not None:
        inicio = inicio.replace(tzinfo=ahora.tzinfo)
    return (inicio - ahora).total_seconds() / 3600.0


def _mismo_inicio_horario(horario_a: str, horario_b: str) -> bool:
    """Compara inicios exactos; no infiere duración porque el caso no la especifica."""
    try:
        a_dt = datetime.fromisoformat(horario_a)
    except ValueError:
        a_dt = None
    try:
        b_dt = datetime.fromisoformat(horario_b)
    except ValueError:
        b_dt = None
    if a_dt is not None and b_dt is not None:
        return a_dt == b_dt
    if a_dt is None and b_dt is None:
        try:
            return time_type.fromisoformat(horario_a) == time_type.fromisoformat(horario_b)
        except ValueError:
            return False
    return False


def _codificar_token_sesion(payload: dict[str, Any]) -> str:
    secreto = os.getenv("FITZONE_SESSION_SECRET", "")
    if not secreto:
        raise HTTPException(status_code=503, detail="El inicio de sesión no está configurado.")
    contenido = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    firma = hmac.new(secreto.encode(), contenido.encode(), hashlib.sha256).hexdigest()
    return f"{contenido}.{firma}"


def _leer_token_sesion(token: str) -> dict[str, Any]:
    secreto = os.getenv("FITZONE_SESSION_SECRET", "")
    try:
        contenido, firma = token.split(".", 1)
        esperada = hmac.new(secreto.encode(), contenido.encode(), hashlib.sha256).hexdigest()
        if not secreto or not hmac.compare_digest(firma, esperada):
            raise ValueError("firma")
        payload = json.loads(base64.urlsafe_b64decode(contenido + "=" * (-len(contenido) % 4)))
        if int(payload.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
            raise ValueError("expirado")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Tu sesión no es válida o ha expirado. Inicia sesión nuevamente.")


def requerir_rol_staff(rol_esperado: str):
    """Valida una sesión firmada; conserva headers internos para compatibilidad de pruebas/API."""
    def dependencia(
        authorization: str | None = Header(None, alias="Authorization"),
        x_staff_role: str | None = Header(None, alias="X-Staff-Role"),
        x_staff_token: str | None = Header(None, alias="X-Staff-Token"),
        x_staff_id: str | None = Header(None, alias="X-Staff-Id"),
    ) -> str:
        if authorization and authorization.startswith("Bearer "):
            payload = _leer_token_sesion(authorization[7:].strip())
            if payload.get("rol") != rol_esperado:
                raise HTTPException(status_code=403, detail="Tu cuenta no tiene permisos para realizar esta operación.")
            return str(payload.get("id", ""))
        token_configurado = os.getenv(f"FITZONE_STAFF_TOKEN_{rol_esperado}")
        if not all((x_staff_role, x_staff_token, x_staff_id)):
            raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
        if not token_configurado:
            raise HTTPException(status_code=503, detail="El acceso del personal no está configurado.")
        if x_staff_role.strip().upper() != rol_esperado or not hmac.compare_digest(x_staff_token, token_configurado):
            raise HTTPException(status_code=403, detail="No se pudo validar tu acceso.")
        return x_staff_id.strip()
    return dependencia

def _mensaje_error_dominio(exc: FitZoneDomainError) -> str:
    """Convierte errores internos del dominio en mensajes claros para quien usa la API."""
    mensajes = (
        (ClaseSinCupoError, "Esta clase ya no tiene lugares disponibles."),
        (SocioBloqueadoError, "No es posible realizar la reserva porque la cuenta tiene una restricción por inasistencias."),
        (LimiteReservasPlanError, "Alcanzaste el máximo de reservas permitidas por tu plan."),
        (ReservaDuplicadaError, "Ya existe una reserva para esta clase con ese socio."),
        (ReservaNoEncontradaError, "No encontramos una reserva para realizar esta operación."),
        (CancelacionTardiaError, "Ya pasó el límite de tiempo permitido para cancelar esta reserva."),
        (MembresiaInactivaError, None),
        (RecursoNoDisponibleError, "El plan o la clase solicitada no está disponible."),
        (TransicionEstadoInvalidaError, "La operación no puede realizarse porque el estado actual no lo permite."),
        (PrecondicionOperacionError, "No se cumplen los requisitos para realizar esta operación."),
        (DatosInvalidosError, "Los datos proporcionados no son válidos. Revisa la información e inténtalo de nuevo."),
    )
    for tipo_error, mensaje in mensajes:
        if isinstance(exc, tipo_error):
            return str(exc) if mensaje is None else mensaje
    return "No fue posible completar la operación. Verifica los datos e inténtalo de nuevo."


def _traducir_error_dominio(exc: FitZoneDomainError) -> HTTPException:
    """Traduce errores del dominio a códigos HTTP y mensajes comprensibles."""
    mensaje = _mensaje_error_dominio(exc)
    if isinstance(exc, RecursoNoDisponibleError):
        codigo = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, (
        TransicionEstadoInvalidaError, ReservaDuplicadaError, ClaseSinCupoError,
        SocioBloqueadoError, LimiteReservasPlanError,
    )):
        codigo = status.HTTP_409_CONFLICT
    elif isinstance(exc, (
        DatosInvalidosError, PrecondicionOperacionError, MembresiaInactivaError,
        CancelacionTardiaError, ReservaNoEncontradaError,
    )):
        codigo = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        codigo = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=codigo, detail=mensaje)


@app.post("/api/v1/auth/login", tags=["Autenticación"])
def iniciar_sesion(dto: LoginRequestDTO) -> dict[str, Any]:
    """Autentica cuentas de demostración y emite una sesión firmada con duración limitada."""
    cuentas = (
        ("ADMIN", "ADMIN-01", "FITZONE_DEMO_ADMIN_USER", "FITZONE_DEMO_ADMIN_PASSWORD", "Administrador"),
        ("RECEPCION", "REC-01", "FITZONE_DEMO_RECEPCION_USER", "FITZONE_DEMO_RECEPCION_PASSWORD", "Recepción"),
        ("INSTRUCTOR", "INST-01", "FITZONE_DEMO_INSTRUCTOR_USER", "FITZONE_DEMO_INSTRUCTOR_PASSWORD", "Instructor"),
    )
    for rol, identificador, usuario_env, password_env, nombre_rol in cuentas:
        usuario = os.getenv(usuario_env, "")
        contrasena = os.getenv(password_env, "")
        if usuario and contrasena and hmac.compare_digest(dto.usuario, usuario) and hmac.compare_digest(dto.contrasena, contrasena):
            expira = int(datetime.now(UTC).timestamp()) + 8 * 60 * 60
            token = _codificar_token_sesion({"rol": rol, "id": identificador, "exp": expira})
            return {"access_token": token, "token_type": "bearer", "rol": rol, "id": identificador,
                    "nombre": nombre_rol, "expires_in": 28800}
    raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")


@app.get("/api/v1/auth/me", tags=["Autenticación"])
def consultar_sesion(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
    payload = _leer_token_sesion(authorization[7:].strip())
    return {"rol": payload["rol"], "id": payload["id"], "exp": payload["exp"]}


# ==============================================================================
# ENDPOINTS DE SALUD Y SEMILLA DE DATOS
# ==============================================================================


@app.get("/health", tags=["Sistema"])
def health_check() -> dict[str, str]:
    """Verifica el estado operativo de la API y conexión a datos."""
    return {"status": "ok", "service": "FitZone PIA API", "equipo": "Equipo 11"}


@app.post("/api/v1/seed", status_code=status.HTTP_201_CREATED, tags=["Sistema"])
def seed_database(session: Session = Depends(get_db_session)) -> dict[str, Any]:
    """Recarga los 40 socios, 20 planes, 60 operaciones y clases base desde los CSV oficiales."""
    resumen = poblar_base_de_datos(session)
    return {"mensaje": "Base de datos poblada exitosamente desde CSVs oficiales", "resumen": resumen}


# ==============================================================================
# ENDPOINTS DE SOCIOS, CATÁLOGO Y CONTROL DE ACCESO (N1 / CU-04)
# ==============================================================================


@app.get("/api/v1/socios", tags=["Socios y Accesos"])
def listar_socios(session: Session = Depends(get_db_session)) -> list[dict[str, Any]]:
    repo = SqlSocioRepository(session)
    return [
        {
            "actor_id": s.actor_id,
            "nombre": s.nombre,
            "es_preferente": s.es_preferente,
            "activo": s.activo,
            "ciudad": s.ciudad,
            "tipo_plan": s.tipo_plan,
            "no_shows_mes": s.no_shows_mes,
            "bloqueado_reservas": s.bloqueado_reservas,
            "reservas_activas_count": s.reservas_activas_count,
            "vigencia_inicio": s.vigencia.fecha_inicio.isoformat() if s.vigencia else None,
            "vigencia_fin": s.vigencia.fecha_fin.isoformat() if s.vigencia else None,
        }
        for s in repo.list_all()
    ]


@app.get("/api/v1/socios/{actor_id}", tags=["Socios y Accesos"])
def obtener_socio(actor_id: str, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    repo = SqlSocioRepository(session)
    s = repo.get_by_id(actor_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"No encontramos un socio con el número {actor_id}.")
    return {
        "actor_id": s.actor_id,
        "nombre": s.nombre,
        "es_preferente": s.es_preferente,
        "activo": s.activo,
        "ciudad": s.ciudad,
        "tipo_plan": s.tipo_plan,
        "no_shows_mes": s.no_shows_mes,
        "bloqueado_reservas": s.bloqueado_reservas,
        "dias_bloqueo_restantes": s.dias_bloqueo_restantes,
        "reservas_activas_count": s.reservas_activas_count,
        "vigencia_inicio": s.vigencia.fecha_inicio.isoformat() if s.vigencia else None,
        "vigencia_fin": s.vigencia.fecha_fin.isoformat() if s.vigencia else None,
    }


@app.put("/api/v1/socios/{actor_id}/vigencia", tags=["Socios y Accesos"])
def actualizar_vigencia_socio(
    actor_id: str, dto: ActualizarVigenciaDTO, session: Session = Depends(get_db_session),
    _administrador_autenticado: str = Depends(requerir_rol_staff("ADMIN")),
) -> dict[str, Any]:
    """Registra el periodo real de membresía; el CSV oficial no proporciona estas fechas."""
    socio_repo = SqlSocioRepository(session)
    socio = socio_repo.get_by_id(actor_id)
    if socio is None:
        raise HTTPException(status_code=404, detail=f"No encontramos un socio con el número {actor_id}.")
    try:
        socio.vigencia = Vigencia(dto.fecha_inicio, dto.fecha_fin)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)
    socio_repo.save(socio)
    SqlAlchemyUnitOfWork(session).commit()
    return {"socio_id": actor_id, "fecha_inicio": dto.fecha_inicio.isoformat(),
            "fecha_fin": dto.fecha_fin.isoformat(), "registrada": True}


@app.post("/api/v1/socios/vigencias-demo", tags=["Socios y Accesos"])
def asignar_vigencias_demo(
    session: Session = Depends(get_db_session),
    _administrador_autenticado: str = Depends(requerir_rol_staff("ADMIN")),
) -> dict[str, Any]:
    """Asigna 30 días de vigencia únicamente a socios sin fechas registradas."""
    from datetime import timedelta
    repo = SqlSocioRepository(session)
    socios = repo.list_all()
    inicio = date.today()
    fin = inicio + timedelta(days=30)
    actualizados = []
    for socio in socios:
        if socio.vigencia is None:
            socio.vigencia = Vigencia(inicio, fin)
            repo.save(socio)
            actualizados.append(socio.actor_id)
    SqlAlchemyUnitOfWork(session).commit()
    return {"actualizados": len(actualizados), "omitidos": len(socios)-len(actualizados), "socios_actualizados": actualizados, "fecha_inicio": inicio.isoformat(), "fecha_fin": fin.isoformat()}


@app.post("/api/v1/socios/{actor_id}/acceso", tags=["Socios y Accesos"])
def validar_acceso_torniquete(
    actor_id: str, session: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """CU-04 (US-006, US-007): Valida ingreso físico en recepción según vigencia de membresía."""
    service = ControlAccesoAppService(SqlSocioRepository(session))
    try:
        return service.validar_ingreso(actor_id)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.get("/api/v1/catalogo", tags=["Catálogo de Planes"])
def listar_catalogo(session: Session = Depends(get_db_session)) -> list[dict[str, Any]]:
    repo = SqlCatalogoRepository(session)
    return [
        {
            "recurso_id": p.recurso_id,
            "descripcion": p.descripcion,
            "precio_mxn": str(p.precio_mxn.amount),
            "capacidad_o_stock": p.capacidad_o_stock,
            "habilitado": p.habilitado,
        }
        for p in repo.list_all()
    ]


# ==============================================================================
# ENDPOINTS DE OPERACIONES DE MEMBRESÍA, SPECIFICATIONS Y STATE MACHINE
# ==============================================================================


def _serializar_operacion(op) -> dict[str, Any]:
    return {
        "operacion_id": op.operacion_id,
        "actor_id": op.socio.actor_id,
        "socio_activo": op.socio.activo,
        "socio_preferente": op.socio.es_preferente,
        "estado": op.estado.value,
        "fecha_solicitud": op.fecha_solicitud,
        "promocion_activa": op.promocion_activa,
        "autorizado": op.autorizado,
        "referencia": op.referencia,
        "unidades": op.total_unidades,
        "total_bruto": str(op.total_bruto.amount),
        "tiene_beneficio_preferente": op.tiene_beneficio_preferente(),
        "tasa_descuento": str(op.tasa_descuento),
        "monto_descuento": str(op.monto_descuento.amount),
        "total_neto": str(op.total_neto.amount),
        "puede_procesarse": op.puede_procesarse(),
        "lineas": [
            {
                "recurso_id": l.recurso_id,
                "descripcion": l.descripcion,
                "cantidad": l.cantidad,
                "precio_unitario": str(l.precio_unitario.amount),
                "subtotal": str(l.subtotal.amount),
                "recurso_habilitado": l.recurso_habilitado,
            }
            for l in op.lineas
        ],
        "eventos": [
            {"nombre": e.nombre, "detalles": e.detalles} for e in op.eventos
        ],
    }


@app.post("/api/v1/operaciones", status_code=status.HTTP_201_CREATED, tags=["Operaciones y Membresías"])
def crear_solicitud_operacion(
    dto: CrearOperacionRequestDTO,
    session: Session = Depends(get_db_session),
    empleado_autenticado: str = Depends(requerir_rol_staff("RECEPCION")),
) -> dict[str, Any]:
    """US-008: recepción registra una solicitud de contratación para un socio."""
    socios = SqlSocioRepository(session)
    catalogo = SqlCatalogoRepository(session)
    operaciones = SqlOperacionRepository(session, socios)
    if operaciones.get_by_id(dto.operacion_id) is not None:
        raise HTTPException(status_code=409, detail="Ya existe una operación con ese identificador.")
    socio = socios.get_by_id(dto.socio_id)
    if socio is None:
        raise HTTPException(status_code=404, detail=f"No encontramos al socio {dto.socio_id}.")
    if not socio.activo:
        raise HTTPException(status_code=422, detail="No se puede registrar una contratación para un socio inactivo.")
    operacion = OperacionMembresia(
        operacion_id=dto.operacion_id,
        socio=socio,
        fecha_solicitud=date.today().isoformat(),
        promocion_activa=dto.promocion_activa,
        autorizado=True,
        referencia=f"Recepción: {empleado_autenticado}",
    )
    for linea in dto.lineas:
        plan = catalogo.get_by_id(linea.recurso_id)
        if plan is None:
            raise HTTPException(status_code=404, detail=f"No encontramos el plan {linea.recurso_id}.")
        if not plan.habilitado:
            raise HTTPException(status_code=422, detail=f"El plan {plan.descripcion} está deshabilitado.")
        if linea.cantidad > plan.capacidad_o_stock:
            raise HTTPException(status_code=422, detail=f"No hay stock suficiente para {plan.descripcion}.")
        operacion.agregar_linea(plan, linea.cantidad)
    if not operacion.puede_procesarse():
        raise HTTPException(status_code=422, detail="La solicitud no cumple las precondiciones de contratación.")
    operaciones.save(operacion)
    SqlAlchemyUnitOfWork(session).commit()
    return {**_serializar_operacion(operacion), "registrada_por": empleado_autenticado, "canal": "RECEPCION"}


@app.get("/api/v1/operaciones", tags=["Operaciones y Membresías"])
def listar_operaciones(session: Session = Depends(get_db_session)) -> list[dict[str, Any]]:
    socio_repo = SqlSocioRepository(session)
    op_repo = SqlOperacionRepository(session, socio_repo)
    return [_serializar_operacion(op) for op in op_repo.list_all()]


@app.get("/api/v1/operaciones/{operacion_id}", tags=["Operaciones y Membresías"])
def obtener_operacion(
    operacion_id: str, session: Session = Depends(get_db_session)
) -> dict[str, Any]:
    socio_repo = SqlSocioRepository(session)
    op_repo = SqlOperacionRepository(session, socio_repo)
    op = op_repo.get_by_id(operacion_id)
    if op is None:
        raise HTTPException(status_code=404, detail=f"Operación {operacion_id} no encontrada")
    return _serializar_operacion(op)


@app.get("/api/v1/operaciones/{operacion_id}/evaluar", tags=["Operaciones y Membresías"])
def evaluar_operacion_specifications(
    operacion_id: str, session: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """Evalúa PUEDE_PROCESARSE_SPEC y BENEFICIO_PREFERENTE_SPEC sobre la operación."""
    socio_repo = SqlSocioRepository(session)
    service = MembresiaAppService(
        SqlOperacionRepository(session, socio_repo),
        socio_repo,
        SqlCatalogoRepository(session),
        SqlAlchemyUnitOfWork(session),
    )
    try:
        return service.evaluar_operacion(operacion_id)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/operaciones/{operacion_id}/aprobar", tags=["Operaciones y Membresías"])
def aprobar_operacion(
    operacion_id: str, session: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """Transición SOLICITADA -> ACTIVA validando Specifications."""
    socio_repo = SqlSocioRepository(session)
    service = MembresiaAppService(
        SqlOperacionRepository(session, socio_repo),
        socio_repo,
        SqlCatalogoRepository(session),
        SqlAlchemyUnitOfWork(session),
    )
    try:
        op = service.aprobar_operacion(operacion_id)
        return _serializar_operacion(op)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/operaciones/{operacion_id}/suspender", tags=["Operaciones y Membresías"])
def suspender_operacion(
    operacion_id: str,
    body: MotivoRequestDTO | None = None,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Transición ACTIVA -> SUSPENDIDA."""
    socio_repo = SqlSocioRepository(session)
    service = MembresiaAppService(
        SqlOperacionRepository(session, socio_repo),
        socio_repo,
        SqlCatalogoRepository(session),
        SqlAlchemyUnitOfWork(session),
    )
    try:
        motivo = body.motivo if body else "Suspensión administrativa"
        op = service.suspender_operacion(operacion_id, motivo)
        return _serializar_operacion(op)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/operaciones/{operacion_id}/vencer", tags=["Operaciones y Membresías"])
def vencer_operacion(
    operacion_id: str, session: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """Transición ACTIVA/SUSPENDIDA -> VENCIDA y cancelación de reservas activas (US-018)."""
    socio_repo = SqlSocioRepository(session)
    clase_repo = SqlClaseProgramadaRepository(session)
    service = MembresiaAppService(
        SqlOperacionRepository(session, socio_repo),
        socio_repo,
        SqlCatalogoRepository(session),
        SqlAlchemyUnitOfWork(session),
    )
    try:
        op = service.vencer_operacion(operacion_id, clase_repo=clase_repo)
        return _serializar_operacion(op)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/operaciones/{operacion_id}/cancelar", tags=["Operaciones y Membresías"])
def cancelar_operacion(
    operacion_id: str,
    body: MotivoRequestDTO | None = None,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Transición SOLICITADA -> CANCELADA."""
    socio_repo = SqlSocioRepository(session)
    service = MembresiaAppService(
        SqlOperacionRepository(session, socio_repo),
        socio_repo,
        SqlCatalogoRepository(session),
        SqlAlchemyUnitOfWork(session),
    )
    try:
        motivo = body.motivo if body else "Cancelación solicitada"
        op = service.cancelar_operacion(operacion_id, motivo)
        return _serializar_operacion(op)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


# ==============================================================================
# ENDPOINTS DE CLASES PROGRAMADAS, RESERVAS, LISTA DE ESPERA FIFO Y NO-SHOWS
# ==============================================================================


@app.get("/api/v1/clases", tags=["Clases y Reservas"])
def listar_clases(session: Session = Depends(get_db_session)) -> list[dict[str, Any]]:
    repo = SqlClaseProgramadaRepository(session)
    return [
        {
            "clase_id": c.clase_id,
            "disciplina": c.disciplina,
            "horario": c.horario,
            "instructor_id": c.instructor_id,
            "capacidad_maxima": c.capacidad_maxima,
            "cupos_disponibles": c.cupos_disponibles,
            "reservas_confirmadas": c.reservas_confirmadas_ids,
            "lista_espera_fifo": c.lista_espera,
            "porcentaje_ocupacion": c.porcentaje_ocupacion,
            "cancelada": c.cancelada,
            "planes_incluidos": sorted(c.planes_incluidos) if c.planes_incluidos is not None else None,
        }
        for c in repo.list_all()
    ]


@app.get("/api/v1/reservas", tags=["Clases y Reservas"])
def listar_reservaciones(session: Session = Depends(get_db_session)) -> list[dict[str, Any]]:
    """Consulta centralizada de reservas, lista de espera y estados por clase."""
    clases = SqlClaseProgramadaRepository(session).list_all()
    socios_repo = SqlSocioRepository(session)
    registros: list[dict[str, Any]] = []
    for clase in clases:
        for socio_id, reserva in clase.reservas.items():
            socio = socios_repo.get_by_id(socio_id)
            registros.append({
                "clase_id": clase.clase_id,
                "disciplina": clase.disciplina,
                "horario": clase.horario,
                "socio_id": socio_id,
                "socio_nombre": socio.nombre if socio else socio_id,
                "estado": reserva.estado.value,
                "modalidad": "DROP-IN" if reserva.es_drop_in else "MEMBRESIA",
            })
        for socio_id in clase.lista_espera:
            if socio_id not in clase.reservas:
                socio = socios_repo.get_by_id(socio_id)
                registros.append({
                    "clase_id": clase.clase_id,
                    "disciplina": clase.disciplina,
                    "horario": clase.horario,
                    "socio_id": socio_id,
                    "socio_nombre": socio.nombre if socio else socio_id,
                    "estado": "LISTA_ESPERA",
                    "modalidad": "MEMBRESIA",
                })
    return sorted(registros, key=lambda r: (r["horario"], r["disciplina"], r["socio_nombre"]))


@app.post(
    "/api/v1/clases",
    status_code=status.HTTP_201_CREATED,
    tags=["Clases y Reservas"],
)
def crear_clase(
    dto: CrearClaseRequestDTO, session: Session = Depends(get_db_session),
    _administrador_autenticado: str = Depends(requerir_rol_staff("ADMIN")),
) -> dict[str, Any]:
    repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)
    try:
        nueva = ClaseProgramada(
            clase_id=dto.clase_id,
            disciplina=dto.disciplina,
            horario=dto.horario,
            capacidad_maxima=dto.capacidad_maxima,
            instructor_id=dto.instructor_id,
        )
        repo.save(nueva)
        uow.commit()
        return {
            "clase_id": nueva.clase_id,
            "disciplina": nueva.disciplina,
            "capacidad_maxima": nueva.capacidad_maxima,
            "cupos_disponibles": nueva.cupos_disponibles,
        }
    except FitZoneDomainError as exc:
        uow.rollback()
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/clases/{clase_id}/reservas/recepcion", tags=["Clases y Reservas"])
def reservar_desde_recepcion(
    clase_id: str, dto: ReservaRecepcionDTO, session: Session = Depends(get_db_session),
    empleado_autenticado: str = Depends(requerir_rol_staff("RECEPCION")),
) -> dict[str, Any]:
    """US-008: permite al personal de recepción registrar una reserva en nombre de un socio."""
    if dto.empleado_id != empleado_autenticado:
        raise HTTPException(status_code=403, detail="El número de empleado no coincide con la cuenta que inició sesión.")
    service = ReservaAppService(
        SqlSocioRepository(session), SqlClaseProgramadaRepository(session), SqlAlchemyUnitOfWork(session)
    )
    try:
        resultado = service.reservar_clase(dto.socio_id, clase_id)
        return {**resultado, "registrada_por": empleado_autenticado, "canal": "RECEPCION"}
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.get("/api/v1/clases/{clase_id}/instructor/{instructor_id}/lista", tags=["Clases y Reservas"])
def consultar_lista_instructor(
    clase_id: str, instructor_id: str, session: Session = Depends(get_db_session),
    instructor_autenticado: str = Depends(requerir_rol_staff("INSTRUCTOR")),
) -> dict[str, Any]:
    """US-009: el instructor consulta socios confirmados, asistidos y en lista de espera."""
    clase = SqlClaseProgramadaRepository(session).get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    if instructor_id != instructor_autenticado:
        raise HTTPException(status_code=403, detail="El número de instructor no coincide con la cuenta que inició sesión.")
    if clase.instructor_id != instructor_autenticado:
        raise HTTPException(status_code=403, detail="No tienes asignada esta clase y no puedes consultar su lista.")
    socios_repo = SqlSocioRepository(session)
    lista = []
    for socio_id, reserva in clase.reservas.items():
        if reserva.estado.value in ("CONFIRMADA", "ASISTIDA"):
            socio = socios_repo.get_by_id(socio_id)
            lista.append({"socio_id": socio_id, "nombre": socio.nombre if socio else None, "estado": reserva.estado.value})
    for socio_id in clase.lista_espera:
        socio = socios_repo.get_by_id(socio_id)
        lista.append({"socio_id": socio_id, "nombre": socio.nombre if socio else None, "estado": "LISTA_ESPERA"})
    return {"clase_id": clase_id, "instructor_id": instructor_id, "total": len(lista), "socios": lista}


@app.patch("/api/v1/clases/{clase_id}/capacidad", tags=["Clases y Reservas"])
def actualizar_capacidad_clase(
    clase_id: str, dto: ActualizarCapacidadDTO, session: Session = Depends(get_db_session),
    _administrador_autenticado: str = Depends(requerir_rol_staff("ADMIN")),
) -> dict[str, Any]:
    """US-012: permite al administrador cambiar la capacidad respetando las reservas activas."""
    repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)
    clase = repo.get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    try:
        clase.actualizar_capacidad(dto.capacidad_maxima)
        repo.save(clase)
        uow.commit()
        return {"clase_id": clase_id, "capacidad_maxima": clase.capacidad_maxima, "cupos_disponibles": clase.cupos_disponibles}
    except FitZoneDomainError as exc:
        uow.rollback()
        raise _traducir_error_dominio(exc)


@app.patch("/api/v1/clases/{clase_id}/planes-incluidos", tags=["Clases y Reservas"])
def actualizar_planes_incluidos_clase(
    clase_id: str, dto: ActualizarPlanesIncluidosDTO, session: Session = Depends(get_db_session),
    _administrador_autenticado: str = Depends(requerir_rol_staff("ADMIN")),
) -> dict[str, Any]:
    """US-013: configura qué tipos de membresía pueden reservar una clase sin Drop-in."""
    repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)
    clase = repo.get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    try:
        clase.actualizar_planes_incluidos(set(dto.planes_incluidos))
        repo.save(clase)
        uow.commit()
        return {"clase_id": clase_id, "planes_incluidos": sorted(clase.planes_incluidos or [])}
    except FitZoneDomainError as exc:
        uow.rollback()
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/reportes/alertas-vencimiento", tags=["Reportes y Analítica CQRS"])
def consultar_alertas_vencimiento(
    dto: AlertasVencimientoDTO, session: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """US-016: consulta socios cuya membresía vence dentro de N días (sin enviar correo externo)."""
    hoy = date.today()
    limite = hoy + timedelta(days=dto.dias_anticipacion)
    socios = SqlSocioRepository(session).list_all()
    alertas = [
        {"socio_id": socio.actor_id, "nombre": socio.nombre, "fecha_vencimiento": socio.vigencia.fecha_fin.isoformat(),
         "dias_restantes": (socio.vigencia.fecha_fin - hoy).days}
        for socio in socios
        if socio.activo and socio.vigencia is not None and hoy <= socio.vigencia.fecha_fin <= limite
    ]
    return {"fecha_consulta": hoy.isoformat(), "dias_anticipacion": dto.dias_anticipacion,
            "total_alertas": len(alertas), "alertas": alertas,
            "nota": "Consulta de alertas; el envío automático de notificaciones requiere un proveedor configurado."}


@app.post("/api/v1/clases/{clase_id}/reservas", tags=["Clases y Reservas"])
def reservar_lugar_en_clase(
    clase_id: str, dto: ReservaRequestDTO, session: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """CU-01 / CU-02 (US-001, US-003, US-019): Reserva cupo o inscribe en Lista de Espera FIFO."""
    service = ReservaAppService(
        SqlSocioRepository(session),
        SqlClaseProgramadaRepository(session),
        SqlAlchemyUnitOfWork(session),
        notificador=SqlOutboxNotificador(session),
    )
    try:
        return service.reservar_clase(dto.socio_id, clase_id, es_drop_in=dto.es_drop_in)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/clases/{clase_id}/cancelar-reserva/{socio_id}", tags=["Clases y Reservas"])
def cancelar_reserva_en_clase(
    clase_id: str,
    socio_id: str,
    dto: CancelarReservaRequestDTO | None = None,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """CU-03 (US-004, US-005): Cancela reserva validando cut-off de 3h y promoviendo en FIFO."""
    clase = SqlClaseProgramadaRepository(session).get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    try:
        horas_reales = _calcular_horas_hasta_clase(clase.horario)
        service = ReservaAppService(
            SqlSocioRepository(session),
            SqlClaseProgramadaRepository(session),
            SqlAlchemyUnitOfWork(session),
            notificador=SqlOutboxNotificador(session),
        )
        # El campo legacy dto.horas_anticipacion se ignora: la regla usa horario persistido.
        return service.cancelar_reserva(socio_id, clase_id, horas_anticipacion=horas_reales)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/clases/{clase_id}/asistencia/{socio_id}", tags=["Clases y Reservas"])
def registrar_asistencia_en_clase(
    clase_id: str, socio_id: str, session: Session = Depends(get_db_session),
    instructor_autenticado: str = Depends(requerir_rol_staff("INSTRUCTOR")),
) -> dict[str, Any]:
    """US-011: solo el instructor asignado puede registrar asistencia."""
    clase = SqlClaseProgramadaRepository(session).get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    if clase.instructor_id != instructor_autenticado:
        raise HTTPException(status_code=403, detail="Solo el instructor asignado puede registrar asistencia.")
    service = AsistenciaAppService(SqlSocioRepository(session), SqlClaseProgramadaRepository(session), SqlAlchemyUnitOfWork(session))
    try:
        return service.registrar_asistencia(socio_id, clase_id)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/clases/{clase_id}/promociones/{socio_id}/confirmar", tags=["Clases y Reservas"])
def confirmar_promocion_lista_espera(
    clase_id: str, socio_id: str, session: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """US-005: Confirma una promoción FIFO dentro de la ventana de 30 minutos."""
    repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)
    clase = repo.get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    try:
        clase.confirmar_promocion(socio_id)
        repo.save(clase)
        uow.commit()
        return {"clase_id": clase_id, "socio_id": socio_id, "estado": "CONFIRMADA"}
    except FitZoneDomainError as exc:
        uow.rollback()
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/clases/{clase_id}/promociones/procesar-expiracion", tags=["Clases y Reservas"])
def procesar_expiracion_promocion(
    clase_id: str, session: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """Procesa vencimientos de promociones; puede invocarse mediante tarea programada."""
    repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)
    clase = repo.get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    siguiente = clase.expirar_promocion()
    repo.save(clase)
    uow.commit()
    return {"clase_id": clase_id, "siguiente_socio_promovido": siguiente, "promocion_pendiente": clase.promocion_pendiente_socio_id}


@app.post("/api/v1/clases/{clase_id}/no-show/{socio_id}", tags=["Clases y Reservas"])
def registrar_no_show_en_clase(
    clase_id: str, socio_id: str, session: Session = Depends(get_db_session),
    instructor_autenticado: str = Depends(requerir_rol_staff("INSTRUCTOR")),
) -> dict[str, Any]:
    """CU-05 (US-011, US-017): solo el instructor asignado registra no-shows."""
    clase = SqlClaseProgramadaRepository(session).get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    if clase.instructor_id != instructor_autenticado:
        raise HTTPException(status_code=403, detail="Solo el instructor asignado puede registrar inasistencias.")
    service = AsistenciaAppService(
        SqlSocioRepository(session),
        SqlClaseProgramadaRepository(session),
        SqlAlchemyUnitOfWork(session),
    )
    try:
        return service.registrar_no_show(socio_id, clase_id)
    except FitZoneDomainError as exc:
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/clases/{clase_id}/reasignar-instructor", tags=["Clases y Reservas"])
def reasignar_instructor_clase(
    clase_id: str, dto: ReasignarInstructorDTO, session: Session = Depends(get_db_session),
    _administrador_autenticado: str = Depends(requerir_rol_staff("ADMIN")),
) -> dict[str, Any]:
    """US-020 (N6): Reasigna un instructor de respaldo cuando el titular no puede asistir."""
    repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)
    clase = repo.get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    try:
        conflicto = next((otra for otra in repo.list_all()
            if otra.clase_id != clase.clase_id and not otra.cancelada
            and otra.instructor_id == dto.nuevo_instructor_id
            and _mismo_inicio_horario(otra.horario, clase.horario)), None)
        if conflicto:
            raise HTTPException(status_code=409, detail=(
                "El instructor seleccionado ya está asignado a otra clase "
                "en el mismo horario"
            ))
        instructor_anterior = clase.instructor_id
        clase.reasignar_instructor(dto.nuevo_instructor_id)
        notificador = SqlOutboxNotificador(session)
        notificados = []
        for socio_id in clase.reservas_confirmadas_ids:
            notificador.enviar_notificacion(
                socio_id,
                "Cambio de instructor",
                f"La clase {clase.disciplina} ({clase.clase_id}) ahora será impartida por {clase.instructor_id} en lugar de {instructor_anterior}.",
            )
            notificados.append(socio_id)
        repo.save(clase)
        uow.commit()
        return {
            "clase_id": clase.clase_id,
            "instructor_anterior": instructor_anterior,
            "instructor_id": clase.instructor_id,
            "notificaciones_en_cola": len(notificados),
            "eventos": [e.nombre for e in clase.eventos],
        }
    except FitZoneDomainError as exc:
        uow.rollback()
        raise _traducir_error_dominio(exc)


@app.post("/api/v1/clases/{clase_id}/cancelar-instructor", tags=["Clases y Reservas"])
def cancelar_clase_por_instructor(
    clase_id: str, dto: CancelarInstructorDTO, session: Session = Depends(get_db_session),
    instructor_autenticado: str = Depends(requerir_rol_staff("INSTRUCTOR")),
) -> dict[str, Any]:
    """US-010 (N6): Cancela una clase con al menos 2 horas de anticipación."""
    repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)
    clase = repo.get_by_id(clase_id)
    if clase is None:
        raise HTTPException(status_code=404, detail=f"No encontramos la clase {clase_id}.")
    if instructor_autenticado != clase.instructor_id:
        raise HTTPException(status_code=403, detail="No tienes asignada esta clase y no puedes realizar esta operación.")
    try:
        horas_reales = _calcular_horas_hasta_clase(clase.horario)
        # El campo legacy dto.horas_anticipacion se ignora: se calcula con el horario persistido.
        clase.cancelar_por_instructor(horas_reales, dto.motivo)
        notificador = SqlOutboxNotificador(session)
        socios_afectados = list(clase.eventos[-1].detalles.get("socios_afectados", []))
        for socio_id in socios_afectados:
            notificador.enviar_notificacion(
                socio_id,
                "Clase cancelada por instructor",
                f"La clase {clase.disciplina} ({clase.clase_id}) fue cancelada. Motivo: {dto.motivo}. Consulta recepción para opciones de reprogramación.",
            )
        notificador.enviar_notificacion(
            "ADMIN",
            "Cancelación de clase por instructor",
            f"El instructor {instructor_autenticado} canceló {clase.clase_id}. Socios afectados: {len(socios_afectados)}.",
        )
        sugerencias = [
            {"clase_id": candidata.clase_id, "disciplina": candidata.disciplina,
             "horario": candidata.horario, "cupos_disponibles": candidata.cupos_disponibles}
            for candidata in repo.list_all()
            if candidata.clase_id != clase.clase_id and not candidata.cancelada
            and candidata.disciplina.casefold() == clase.disciplina.casefold()
            and candidata.cupos_disponibles > 0
        ]
        repo.save(clase)
        uow.commit()
        return {
            "clase_id": clase.clase_id,
            "cancelada": clase.cancelada,
            "socios_notificados_en_cola": len(socios_afectados),
            "notificacion_admin_en_cola": True,
            "clases_similares_disponibles": sugerencias,
            "eventos": [e.nombre for e in clase.eventos],
        }
    except FitZoneDomainError as exc:
        uow.rollback()
        raise _traducir_error_dominio(exc)


@app.get("/api/v1/notificaciones/pendientes", tags=["Notificaciones"])
def listar_notificaciones_pendientes(
    session: Session = Depends(get_db_session),
    _administrador_autenticado: str = Depends(requerir_rol_staff("ADMIN")),
) -> dict[str, Any]:
    """Consulta la outbox de notificaciones pendientes de entrega externa."""
    notificador = SqlOutboxNotificador(session)
    pendientes = notificador.listar_pendientes()
    return {"total": len(pendientes), "notificaciones": pendientes,
            "nota": "Los mensajes están persistidos en cola; el envío por correo/SMS requiere un adaptador externo."}


# ==============================================================================
# ENDPOINTS DE REPORTES ANALÍTICOS (CQRS QUERIES - N5) Y LOTE CSV OFICIAL
# ==============================================================================


@app.get("/api/v1/reportes/ocupacion", tags=["Reportes y Analítica CQRS"])
def obtener_reporte_ocupacion(session: Session = Depends(get_db_session)) -> list[dict[str, Any]]:
    """US-014 (N5): Reporte de porcentaje de ocupación y demanda por clase."""
    query_service = ReportesQueryService(
        SqlSocioRepository(session),
        SqlClaseProgramadaRepository(session),
        SqlOperacionRepository(session, SqlSocioRepository(session)),
    )
    return query_service.reporte_ocupacion_clases()


@app.get("/api/v1/reportes/no-shows", tags=["Reportes y Analítica CQRS"])
def obtener_reporte_no_shows(session: Session = Depends(get_db_session)) -> list[dict[str, Any]]:
    """US-015 (N5): Reporte de inasistencias acumuladas y socios bloqueados."""
    query_service = ReportesQueryService(
        SqlSocioRepository(session),
        SqlClaseProgramadaRepository(session),
        SqlOperacionRepository(session, SqlSocioRepository(session)),
    )
    return query_service.reporte_no_shows_socios()


@app.get("/api/v1/lote-pruebas/casos", tags=["Evaluación Paquete 11_FitZone"])
def ejecutar_120_casos_csv() -> dict[str, Any]:
    """Ejecuta en vivo los 120 casos de prueba de casos_prueba.csv y devuelve el resumen."""
    resultados = evaluar_casos_prueba_csv()
    validas = sum(1 for r in resultados if r["resultado_alumno"] == "VALIDA")
    rechazadas = sum(1 for r in resultados if r["resultado_alumno"] == "RECHAZADA")
    con_beneficio = sum(1 for r in resultados if r["resultado_alumno"].startswith("APLICA_10%"))
    return {
        "total_casos": len(resultados),
        "operaciones_validas": validas,
        "operaciones_rechazadas": rechazadas,
        "operaciones_con_beneficio_10": con_beneficio,
        "resultados": resultados,
    }


@app.get("/api/v1/lote-pruebas/transiciones", tags=["Evaluación Paquete 11_FitZone"])
def ejecutar_20_transiciones_csv() -> dict[str, Any]:
    """Ejecuta en vivo las 20 pruebas de transición de transiciones_prueba.csv."""
    resultados = evaluar_transiciones_csv()
    exitosas = sum(1 for r in resultados if r["resultado_alumno"].startswith("TRANSICION_EXITOSA"))
    rechazadas = len(resultados) - exitosas
    return {
        "total_transiciones": len(resultados),
        "transiciones_exitosas": exitosas,
        "transiciones_rechazadas": rechazadas,
        "resultados": resultados,
    }


# Interfaz web de FitZone: se monta al final para no interceptar las rutas de la API.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
