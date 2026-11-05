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
- **Aplicación web FitZone (Producción en Render):** `https://fitzone-api-kavw.onrender.com/`
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
4. **Calidad y Producción:** Suite de pruebas unitarias e integración con **91.43% de cobertura verificada en 34 pruebas** (superando el mínimo obligatorio de 80%), workflow de CI en GitHub Actions (`.github/workflows/ci.yml`), configuración de Docker Compose con **PostgreSQL (`db`), API (`app`), pruebas (`tests`) y worker (`worker`)**, y configuración 12-Factor App mediante `.env.example`. Docker Compose está definido y su YAML validado, pero debe ejecutarse en un equipo con Docker para confirmar el levantamiento real.

---

## 2. Interfaz web de FitZone
La aplicación web está disponible en la raíz del servicio desplegado. Incluye panel general, consulta de socios, clases programadas, registro/cancelación de reservaciones y reportes de ocupación e inasistencias. La interfaz consume la API REST del mismo servicio; no utiliza datos simulados.

El personal ingresa desde la pantalla **Iniciar sesión** con usuario y contraseña. La API valida las credenciales en el servidor y entrega una sesión firmada de duración limitada; el navegador no recibe ni almacena los secretos de las cuentas. Las cuentas de demostración se configuran mediante variables de entorno en Render.

### Cuentas de demostración para la presentación

| Perfil | Usuario | Contraseña |
|---|---|---|
| Administrador | `admin` | `FitZoneAdmin2026!` |
| Recepción | `recepcion` | `FitZoneRecepcion2026!` |
| Instructor | `instructor` | `FitZoneInstructor2026!` |

Las credenciales anteriores son exclusivas de la demostración académica. Cambiarlas antes de utilizar el sistema con información real. Las cuentas se definen en Render mediante variables `FITZONE_DEMO_*`; las sesiones se firman con `FITZONE_SESSION_SECRET`.
