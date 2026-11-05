"""Modelos ORM SQLAlchemy y configuración de motor de Base de Datos (12-Factor App)."""

import os

from sqlalchemy import Boolean, Column, Float, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class SocioRow(Base):
    __tablename__ = "socios"

    actor_id = Column(String(32), primary_key=True)
    nombre = Column(String(120), nullable=False)
    es_preferente = Column(Boolean, nullable=False, default=False)
    activo = Column(Boolean, nullable=False, default=True)
    ciudad = Column(String(80), nullable=False, default="Monterrey")
    tipo_plan = Column(String(32), nullable=False, default="BASICO")
    no_shows_mes = Column(Integer, nullable=False, default=0)
    bloqueado_reservas = Column(Boolean, nullable=False, default=False)
    dias_bloqueo_restantes = Column(Integer, nullable=False, default=0)
    reservas_activas_count = Column(Integer, nullable=False, default=0)
    vigencia_inicio = Column(String(10), nullable=True)
    vigencia_fin = Column(String(10), nullable=True)
    periodo_no_shows = Column(String(7), nullable=False, default="")
    bloqueo_hasta = Column(String(10), nullable=True)


class PlanDeportivoRow(Base):
    __tablename__ = "catalogo_planes"

    recurso_id = Column(String(32), primary_key=True)
    descripcion = Column(String(120), nullable=False)
    precio_mxn = Column(String(32), nullable=False)
    capacidad_o_stock = Column(Integer, nullable=False)
    habilitado = Column(Boolean, nullable=False, default=True)


class OperacionMembresiaRow(Base):
    __tablename__ = "operaciones_membresia"

    operacion_id = Column(String(32), primary_key=True)
    actor_id = Column(String(32), nullable=False)
    estado = Column(String(32), nullable=False)
    fecha_solicitud = Column(String(32), nullable=False)
    promocion_activa = Column(Boolean, nullable=False, default=False)
    autorizado = Column(Boolean, nullable=False, default=True)
    referencia = Column(String(64), nullable=False, default="")
    lineas_json = Column(Text, nullable=False, default="[]")
    eventos_json = Column(Text, nullable=False, default="[]")


class NotificacionOutboxRow(Base):
    __tablename__ = "notificaciones_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    destinatario_id = Column(String(32), nullable=False, index=True)
    asunto = Column(String(160), nullable=False)
    mensaje = Column(Text, nullable=False)
    estado = Column(String(20), nullable=False, default="PENDIENTE")
    creado_en = Column(String(32), nullable=False)


class AuditoriaRow(Base):
    __tablename__ = "auditoria_operaciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ocurrido_en = Column(String(40), nullable=False, index=True)
    actor_id = Column(String(32), nullable=False, index=True)
    rol = Column(String(20), nullable=False)
    accion = Column(String(80), nullable=False, index=True)
    entidad_tipo = Column(String(40), nullable=False)
    entidad_id = Column(String(64), nullable=False, index=True)
    resultado = Column(String(20), nullable=False)
    detalle = Column(Text, nullable=False, default="")


class ClaseProgramadaRow(Base):
    __tablename__ = "clases_programadas"

    clase_id = Column(String(32), primary_key=True)
    disciplina = Column(String(80), nullable=False)
    horario = Column(String(64), nullable=False)
    capacidad_maxima = Column(Integer, nullable=False)
    instructor_id = Column(String(32), nullable=False, default="INST-01")
    incluida_en_plan_basico = Column(Boolean, nullable=False, default=True)
    planes_incluidos_json = Column(Text, nullable=True)
    cancelada = Column(Boolean, nullable=False, default=False)
    cut_off_horas_socio = Column(Float, nullable=False, default=3.0)
    reservas_json = Column(Text, nullable=False, default="{}")
    lista_espera_json = Column(Text, nullable=False, default="[]")
    promocion_pendiente_socio_id = Column(String(32), nullable=True)
    promocion_expira_en = Column(String(32), nullable=True)
    eventos_json = Column(Text, nullable=False, default="[]")


def get_database_url() -> str:
    """Obtiene la URL de conexión desde variables de entorno (12-Factor App)."""
    return os.getenv("DATABASE_URL", "sqlite:///./fitzone_pia.sqlite3")


def make_engine(db_url: str | None = None):
    url = db_url or get_database_url()
    # SQLAlchemy 2.1 usa psycopg 3 por defecto para URLs postgresql://.
    # El proyecto instala psycopg2-binary, por lo que fijamos explícitamente ese driver.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    opciones_engine = {"poolclass": StaticPool} if url in ("sqlite://", "sqlite:///:memory:") else {}
    engine = create_engine(url, connect_args=connect_args, **opciones_engine)
    Base.metadata.create_all(engine)
    # Migración aditiva para bases existentes (SQLite y PostgreSQL).
    additions = {
        "socios": {"vigencia_inicio": "VARCHAR(10)", "vigencia_fin": "VARCHAR(10)",
                   "periodo_no_shows": "VARCHAR(7) NOT NULL DEFAULT ''", "bloqueo_hasta": "VARCHAR(10)"},
        "clases_programadas": {"promocion_pendiente_socio_id": "VARCHAR(32)",
                               "promocion_expira_en": "VARCHAR(32)", "planes_incluidos_json": "TEXT"},
    }
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table, columns in additions.items():
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
    return engine


def make_session(engine=None) -> Session:
    eng = engine or make_engine()
    factory = sessionmaker(bind=eng, autoflush=True, autocommit=False)
    return factory()
