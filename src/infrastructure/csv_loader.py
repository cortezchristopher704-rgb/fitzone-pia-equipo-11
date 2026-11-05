"""Cargador y ejecutor oficial de los archivos CSV del paquete 11_FitZone."""

import csv
import os
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from src.domain.exceptions import FitZoneDomainError
from src.domain.models import (
    ClaseProgramada,
    EstadoOperacion,
    OperacionMembresia,
    PlanDeportivo,
    Socio,
)
from src.domain.value_objects import Money
from src.infrastructure.repositories import (
    SqlAlchemyUnitOfWork,
    SqlCatalogoRepository,
    SqlClaseProgramadaRepository,
    SqlOperacionRepository,
    SqlSocioRepository,
)


def default_datos_dir() -> str:
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.getenv("FITZONE_DATA_DIR", os.path.join(base_dir, "datos"))


def cargar_entidades_desde_csv(
    datos_dir: str | None = None,
) -> tuple[dict[str, Socio], dict[str, PlanDeportivo], dict[str, OperacionMembresia]]:
    """Lee actores.csv, catalogo.csv, operaciones.csv y detalle_operaciones.csv en memoria."""
    folder = datos_dir or default_datos_dir()

    socios: dict[str, Socio] = {}
    with open(os.path.join(folder, "actores.csv"), mode="r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            es_pref = row["es_preferente"].strip() == "1"
            socios[row["actor_id"].strip()] = Socio(
                actor_id=row["actor_id"].strip(),
                nombre=row["nombre"].strip(),
                es_preferente=es_pref,
                activo=row["activo"].strip() == "1",
                ciudad=row["ciudad"].strip(),
                tipo_plan="PREMIUM" if es_pref else "BASICO",
            )

    catalogo: dict[str, PlanDeportivo] = {}
    with open(os.path.join(folder, "catalogo.csv"), mode="r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            catalogo[row["recurso_id"].strip()] = PlanDeportivo(
                recurso_id=row["recurso_id"].strip(),
                descripcion=row["descripcion"].strip(),
                precio_mxn=Money(Decimal(row["precio_mxn"].strip()), "MXN"),
                capacidad_o_stock=int(row["capacidad_o_stock"].strip()),
                habilitado=row["habilitado"].strip() == "1",
            )

    operaciones: dict[str, OperacionMembresia] = {}
    with open(os.path.join(folder, "operaciones.csv"), mode="r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            op_id = row["operacion_id"].strip()
            actor_id = row["actor_id"].strip()
            operaciones[op_id] = OperacionMembresia(
                operacion_id=op_id,
                socio=socios[actor_id],
                estado=EstadoOperacion(row["estado_inicial"].strip()),
                fecha_solicitud=row["fecha_solicitud"].strip(),
                promocion_activa=row["promocion_activa"].strip() == "1",
                autorizado=row["autorizado"].strip() == "1",
                referencia=row["referencia"].strip(),
            )

    with open(
        os.path.join(folder, "detalle_operaciones.csv"), mode="r", encoding="utf-8-sig"
    ) as f:
        for row in csv.DictReader(f):
            op_id = row["operacion_id"].strip()
            rec_id = row["recurso_id"].strip()
            cant = int(row["cantidad"].strip())
            if op_id in operaciones and rec_id in catalogo:
                operaciones[op_id].agregar_linea(catalogo[rec_id], cant)

    return socios, catalogo, operaciones


def poblar_base_de_datos(session: Session, datos_dir: str | None = None) -> dict[str, int]:
    """Importa todos los CSVs y clases programadas iniciales dentro de la base de datos SQL."""
    socios, catalogo, operaciones = cargar_entidades_desde_csv(datos_dir)
    socio_repo = SqlSocioRepository(session)
    cat_repo = SqlCatalogoRepository(session)
    op_repo = SqlOperacionRepository(session, socio_repo)
    clase_repo = SqlClaseProgramadaRepository(session)
    uow = SqlAlchemyUnitOfWork(session)

    for s in socios.values():
        socio_repo.save(s)
    for p in catalogo.values():
        cat_repo.save(p)
    for op in operaciones.values():
        op_repo.save(op)

    # Sembrar clases deportivas representativas del BRD de FitZone si no existen
    clases_demo = [
        ClaseProgramada(
            clase_id="CLASE-01",
            disciplina="CrossFit Intensivo",
            horario="2026-11-05 08:00",
            capacidad_maxima=20,
            instructor_id="INST-01",
        ),
        ClaseProgramada(
            clase_id="CLASE-02",
            disciplina="Spinning Pro",
            horario="2026-11-05 18:00",
            capacidad_maxima=2,
            instructor_id="INST-02",
        ),
        ClaseProgramada(
            clase_id="CLASE-03",
            disciplina="Yoga Restaurativo",
            horario="2026-11-05 20:00",
            capacidad_maxima=15,
            instructor_id="INST-03",
        ),
    ]
    for c in clases_demo:
        if clase_repo.get_by_id(c.clase_id) is None:
            clase_repo.save(c)

    uow.commit()
    return {
        "socios": len(socios),
        "catalogo": len(catalogo),
        "operaciones": len(operaciones),
        "clases": len(clases_demo),
    }


def evaluar_casos_prueba_csv(datos_dir: str | None = None) -> list[dict[str, Any]]:
    """Ejecuta los 120 casos de casos_prueba.csv contra el modelo de dominio."""
    folder = datos_dir or default_datos_dir()
    _, _, operaciones = cargar_entidades_desde_csv(folder)

    resultados: list[dict[str, Any]] = []
    with open(os.path.join(folder, "casos_prueba.csv"), mode="r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            caso_id = row["caso_id"].strip()
            op_id = row["operacion_id"].strip()
            tipo = row["tipo_prueba"].strip()
            regla = row["regla_a_verificar"].strip()
            op = operaciones[op_id]

            if tipo == "validar_operacion":
                cumple = op.puede_procesarse()
                res_alumno = "VALIDA" if cumple else "RECHAZADA"
                evidencia = (
                    f"socio_activo={op.socio.activo}, lineas={len(op.lineas)}, "
                    f"recursos_ok={all(l.recurso_habilitado and l.cantidad <= l.stock_disponible for l in op.lineas) if op.lineas else False}, "
                    f"autorizado={op.autorizado}"
                )
            else:
                aplica = op.tiene_beneficio_preferente()
                res_alumno = (
                    f"APLICA_10% (desc={op.monto_descuento.amount}, neto={op.total_neto.amount})"
                    if aplica
                    else f"SIN_BENEFICIO (0%, total={op.total_bruto.amount})"
                )
                evidencia = (
                    f"preferente={op.socio.es_preferente}, total_bruto={op.total_bruto.amount}, "
                    f"promocion_activa={op.promocion_activa}"
                )

            resultados.append(
                {
                    "caso_id": caso_id,
                    "operacion_id": op_id,
                    "tipo_prueba": tipo,
                    "regla_a_verificar": regla,
                    "resultado_alumno": res_alumno,
                    "evidencia_tecnica": evidencia,
                }
            )
    return resultados


def evaluar_transiciones_csv(datos_dir: str | None = None) -> list[dict[str, Any]]:
    """Ejecuta las 20 pruebas de transición de transiciones_prueba.csv sobre instancias frescas."""
    folder = datos_dir or default_datos_dir()
    resultados: list[dict[str, Any]] = []

    with open(
        os.path.join(folder, "transiciones_prueba.csv"), mode="r", encoding="utf-8-sig"
    ) as f:
        for row in csv.DictReader(f):
            # Cargar copia fresca para aislar efectos entre casos
            _, _, operaciones = cargar_entidades_desde_csv(folder)
            caso_id = row["caso_id"].strip()
            op_id = row["operacion_id"].strip()
            accion = row["accion_sugerida"].strip()
            estado_ini = row["estado_inicial"].strip()
            op = operaciones[op_id]

            try:
                op.ejecutar_accion_transicion(accion)
                eventos_nombres = [e.nombre for e in op.eventos]
                res_alumno = f"TRANSICION_EXITOSA -> {op.estado.value}"
                evidencia = f"Eventos emitidos: {eventos_nombres}"
            except FitZoneDomainError as exc:
                res_alumno = f"RECHAZADA ({exc.__class__.__name__})"
                evidencia = f"Estado preservado: {op.estado.value} | Detalle: {exc!s}"

            resultados.append(
                {
                    "caso_id": caso_id,
                    "operacion_id": op_id,
                    "accion_sugerida": accion,
                    "estado_inicial": estado_ini,
                    "estado_final": op.estado.value,
                    "resultado_alumno": res_alumno,
                    "evidencia_tecnica": evidencia,
                }
            )
    return resultados
