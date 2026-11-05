# Guía de ejecución y demostración local — FitZone

Esta guía permite demostrar la API en Windows sin GitHub. Requiere Python 3.11 o superior. Docker y despliegue se revisan en una etapa posterior.

## 1. Preparar el proyecto
1. Extrae `FITZONE_Fase2_Auditado.zip`.
2. Abre la carpeta `fitzone-pia` en Visual Studio Code.
3. Abre una terminal PowerShell dentro de esa carpeta.
4. Crea y activa el entorno virtual:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si PowerShell bloquea la activación, ejecuta solo para esa terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 2. Configurar variables de entorno

La aplicación lee las variables del entorno del proceso. Para una demostración local, configura tokens de prueba (no uses estos valores en producción):

```powershell
$env:DATABASE_URL = "sqlite:///./fitzone_pia.sqlite3"
$env:FITZONE_STAFF_TOKEN_ADMIN = "demo-admin-token-cambiar"
$env:FITZONE_STAFF_TOKEN_RECEPCION = "demo-recepcion-token-cambiar"
$env:FITZONE_STAFF_TOKEN_INSTRUCTOR = "demo-instructor-token-cambiar"
```

`.env.example` sirve como plantilla para Docker Compose; la ejecución local desde PowerShell no carga automáticamente ese archivo.

## 3. Ejecutar la API y abrir Swagger

```powershell
uvicorn src.api.main:app --reload --port 8000
```

Abre `http://127.0.0.1:8000/docs`. En otra terminal puedes comprobar `http://127.0.0.1:8000/health`.

En Swagger ejecuta `POST /api/v1/seed` una vez para cargar los datos oficiales de socios, planes y operaciones. La carga inicial no incluye vigencias porque el CSV oficial `actores.csv` no proporciona fechas de inicio/fin.

## 4. Registrar vigencia antes de permitir acceso o reservas

El sistema ahora **deniega el acceso y las reservas** si el socio no tiene una vigencia registrada. Esto evita tratar un socio activo del CSV como si su contrato estuviera vigente sin evidencia.

En Swagger abre `PUT /api/v1/socios/{actor_id}/vigencia` e introduce:

- `actor_id`: identificador real, por ejemplo `FIT-C001`.
- `fecha_inicio`: fecha real de inicio del contrato, formato `AAAA-MM-DD`.
- `fecha_fin`: fecha real de vencimiento, formato `AAAA-MM-DD`.

En los encabezados de la petición agrega:

```text
X-Staff-Role: ADMIN
X-Staff-Token: (el valor de FITZONE_STAFF_TOKEN_ADMIN)
X-Staff-Id: ADMIN-01
```

Ejecuta la operación y confirma que responda `registrada: true`. Después prueba `POST /api/v1/socios/{actor_id}/acceso`. Solo usa fechas de contratos reales o datos de prueba claramente identificados; no copies fechas de ejemplo como datos reales.

Repite el registro para los socios que utilizarás en la demostración de reservas. No es necesario inventar fechas para los 40 registros.

## 5. Flujos que conviene demostrar

1. **Acceso:** un socio sin vigencia recibe `permitido: false`; al registrar una vigencia válida, el acceso se autoriza. Una vigencia vencida se rechaza.
2. **Reserva/FIFO:** crea una clase con capacidad 1; reserva con el primer socio; reserva con un segundo socio y verifica `LISTA_ESPERA`; cancela la primera reserva con al menos 3 horas de anticipación; comprueba la promoción FIFO y la ventana de 30 minutos.
3. **Asistencia/no-show:** registra una reserva y utiliza los endpoints de asistencia o no-show. El tercer no-show mensual bloquea nuevas reservas durante 7 días, sin bloquear el acceso físico si la vigencia sigue activa.
4. **Instructor:** configura tokens de instructor y administrador; prueba la consulta de inscritos, reasignación y cancelación de clase.
5. **Reportes:** consulta `GET /api/v1/reportes/ocupacion` y `GET /api/v1/reportes/no-shows`.

## 6. Ejecutar pruebas

Detén Uvicorn con `Ctrl+C` y ejecuta:

```powershell
python -m pytest --cov=src --cov-report=term-missing -q
```

Resultado verificado en la auditoría del paquete: 31 pruebas aprobadas y 91.49% de cobertura. Si realizas cambios, vuelve a ejecutar las pruebas y conserva la salida como evidencia.

## 7. Docker Compose (pendiente de ejecutar por el equipo)

Cuando tengas Docker Desktop instalado y activo:

```powershell
Copy-Item .env.example .env
# Edita .env y cambia los tokens de ejemplo por valores propios.
docker compose config
docker compose up --build
```

La API quedará en `http://localhost:8000/docs`. El servicio `tests` debe terminar con código 0. Comprueba los servicios con `docker compose ps` y los logs con `docker compose logs -f app worker tests`.

No marques Docker como verificado hasta que los contenedores hayan iniciado correctamente en tu equipo.
