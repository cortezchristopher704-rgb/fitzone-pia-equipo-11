"""Pruebas de Integración de la API REST FastAPI (200/201, 404, 409, 422)."""

from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from src.api.main import app


def test_api_end_to_end_flows_and_status_codes(monkeypatch):
    monkeypatch.setenv("FITZONE_STAFF_TOKEN_ADMIN", "test-admin-secret")
    monkeypatch.setenv("FITZONE_STAFF_TOKEN_INSTRUCTOR", "test-inst-secret")
    with TestClient(app) as client:
        # 1. Health & Seed (200 / 201)
        r_health = client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "ok"

        r_seed = client.post("/api/v1/seed")
        assert r_seed.status_code == 201
        assert r_seed.json()["resumen"]["socios"] == 40

        # 2. Socios, Catálogo y Control de Acceso (200 / 404)
        r_socios = client.get("/api/v1/socios")
        assert r_socios.status_code == 200
        assert len(r_socios.json()) == 40

        r_s1 = client.get("/api/v1/socios/FIT-C001")
        assert r_s1.status_code == 200
        assert r_s1.json()["actor_id"] == "FIT-C001"

        assert client.get("/api/v1/socios/NO-EXISTE").status_code == 404

        admin_headers = {"X-Staff-Role": "ADMIN", "X-Staff-Token": "test-admin-secret", "X-Staff-Id": "ADMIN-01"}
        client.headers.update(admin_headers)
        r_sin_vigencia = client.post("/api/v1/socios/FIT-C001/acceso")
        assert r_sin_vigencia.status_code == 200
        assert r_sin_vigencia.json()["permitido"] is False
        assert r_sin_vigencia.json()["motivo"] == "Vigencia de membresía no registrada"
        horario_sin_vigencia = (datetime.now() + timedelta(days=1)).isoformat(timespec="minutes")
        assert client.post("/api/v1/clases", json={
            "clase_id": "CLASE-SIN-VIGENCIA", "disciplina": "Yoga",
            "horario": horario_sin_vigencia, "capacidad_maxima": 2,
        }).status_code == 201
        assert client.post("/api/v1/clases/CLASE-SIN-VIGENCIA/reservas",
            json={"socio_id": "FIT-C001"}).status_code == 422
        r_vigencia = client.put("/api/v1/socios/FIT-C001/vigencia", json={
            "fecha_inicio": (date.today() - timedelta(days=2)).isoformat(),
            "fecha_fin": (date.today() + timedelta(days=30)).isoformat(),
        }, headers=admin_headers)
        assert r_vigencia.status_code == 200
        # El CSV oficial no contiene vigencias; para los flujos de demostración se asignan fechas de prueba.
        from src.api.main import _ENGINE
        from src.infrastructure.database import SocioRow
        from sqlalchemy.orm import Session
        with Session(_ENGINE) as db:
            for socio_row in db.query(SocioRow).all():
                if socio_row.actor_id != "FIT-C001":
                    socio_row.vigencia_inicio = (date.today() - timedelta(days=2)).isoformat()
                    socio_row.vigencia_fin = (date.today() + timedelta(days=30)).isoformat()
            db.commit()
        assert client.put("/api/v1/socios/FIT-C001/vigencia", json={
            "fecha_inicio": "2026-12-31", "fecha_fin": "2026-01-01",
        }, headers=admin_headers).status_code == 422
        r_acc_ok = client.post("/api/v1/socios/FIT-C001/acceso")
        assert r_acc_ok.status_code == 200
        assert r_acc_ok.json()["permitido"] is True

        r_acc_den = client.post("/api/v1/socios/FIT-C007/acceso")
        assert r_acc_den.status_code == 200
        assert r_acc_den.json()["permitido"] is False

        assert client.post("/api/v1/socios/NO-EXISTE/acceso").status_code == 404

        r_cat = client.get("/api/v1/catalogo")
        assert r_cat.status_code == 200
        assert len(r_cat.json()) == 20

        # 3. Operaciones, Specifications y Máquina de Estados (200 / 404 / 409 / 422)
        r_ops = client.get("/api/v1/operaciones")
        assert r_ops.status_code == 200
        assert len(r_ops.json()) == 60

        r_op1 = client.get("/api/v1/operaciones/FIT-O001")
        assert r_op1.status_code == 200
        assert r_op1.json()["estado"] == "SOLICITADA"

        assert client.get("/api/v1/operaciones/NO-EXISTE").status_code == 404
        assert client.get("/api/v1/operaciones/NO-EXISTE/evaluar").status_code == 404

        r_eval = client.get("/api/v1/operaciones/FIT-O004/evaluar")
        assert r_eval.status_code == 200
        assert r_eval.json()["beneficio_preferente"] is True

        # Aprobar FIT-O001 (200) y tratar de aprobar por segunda vez (409 Conflict)
        r_ap1 = client.post("/api/v1/operaciones/FIT-O001/aprobar")
        assert r_ap1.status_code == 200
        assert r_ap1.json()["estado"] == "ACTIVA"

        r_ap_dup = client.post("/api/v1/operaciones/FIT-O001/aprobar")
        assert r_ap_dup.status_code == 409

        # Suspender y vencer FIT-O001 (200)
        r_susp = client.post("/api/v1/operaciones/FIT-O001/suspender", json={"motivo": "Pausa"})
        assert r_susp.status_code == 200
        assert r_susp.json()["estado"] == "SUSPENDIDA"

        r_venc = client.post("/api/v1/operaciones/FIT-O001/vencer")
        assert r_venc.status_code == 200
        assert r_venc.json()["estado"] == "VENCIDA"

        # Intentar aprobar operación con precondiciones inválidas FIT-O005 (422)
        r_inv = client.post("/api/v1/operaciones/FIT-O005/aprobar")
        assert r_inv.status_code == 422

        # Intentar saltar estado SOLICITADA -> VENCIDA en FIT-O002 (409)
        assert client.post("/api/v1/operaciones/FIT-O002/vencer").status_code == 409
        assert client.post("/api/v1/operaciones/FIT-O002/suspender").status_code == 409

        # Cancelar FIT-O002 desde SOLICITADA (200) y repetir cancelación (409)
        r_canc_op = client.post("/api/v1/operaciones/FIT-O002/cancelar", json={"motivo": "Cambio"})
        assert r_canc_op.status_code == 200
        assert r_canc_op.json()["estado"] == "CANCELADA"
        assert client.post("/api/v1/operaciones/FIT-O002/cancelar").status_code == 409

        # 4. Clases, Reservas, Lista de Espera FIFO, Cancelaciones y No-Shows
        r_clases = client.get("/api/v1/clases")
        assert r_clases.status_code == 200
        assert len(r_clases.json()) >= 3

        with TestClient(app) as anonymous_client:
            r_sin_acceso_clase = anonymous_client.post("/api/v1/clases", json={
                "clase_id": "CLASE-SIN-AUTH", "disciplina": "Yoga",
                "horario": "2026-11-06 09:00", "capacidad_maxima": 5,
            })
            assert r_sin_acceso_clase.status_code == 401

        r_new_c = client.post(
            "/api/v1/clases",
            json={
                "clase_id": "CLASE-API-01",
                "disciplina": "Box Funcional",
                "horario": "2026-11-06 10:00",
                "capacidad_maxima": 1,
                "instructor_id": "INST-05",
            },
        )
        assert r_new_c.status_code == 201

        # Capacidad inválida al crear clase -> 422
        r_bad_c = client.post(
            "/api/v1/clases",
            json={
                "clase_id": "CLASE-BAD",
                "disciplina": "Box",
                "horario": "10:00",
                "capacidad_maxima": 0,
            },
        )
        assert r_bad_c.status_code == 422

        # Reservar cupo 1 con FIT-C002 -> CONFIRMADA
        r_res1 = client.post(
            "/api/v1/clases/CLASE-API-01/reservas",
            json={"socio_id": "FIT-C002", "es_drop_in": False},
        )
        assert r_res1.status_code == 200
        assert r_res1.json()["resultado"] == "CONFIRMADA"

        # Reserva duplicada -> 409
        assert (
            client.post(
                "/api/v1/clases/CLASE-API-01/reservas",
                json={"socio_id": "FIT-C002", "es_drop_in": False},
            ).status_code
            == 409
        )

        # Reservar con FIT-C003 cuando cupo == 0 -> LISTA_ESPERA
        r_res2 = client.post(
            "/api/v1/clases/CLASE-API-01/reservas",
            json={"socio_id": "FIT-C003", "es_drop_in": False},
        )
        assert r_res2.status_code == 200
        assert r_res2.json()["resultado"] == "LISTA_ESPERA"

        # Cancelar con >= 3h promueve a FIT-C003
        r_canc_res = client.post(
            "/api/v1/clases/CLASE-API-01/cancelar-reserva/FIT-C002",
            json={"horas_anticipacion": 4.0},
        )
        assert r_canc_res.status_code == 200
        assert r_canc_res.json()["socio_promovido"] == "FIT-C003"

        # El socio promovido debe confirmar en los 30 minutos antes de cancelar.
        r_confirma = client.post("/api/v1/clases/CLASE-API-01/promociones/FIT-C003/confirmar")
        assert r_confirma.status_code == 200

        # La anticipación se calcula con el horario guardado; se ignora el valor enviado por cliente.
        horario_cercano = (datetime.now() + timedelta(hours=1)).isoformat(timespec="minutes")
        assert client.post("/api/v1/clases", json={
            "clase_id": "CLASE-API-LATE", "disciplina": "Yoga",
            "horario": horario_cercano, "capacidad_maxima": 2,
        }).status_code == 201
        assert client.post("/api/v1/clases/CLASE-API-LATE/reservas", json={"socio_id": "FIT-C003"}).status_code == 200
        r_tardia = client.post(
            "/api/v1/clases/CLASE-API-LATE/cancelar-reserva/FIT-C003",
            json={"horas_anticipacion": 99.0},
        )
        assert r_tardia.status_code == 422

        # Registrar 3 no-shows reales: cada uno requiere una reserva confirmada distinta.
        for idx in range(1, 4):
            clase_ns = f"CLASE-NS-{idx}"
            client.post("/api/v1/clases", json={"clase_id": clase_ns, "disciplina": "Yoga", "horario": "2026-11-07 10:00", "capacidad_maxima": 5})
            assert client.post(f"/api/v1/clases/{clase_ns}/reservas", json={"socio_id": "FIT-C009"}).status_code == 200
            r_ns3 = client.post(f"/api/v1/clases/{clase_ns}/no-show/FIT-C009", headers={"X-Staff-Role": "INSTRUCTOR", "X-Staff-Token": "test-inst-secret", "X-Staff-Id": "INST-01"})
            assert r_ns3.status_code == 200
        assert r_ns3.json()["bloqueado_reservas"] is True

        assert (
            client.post(
                "/api/v1/clases/CLASE-01/reservas",
                json={"socio_id": "FIT-C009", "es_drop_in": False},
            ).status_code
            == 409
        )
        assert client.post("/api/v1/clases/NO-EXISTE/no-show/FIT-C009").status_code == 404

        # Reasignar instructor y cancelar por instructor
        instructor_headers = {"X-Staff-Role": "INSTRUCTOR", "X-Staff-Token": "test-inst-secret", "X-Staff-Id": "INST-01"}
        r_reasig = client.post(
            "/api/v1/clases/CLASE-03/reasignar-instructor",
            json={"nuevo_instructor_id": "INST-SUPLENTE-10"}, headers=admin_headers,
        )
        assert r_reasig.status_code == 200
        assert client.post("/api/v1/clases/NO-EXISTE/reasignar-instructor", json={"nuevo_instructor_id": "X"}, headers=admin_headers).status_code == 404
        assert client.post("/api/v1/clases/CLASE-03/reasignar-instructor", json={"nuevo_instructor_id": ""}, headers=admin_headers).status_code == 422

        horario_instructor_cercano = (datetime.now() + timedelta(hours=1)).isoformat(timespec="minutes")
        assert client.post("/api/v1/clases", json={
            "clase_id": "CLASE-INSTRUCTOR-LATE", "disciplina": "Box",
            "horario": horario_instructor_cercano, "capacidad_maxima": 10,
        }).status_code == 201
        assert client.post(
            "/api/v1/clases/CLASE-INSTRUCTOR-LATE/cancelar-instructor",
            json={"horas_anticipacion": 99.0, "motivo": "Tarde"},
            headers={"X-Staff-Role": "INSTRUCTOR", "X-Staff-Token": "test-inst-secret", "X-Staff-Id": "INST-01"},
        ).status_code == 422
        r_canc_inst = client.post(
            "/api/v1/clases/CLASE-03/cancelar-instructor",
            json={"horas_anticipacion": 3.0, "motivo": "Clima"},
            headers={"X-Staff-Role": "INSTRUCTOR", "X-Staff-Token": "test-inst-secret", "X-Staff-Id": "INST-SUPLENTE-10"},
        )
        assert r_canc_inst.status_code == 200
        assert client.post("/api/v1/clases/NO-EXISTE/cancelar-instructor", json={"horas_anticipacion": 3.0, "motivo": "X"}, headers={"X-Staff-Role": "INSTRUCTOR", "X-Staff-Token": "test-inst-secret", "X-Staff-Id": "INST-01"}).status_code == 404

        # 5. Reportes analíticos CQRS y ejecución de lote CSV oficial
        assert client.get("/api/v1/reportes/ocupacion").status_code == 200
        r_reporte_ns = client.get("/api/v1/reportes/no-shows")
        assert r_reporte_ns.status_code == 200
        socio_ns_reporte = next(x for x in r_reporte_ns.json() if x["actor_id"] == "FIT-C009")
        assert socio_ns_reporte["no_shows_historicos"] == 3
        assert socio_ns_reporte["tasa_no_show_porcentaje"] == 100.0

        r_lote_casos = client.get("/api/v1/lote-pruebas/casos")
        assert r_lote_casos.status_code == 200
        assert r_lote_casos.json()["total_casos"] == 120

        r_lote_trans = client.get("/api/v1/lote-pruebas/transiciones")
        assert r_lote_trans.status_code == 200
        assert r_lote_trans.json()["total_transiciones"] == 20


def test_new_use_cases_reception_instructor_capacity_and_expiry_alerts(monkeypatch):
    monkeypatch.setenv("FITZONE_STAFF_TOKEN_RECEPCION", "test-rec-secret")
    monkeypatch.setenv("FITZONE_STAFF_TOKEN_INSTRUCTOR", "test-inst-secret")
    monkeypatch.setenv("FITZONE_STAFF_TOKEN_ADMIN", "test-admin-secret")
    with TestClient(app) as client:
        client.post("/api/v1/seed")
        # Las fechas no vienen en el CSV oficial; se asignan vigencias de prueba explícitas a los socios de esta demo.
        admin_headers = {"X-Staff-Role": "ADMIN", "X-Staff-Token": "test-admin-secret", "X-Staff-Id": "ADMIN-01"}
        client.headers.update(admin_headers)
        for socio_id in ("FIT-C001", "FIT-C003", "FIT-C005"):
            assert client.put(f"/api/v1/socios/{socio_id}/vigencia", json={
                "fecha_inicio": (date.today() - timedelta(days=2)).isoformat(),
                "fecha_fin": (date.today() + timedelta(days=30)).isoformat(),
            }, headers=admin_headers).status_code == 200
        # US-008: recepción registra una reserva a nombre del socio.
        # La clase se programa dinámicamente a futuro para que la prueba no dependa
        # de la hora del día en que se ejecute (corte de cancelación de instructor: 2 h).
        horario_demo = (datetime.now() + timedelta(hours=4)).isoformat(timespec="minutes")
        client.post("/api/v1/clases", json={"clase_id": "CLASE-REC-01", "disciplina": "Yoga", "horario": horario_demo, "capacidad_maxima": 1, "instructor_id": "INST-REC"})
        recepcion_headers = {"X-Staff-Role": "RECEPCION", "X-Staff-Token": "test-rec-secret", "X-Staff-Id": "REC-01"}
        instructor_headers = {"X-Staff-Role": "INSTRUCTOR", "X-Staff-Token": "test-inst-secret", "X-Staff-Id": "INST-REC"}
        assert client.post("/api/v1/clases/CLASE-REC-01/reservas/recepcion", json={"socio_id": "FIT-C001", "empleado_id": "REC-01"}, headers={**recepcion_headers, "X-Staff-Token": "bad-token"}).status_code == 403
        r = client.post("/api/v1/clases/CLASE-REC-01/reservas/recepcion", json={"socio_id": "FIT-C001", "empleado_id": "REC-01"}, headers=recepcion_headers)
        assert r.status_code == 200
        assert r.json()["canal"] == "RECEPCION"
        assert r.json()["registrada_por"] == "REC-01"

        # US-009: la lista incluye confirmados y socios en espera; solo consulta el instructor asignado.
        r_espera = client.post("/api/v1/clases/CLASE-REC-01/reservas", json={"socio_id": "FIT-C003"})
        assert r_espera.status_code == 200
        assert r_espera.json()["resultado"] == "LISTA_ESPERA"
        r = client.get("/api/v1/clases/CLASE-REC-01/instructor/INST-REC/lista", headers=instructor_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 2
        assert client.post("/api/v1/clases/CLASE-REC-01/asistencia/FIT-C001").status_code == 401
        assert client.post("/api/v1/clases/CLASE-REC-01/asistencia/FIT-C001", headers=instructor_headers).status_code == 200
        estados_lista = {s["socio_id"]: s["estado"] for s in r.json()["socios"]}
        assert estados_lista["FIT-C001"] == "CONFIRMADA"
        assert estados_lista["FIT-C003"] == "LISTA_ESPERA"
        assert client.get("/api/v1/clases/CLASE-REC-01/instructor/OTRO/lista", headers=instructor_headers).status_code == 403

        # US-012: cambio de aforo y rechazo de capacidad inferior a la ocupación.
        assert client.patch("/api/v1/clases/CLASE-REC-01/capacidad", json={"capacidad_maxima": 5}, headers={**admin_headers, "X-Staff-Role": "RECEPCION"}).status_code == 403
        r = client.patch("/api/v1/clases/CLASE-REC-01/capacidad", json={"capacidad_maxima": 5}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["capacidad_maxima"] == 5
        r = client.patch("/api/v1/clases/CLASE-REC-01/capacidad", json={"capacidad_maxima": 0}, headers=admin_headers)
        assert r.status_code == 422
        r = client.patch("/api/v1/clases/CLASE-REC-01/capacidad", json={"capacidad_maxima": 0}, headers=admin_headers)
        assert r.status_code == 422

        # US-013: el administrador configura los tipos de plan permitidos y la regla persiste.
        assert client.post("/api/v1/clases", json={
            "clase_id": "CLASE-PLAN-01", "disciplina": "CrossFit",
            "horario": "2026-11-06 12:00", "capacidad_maxima": 3,
        }).status_code == 201
        r_planes = client.patch("/api/v1/clases/CLASE-PLAN-01/planes-incluidos",
            json={"planes_incluidos": ["PREMIUM"]}, headers=admin_headers)
        assert r_planes.status_code == 200
        assert r_planes.json()["planes_incluidos"] == ["PREMIUM"]
        assert client.post("/api/v1/clases/CLASE-PLAN-01/reservas",
            json={"socio_id": "FIT-C001"}).status_code == 422
        assert client.post("/api/v1/clases/CLASE-PLAN-01/reservas",
            json={"socio_id": "FIT-C005"}).status_code == 200

        # US-016: consulta alertas y verifica un socio con vencimiento dentro del plazo.
        from src.api.main import _ENGINE
        from src.infrastructure.database import SocioRow
        from sqlalchemy.orm import Session
        with Session(_ENGINE) as db:
            socio = db.get(SocioRow, "FIT-C001")
            socio.vigencia_inicio = date.today().isoformat()
            socio.vigencia_fin = (date.today() + timedelta(days=5)).isoformat()
            db.commit()
        r = client.post("/api/v1/reportes/alertas-vencimiento", json={"dias_anticipacion": 7})
        assert r.status_code == 200
        assert r.json()["total_alertas"] >= 1
        assert any(a["socio_id"] == "FIT-C001" for a in r.json()["alertas"])

        # US-020: rechaza suplente ocupado en el mismo horario y luego encola avisos.
        assert client.post("/api/v1/clases", json={
            "clase_id": "CLASE-INSTRUCTOR-OCUPADO", "disciplina": "Pilates",
            "horario": horario_demo, "capacidad_maxima": 5,
            "instructor_id": "INST-BUSY",
        }).status_code == 201
        r_conflicto = client.post("/api/v1/clases/CLASE-REC-01/reasignar-instructor",
            json={"nuevo_instructor_id": "INST-BUSY"}, headers=admin_headers)
        assert r_conflicto.status_code == 409
        r_reasig = client.post("/api/v1/clases/CLASE-REC-01/reasignar-instructor",
            json={"nuevo_instructor_id": "INST-REC2"}, headers=admin_headers)
        assert r_reasig.status_code == 200
        assert r_reasig.json()["notificaciones_en_cola"] == 1

        # US-010: cancelar encola avisos a socios y administración y ofrece clases similares.
        instructor_suplente = {"X-Staff-Role": "INSTRUCTOR", "X-Staff-Token": "test-inst-secret", "X-Staff-Id": "INST-REC2"}
        r_cancelacion = client.post("/api/v1/clases/CLASE-REC-01/cancelar-instructor",
            json={"motivo": "Incapacidad médica"}, headers=instructor_suplente)
        assert r_cancelacion.status_code == 200
        assert r_cancelacion.json()["socios_notificados_en_cola"] == 1
        assert r_cancelacion.json()["notificacion_admin_en_cola"] is True

        assert client.get("/api/v1/notificaciones/pendientes", headers=recepcion_headers).status_code == 403
        r_outbox = client.get("/api/v1/notificaciones/pendientes", headers=admin_headers)
        assert r_outbox.status_code == 200
        assert r_outbox.json()["total"] >= 3


def test_staff_routes_fail_closed_when_role_token_is_not_configured(monkeypatch):
    monkeypatch.delenv("FITZONE_STAFF_TOKEN_RECEPCION", raising=False)
    headers = {
        "X-Staff-Role": "RECEPCION",
        "X-Staff-Token": "any-token",
        "X-Staff-Id": "REC-01",
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/clases/CLASE-NO-EXISTE/reservas/recepcion",
            json={"socio_id": "FIT-C001", "empleado_id": "REC-01"},
            headers=headers,
        )
    assert response.status_code == 503



def test_login_demo_accounts_and_signed_role_sessions(monkeypatch):
    monkeypatch.setenv("FITZONE_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("FITZONE_DEMO_ADMIN_USER", "admin")
    monkeypatch.setenv("FITZONE_DEMO_ADMIN_PASSWORD", "admin-pass")
    monkeypatch.setenv("FITZONE_DEMO_RECEPCION_USER", "recepcion")
    monkeypatch.setenv("FITZONE_DEMO_RECEPCION_PASSWORD", "recepcion-pass")
    monkeypatch.setenv("FITZONE_DEMO_INSTRUCTOR_USER", "instructor")
    monkeypatch.setenv("FITZONE_DEMO_INSTRUCTOR_PASSWORD", "instructor-pass")
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={"usuario": "admin", "contrasena": "bad"}).status_code == 401
        login = client.post("/api/v1/auth/login", json={"usuario": "admin", "contrasena": "admin-pass"})
        assert login.status_code == 200
        data = login.json()
        assert data["rol"] == "ADMIN"
        assert data["id"] == "ADMIN-01"
        headers = {"Authorization": "Bearer " + data["access_token"]}
        assert client.get("/api/v1/auth/me", headers=headers).json()["rol"] == "ADMIN"
        assert client.post("/api/v1/clases", json={
            "clase_id": "CLASE-LOGIN-01", "disciplina": "Yoga",
            "horario": "2026-11-08 10:00", "capacidad_maxima": 8,
        }, headers=headers).status_code == 201
        recepcion = client.post("/api/v1/auth/login", json={"usuario": "recepcion", "contrasena": "recepcion-pass"}).json()
        assert client.post("/api/v1/clases", json={
            "clase_id": "CLASE-LOGIN-02", "disciplina": "Yoga",
            "horario": "2026-11-08 11:00", "capacidad_maxima": 8,
        }, headers={"Authorization": "Bearer " + recepcion["access_token"]}).status_code == 403
        assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_bulk_demo_vigency_assigns_only_missing_memberships(monkeypatch):
    monkeypatch.setenv("FITZONE_STAFF_TOKEN_ADMIN", "test-admin-secret")
    headers = {"X-Staff-Role": "ADMIN", "X-Staff-Token": "test-admin-secret", "X-Staff-Id": "ADMIN-01"}
    with TestClient(app) as client:
        client.post("/api/v1/seed")
        start = (date.today() - timedelta(days=1)).isoformat()
        end = (date.today() + timedelta(days=29)).isoformat()
        assert client.put("/api/v1/socios/FIT-C001/vigencia", json={
            "fecha_inicio": start, "fecha_fin": end
        }, headers=headers).status_code == 200
        response = client.post("/api/v1/socios/vigencias-demo", headers=headers)
        assert response.status_code == 200
        assert response.json()["actualizados"] == 39
        socio = client.get("/api/v1/socios/FIT-C001").json()
        assert socio["vigencia_inicio"] == start
        assert socio["vigencia_fin"] == end
        assert client.post("/api/v1/socios/vigencias-demo", headers=headers).json()["actualizados"] == 0


def test_reception_can_register_membership_request(monkeypatch):
    monkeypatch.setenv("FITZONE_STAFF_TOKEN_RECEPCION", "test-reception-secret")
    with TestClient(app) as client:
        client.post("/api/v1/seed")
        headers = {
            "X-Staff-Role": "RECEPCION",
            "X-Staff-Token": "test-reception-secret",
            "X-Staff-Id": "REC-TEST",
        }
        catalog = client.get("/api/v1/catalogo").json()
        plan = next(item for item in catalog if item["habilitado"] and item["capacidad_o_stock"] > 0)
        response = client.post(
            "/api/v1/operaciones",
            headers=headers,
            json={
                "operacion_id": "OP-RECEPCION-TEST",
                "socio_id": "FIT-C001",
                "lineas": [{"recurso_id": plan["recurso_id"], "cantidad": 1}],
                "promocion_activa": False,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["estado"] == "SOLICITADA"
        assert response.json()["actor_id"] == "FIT-C001"
        assert response.json()["canal"] == "RECEPCION"
        duplicate = client.post(
            "/api/v1/operaciones",
            headers=headers,
            json={
                "operacion_id": "OP-RECEPCION-TEST",
                "socio_id": "FIT-C001",
                "lineas": [{"recurso_id": plan["recurso_id"], "cantidad": 1}],
            },
        )
        assert duplicate.status_code == 409
