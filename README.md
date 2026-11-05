# FitZone — Producto Integrador de Aprendizaje (PIA) · Componentes de Lógica de Negocio

**Universidad Autónoma de Nuevo León (UANL) — Facultad de Ingeniería Mecánica y Eléctrica (FIME)**  
**Curso:** Componentes de Lógica de Negocio · **Semestre:** Agosto – Diciembre 2026  
**Profesor:** Miguel Ángel Gómez Marroquín  
**Caso de Negocio Asignado:** Caso 11 — **FitZone** (Gimnasio y Centros de Entrenamiento)  

### Integrantes del Equipo 11
- **Christopher Cortez Garcia** — Matrícula: `2159313`
- **Oscar Elias Vera Moreno** — Matrícula: `2160859`
- **Christofer Aaron Torres Puga** — Matrícula: `2159639`

### Enlaces Oficiales del Proyecto
- **Repositorio de GitHub:** `https://github.com/cortezchristopher704-rgb/fitzone-pia-equipo-11`
- **Documentación Interactiva Swagger UI (Producción en Render):** `https://fitzone-api-kavw.onrender.com/docs`
- **Healthcheck de producción:** `https://fitzone-api-kavw.onrender.com/health`
- **Swagger UI local:** `http://127.0.0.1:8000/docs`
- **Especificación OpenAPI 3.1:** [`docs/api/openapi.json`](docs/api/openapi.json)

---

## 1. Descripción General de la Solución
Este proyecto materializa la solución integral de software basada en lógica de negocio para **FitZone (Caso 11)**, integrando y refinando los artefactos elaborados en las Unidades 2, 3, 4 y 5:
1. **Análisis de Negocio (`docs/BRD.md`):** BRD completo con levantamiento de requerimientos (P1–P12), necesidades N1–N6, **20 Historias de Usuario (US-001 a US-020)** con criterios de aceptación en **Gherkin (`Given/When/Then`)**, modelo de proceso de negocio documentado mediante diagrama **BPMN**, glosario de lenguaje ubicuo y matriz de trazabilidad de extremo a extremo.
2. **Arquitectura DDD + SOLID (`docs/architecture/`):** Diseño Orientado al Dominio (DDD) con 3 *Aggregate Roots* (`OperacionMembresia`, `Socio`, `ClaseProgramada`), *Value Objects* inmutables en `Decimal` (`Money`, `Vigencia`, `LineaOperacion`), **Specification Pattern** con operadores booleanos (`&`, `|`, `~`), **State Machine** con **Domain Events**, **Unit of Work (commit/rollback; la concurrencia requiere controles adicionales)**, **CQRS básico**, aplicación demostrable de los 5 principios **SOLID** y 4 **ADRs**.
3. **Evaluación Completa del Paquete Oficial `11_FitZone.zip`:** Carga automática de los **40 socios** (`actores.csv`), **20 planes deportivos** (`catalogo.csv`), **60 operaciones** (`operaciones.csv` + `detalle_operaciones.csv`), resolución verificada de los **120 casos de prueba** (`casos_prueba.csv` → `resultados/casos_prueba_resueltos.csv`) y las **20 pruebas de transición de estado** (`transiciones_prueba.csv` → `resultados/transiciones_prueba_resueltas.csv`).
4. **Calidad y Producción:** Suite de pruebas unitarias e integración con **91.56% de cobertura verificada en 31 pruebas** (superando el mínimo obligatorio de 80%), workflow de CI en GitHub Actions (`.github/workflows/ci.yml`), configuración de Docker Compose con **PostgreSQL (`db`), API (`app`), pruebas (`tests`) y worker (`worker`)**, y configuración 12-Factor App mediante `.env.example`. Docker Compose está definido y su YAML validado, pero debe ejecutarse en un equipo con Docker para confirmar el levantamiento real.

---

## 2. Estructura del Repositorio

```text
fitzone-pia/
├── docs/
│   ├── BRD.md                                      # BRD + 20 User Stories/Gherkin + Glosario + Trazabilidad
│   ├── architecture/
│   │   ├── ARCHITECTURE_AND_ADRS.md                # DDD, UML, SOLID y ADRs (ADR-01 a ADR-04)
│   │   └── diagrams/                               # BPMN, DDD, UML, arquitectura por capas y máquina de estados
│   └── api/
│       └── openapi.json                            # Especificación OpenAPI 3.1 exportada
├── src/
│   ├── domain/                                     # Núcleo DDD puro (0 dependencias externas)
│   │   ├── models.py                               # Aggregates: Socio, OperacionMembresia, ClaseProgramada
│   │   ├── value_objects.py                        # Money (Decimal), Vigencia, LineaOperacion
│   │   ├── specifications.py                       # Specifications componibles (&, |, ~)
│   │   ├── events.py                               # DomainEvent inmutable
│   │   └── exceptions.py                           # Jerarquía de excepciones de negocio
│   ├── application/                                # Casos de uso (Service Layer + CQRS) y Puertos (ISP/DIP)
│   │   ├── ports.py                                # Interfaces de repositorios, UoW, Torniquete, Pagos
│   │   ├── services.py                             # MembresiaAppService, ReservaAppService, ControlAcceso, CQRS
│   │   └── scheduled_tasks.py                      # Procesos programados de promociones y alertas
│   ├── infrastructure/                             # Adaptadores SQLAlchemy, SQLite/PostgreSQL y lector CSV
│   │   ├── database.py                             # Modelos ORM y configuración por variables de entorno
│   │   ├── repositories.py                         # Repositorios SQL y SqlAlchemyUnitOfWork
│   │   └── csv_loader.py                           # Importador y evaluador de los CSVs de 11_FitZone
│   ├── api/                                        # Controladores HTTP REST con FastAPI
│   │   └── main.py                                 # 31 rutas REST documentadas con traducción de errores (200/201/403/404/409/422)
├── datos/                                          # Archivos CSV oficiales de 11_FitZone
├── resultados/                                     # Salidas resueltas de los 120 casos y 20 transiciones
├── tests/                                          # Suite de pruebas unitarias, CSVs, repositorios y API REST
├── .github/workflows/ci.yml                        # Workflow de CI (Ruff + Pytest + Coverage >= 80%)
├── Dockerfile                                      # Imagen de contenedor de la aplicación
├── docker-compose.yml                              # Orquestación de DB (PostgreSQL) + App (FastAPI) + Tests + Worker
├── .env.example                                    # Variables de entorno de ejemplo (12-Factor App)
├── pyproject.toml                                  # Configuración de Pytest, Coverage y Ruff
├── requirements.txt                                # Dependencias del proyecto
└── README.md                                       # Este documento
```

---

## 3. Instrucciones de Instalación y Ejecución Local

### 3.1 Crear entorno virtual e instalar dependencias
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2 Ejecutar la suite de pruebas y verificar cobertura (>= 80%)
```powershell
pytest -v --cov=src --cov-report=term-missing --cov-report=html:htmlcov --cov-fail-under=80 tests
```

### 3.3 Levantar el servidor API REST y abrir Swagger UI
```powershell
uvicorn src.api.main:app --reload --port 8000
```
- **Swagger UI interactivo:** `http://127.0.0.1:8000/docs`
- **Healthcheck:** `http://127.0.0.1:8000/health`
- Las rutas de recepción, instructor y administración requieren `X-Staff-Role`, `X-Staff-Token` y `X-Staff-Id`; configura `FITZONE_STAFF_TOKEN_RECEPCION`, `FITZONE_STAFF_TOKEN_INSTRUCTOR` y `FITZONE_STAFF_TOKEN_ADMIN` en el entorno. Los tokens de `.env.example` son marcadores y deben reemplazarse.
- **Antes de probar accesos o reservas:** el CSV oficial no contiene fechas de vigencia. Por seguridad, el sistema deniega el acceso físico y las reservas cuando no se han registrado. Un administrador debe capturar las fechas con `PUT /api/v1/socios/{actor_id}/vigencia`.

### 3.4 Registrar la vigencia de un socio (PowerShell)
```powershell
$headers = @{
  "X-Staff-Role" = "ADMIN"
  "X-Staff-Token" = $env:FITZONE_STAFF_TOKEN_ADMIN
  "X-Staff-Id" = "ADMIN-01"
}
$body = @{
  fecha_inicio = "2026-11-01"
  fecha_fin = "2026-12-01"
} | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8000/api/v1/socios/FIT-C001/vigencia" -Headers $headers -ContentType "application/json" -Body $body
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/socios/FIT-C001/acceso"
```
Reemplaza las fechas por las que correspondan al contrato real del socio. No uses fechas de ejemplo como si fueran datos reales.

### 3.5 Reporte de no-shows
```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/reportes/no-shows"
```
El reporte calcula la tasa histórica con reservas que terminaron en `ASISTIDA` o `NO_SHOW`; no incluye reservas pendientes ni canceladas.

---

## 4. Ejecución con Docker Compose (DB + App + Tests)

```powershell
# Copiar archivo de variables de entorno
Copy-Item .env.example .env

# Construir y levantar PostgreSQL + API FastAPI + Contenedor de Pruebas
docker compose up --build
```
El servicio `tests` ejecuta automáticamente la suite completa y verifica que la cobertura supere el 80%, `app` expone la API REST en `http://localhost:8000/docs` conectada a `db`, y `worker` procesa promociones vencidas cada 60 segundos y genera diariamente el reporte de vencimientos. Para revisar el reporte: `docker compose logs -f worker`. Las alertas se registran en logs; no se envían correos/SMS sin configurar un proveedor. Mantener una sola réplica de `worker`.

## Endpoints agregados en la Fase 1

- `POST /api/v1/clases/{clase_id}/asistencia/{socio_id}` — registra asistencia y conserva el contador mensual de no-shows.
- `POST /api/v1/clases/{clase_id}/promociones/{socio_id}/confirmar` — confirma una promoción FIFO pendiente dentro de los 30 minutos.
- `POST /api/v1/clases/{clase_id}/promociones/procesar-expiracion` — procesa la expiración de la promoción y promueve al siguiente socio.

Consulta `docs/FASE_1_CORRECCIONES_TECNICAS.md` para los cambios, la validación y los pendientes que todavía requieren datos o infraestructura externa.
