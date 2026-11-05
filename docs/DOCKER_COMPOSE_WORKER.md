# Ejecución local con Docker Compose y worker

## Objetivo

Levantar el entorno integrado del PIA con PostgreSQL, API REST y worker de tareas programadas. El servicio `tests` ejecuta la suite dentro de un contenedor independiente.

## Requisitos

- Docker Desktop instalado y en ejecución (Windows, macOS o Linux).
- Git para clonar el repositorio.
- Puertos locales `5432` (PostgreSQL) y `8000` (API) disponibles.

## Preparación en Windows PowerShell

Desde la carpeta raíz del repositorio:

```powershell
Copy-Item .env.example .env
```

Abre `.env` y cambia `POSTGRES_PASSWORD` por una contraseña local propia. Las variables `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` son las que utiliza Compose para PostgreSQL. La API y el worker apuntan explícitamente al servicio `db`; el valor SQLite de `DATABASE_URL` del ejemplo se conserva para ejecutar la aplicación fuera de Docker.

## Construir y levantar los servicios

```powershell
docker compose config
docker compose up --build -d db app worker
docker compose ps
```

Comprobar la API:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Abrir Swagger UI en el navegador: <http://localhost:8000/docs>

## Cargar los datos de demostración

En Swagger, ejecutar `POST /api/v1/seed`. Este endpoint carga los datos académicos de demostración (socios, planes, operaciones y clases) en la base PostgreSQL del contenedor.

## Comprobar el worker

Consultar los registros:

```powershell
docker compose logs --tail 100 worker
docker compose logs -f worker
```

El worker debe registrar su inicio y ejecutar ciclos con el intervalo definido por `FITZONE_WORKER_INTERVAL_SECONDS` (por defecto, 60 segundos). En cada ciclo revisa membresías vencidas y promociones de lista de espera expiradas. A la hora configurada en `FITZONE_ALERTA_HORA` genera el resumen diario de membresías próximas a vencer y lo guarda en la outbox de notificaciones.

La bandeja outbox conserva los avisos en PostgreSQL para su consulta. **No envía correos ni SMS**: para entrega externa hace falta integrar y configurar un proveedor.

## Ejecutar pruebas en contenedor

```powershell
docker compose run --rm tests
```

El contenedor de pruebas utiliza SQLite aislado y exige al menos 80 % de cobertura. No modifica los datos PostgreSQL de la aplicación.

## Detener el entorno

```powershell
docker compose down
```

Para eliminar también el volumen de PostgreSQL (esto borra los datos locales de demostración):

```powershell
docker compose down -v
```

## Evidencias recomendadas para el reporte

1. Salida de `docker compose ps` con `db`, `app` y `worker` en ejecución.
2. Respuesta de `/health` y captura de Swagger UI.
3. Logs del worker mostrando el inicio y al menos un ciclo de ejecución.
4. Resultado de `docker compose run --rm tests` con el porcentaje de cobertura.
5. Consulta de notificaciones pendientes en Swagger después de que el worker genere una alerta, cuando existan membresías dentro de la ventana configurada.

## Validación automatizada

El workflow de GitHub Actions también ejecuta `docker compose config`, construye las imágenes, levanta PostgreSQL/API/worker, consulta `/health`, ejecuta las pruebas en el contenedor `tests` y limpia los contenedores. La ejecución exitosa de ese workflow es evidencia de integración reproducible en el runner de CI; no sustituye las capturas de una ejecución local en el equipo del estudiante.
