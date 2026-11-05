"""Pruebas Automatizadas de los 120 Casos de Prueba (casos_prueba.csv) y 20 Transiciones (transiciones_prueba.csv)."""

from decimal import Decimal

from src.infrastructure.csv_loader import (
    cargar_entidades_desde_csv,
    evaluar_casos_prueba_csv,
    evaluar_transiciones_csv,
)


def test_carga_completa_csv_oficiales_11_fitzone():
    socios, catalogo, operaciones = cargar_entidades_desde_csv()
    assert len(socios) == 40
    assert len(catalogo) == 20
    assert len(operaciones) == 60

    # Verificar que FIT-O013 y FIT-O039 no tienen líneas (0.00 MXN)
    assert len(operaciones["FIT-O013"].lineas) == 0
    assert operaciones["FIT-O013"].total_bruto.amount == Decimal("0.00")
    assert len(operaciones["FIT-O039"].lineas) == 0

    # Verificar que FIT-P011 está deshabilitado en catálogo
    assert catalogo["FIT-P011"].habilitado is False


def test_ejecucion_120_casos_prueba_csv():
    resultados = evaluar_casos_prueba_csv()
    assert len(resultados) == 120

    por_id = {r["caso_id"]: r for r in resultados}

    # FIT-T001 (FIT-O001): Socio FIT-C019 activo, 2 líneas habilitadas, autorizado -> VALIDA
    assert por_id["FIT-T001"]["resultado_alumno"] == "VALIDA"
    # FIT-B001 (FIT-O001): Socio FIT-C019 no es preferente -> SIN_BENEFICIO
    assert por_id["FIT-B001"]["resultado_alumno"].startswith("SIN_BENEFICIO")

    # FIT-T004 / FIT-B004 (FIT-O004): Socio FIT-C040 preferente, activo, total 5210 >= 1500, sin promo -> VALIDA y APLICA_10%
    assert por_id["FIT-T004"]["resultado_alumno"] == "VALIDA"
    assert por_id["FIT-B004"]["resultado_alumno"].startswith("APLICA_10%")

    # FIT-T005 (FIT-O005): Socio FIT-C007 inactivo y usa FIT-P011 deshabilitado -> RECHAZADA
    assert por_id["FIT-T005"]["resultado_alumno"] == "RECHAZADA"

    # FIT-T013 (FIT-O013): Sin líneas de detalle -> RECHAZADA
    assert por_id["FIT-T013"]["resultado_alumno"] == "RECHAZADA"

    # FIT-T015 (FIT-O015): Socio activo pero usa FIT-P011 deshabilitado -> RECHAZADA
    assert por_id["FIT-T015"]["resultado_alumno"] == "RECHAZADA"


def test_ejecucion_20_transiciones_prueba_csv():
    resultados = evaluar_transiciones_csv()
    assert len(resultados) == 20

    por_id = {r["caso_id"]: r for r in resultados}

    # FIT-S001 (FIT-O001, completar): SOLICITADA -> ACTIVA -> SUSPENDIDA -> VENCIDA
    assert por_id["FIT-S001"]["estado_final"] == "VENCIDA"
    assert por_id["FIT-S001"]["resultado_alumno"] == "TRANSICION_EXITOSA -> VENCIDA"

    # FIT-S002 (FIT-O002, cancelar): SOLICITADA -> CANCELADA
    assert por_id["FIT-S002"]["estado_final"] == "CANCELADA"

    # FIT-S003 (FIT-O003, repetir_aprobacion): Primera aprueba, segunda falla con TransicionEstadoInvalidaError
    assert "TransicionEstadoInvalidaError" in por_id["FIT-S003"]["resultado_alumno"]

    # FIT-S004 (FIT-O004, saltar_estado): Intentar vencer desde SOLICITADA falla con TransicionEstadoInvalidaError
    assert "TransicionEstadoInvalidaError" in por_id["FIT-S004"]["resultado_alumno"]

    # FIT-S005 (FIT-O005, aprobar): Socio inactivo y recurso deshabilitado -> falla con PrecondicionOperacionError
    assert "PrecondicionOperacionError" in por_id["FIT-S005"]["resultado_alumno"]

    # FIT-S010 (FIT-O010, aprobar): Operación válida -> pasa a ACTIVA
    assert por_id["FIT-S010"]["estado_final"] == "ACTIVA"
