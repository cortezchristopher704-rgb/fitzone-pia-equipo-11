# FitZone PIA — Fase 1: correcciones técnicas

## Cambios realizados

1. **Lista de espera FIFO y ventana de 30 minutos (US-005 / BRD P7-P8)**
   - La promoción ya no se registra como una reserva confirmada inmediata: usa el estado `PROMOCION_PENDIENTE` y ocupa temporalmente el cupo.
   - Se registra la fecha/hora de expiración de la ventana de confirmación.
   - Se incorporaron operaciones de confirmación y expiración. Al vencer, se libera la plaza y se promueve al siguiente socio FIFO.
   - Endpoints añadidos:
     - `POST /api/v1/clases/{clase_id}/promociones/{socio_id}/confirmar`
     - `POST /api/v1/clases/{clase_id}/promociones/procesar-expiracion`
   - La expiración también se revisa oportunistamente cuando se intenta reservar o cancelar en esa clase.

2. **Asistencia y no-shows (US-011 / US-017 / BRD P6)**
   - La asistencia cambia el estado de la reserva a `ASISTIDA` y no borra los no-shows del mes.
   - El no-show cambia la reserva a `NO_SHOW`, decrementa reservas activas y persiste socio y clase.
   - El contador se reinicia al detectar un nuevo mes calendario, no al registrar asistencia.
   - El tercer no-show mensual inicia un bloqueo de siete días con fecha final persistida.
   - El bloqueo se libera al alcanzar su fecha final y se actualizan los días restantes.
   - Endpoint añadido: `POST /api/v1/clases/{clase_id}/asistencia/{socio_id}`.

3. **Reglas de reservación (US-001 / US-013 / BRD P2-P4)**
   - Se valida que una clase con fecha/hora ISO no esté a más de siete días.
   - Se rechaza al socio de Plan Básico cuando la clase no está incluida en ese plan; se conserva el flujo Drop-in.
   - Se valida la vigencia cuando el socio tiene un objeto `Vigencia` registrado.
   - La vigencia del socio y los campos del bloqueo mensual ahora se persisten en la base de datos.

4. **Drop-in y cancelación tardía (US-004 / US-019)**
   - Drop-in deja de considerarse pagado por defecto cuando no hay pasarela configurada. Sin pasarela o pago confirmado, se rechaza.
   - Una cancelación tardía persiste la cancelación y la sanción antes de devolver el error de negocio.
   - Si la cancelación tardía libera un lugar, se conserva la promoción pendiente y se notifica al siguiente socio.

5. **Vencimiento de membresía (US-018)**
   - Al procesar el vencimiento, las reservas se cancelan y las plazas liberadas pueden promover socios en espera, actualizando el contador del socio promovido y enviando notificación cuando hay notificador configurado.

6. **Persistencia compatible**
   - Se añadieron columnas para vigencia, período de no-shows, fin del bloqueo y datos de promoción pendiente.
   - `make_engine()` aplica una migración aditiva para bases SQLite ya existentes.

## Validación ejecutada

Comando: `pytest -q`

Resultado: **19 pruebas aprobadas, 0 fallidas**.

Comando: `python -m pytest --cov=src --cov-report=term -q`

Resultado de cobertura medido antes de añadir la última prueba de reglas de reservación: **95.04%** (superior al mínimo de 80% solicitado). Se recomienda volver a generar el reporte de cobertura al congelar la versión final.

## Pendientes que requieren decisión o infraestructura externa

- **Datos de vigencia:** `datos/actores.csv` solamente contiene `actor_id`, `nombre`, `es_preferente`, `activo` y `ciudad`; no proporciona fechas de inicio/fin. No se inventaron fechas. Aunque el dominio y repositorio ya soportan `Vigencia`, los registros sembrados no pueden demostrar vigencia contractual hasta que el equipo obtenga e importe esas fechas.
- **Expiración automática en producción:** el proyecto ya ofrece operación para procesar promociones expiradas, pero aún debe configurarse un worker/cron externo (por ejemplo, tarea programada de la plataforma) para invocarla puntualmente sin depender de que llegue otra petición a esa clase. No afirmar que existe un scheduler autónomo hasta configurarlo y probarlo.
- **Concurrencia de último cupo:** Unit of Work y transacciones no bastan por sí solos para garantizar ausencia de sobreventa bajo solicitudes concurrentes. Se requiere implementar y probar bloqueo de fila o control optimista de versión en el repositorio PostgreSQL antes de declarar esa garantía.
- **Clases con horarios `HH:MM`:** si el campo horario no incluye fecha, no es posible aplicar el límite de siete días. Para el comportamiento verificable, el API debe recibir fecha y hora, por ejemplo `2026-11-06 09:00`.
- **Vigencia no es lo mismo que `activo`:** el indicador booleano de activo no sustituye fechas de contrato. La carga de datos de vigencia debe ser parte del siguiente ajuste de datos y API administrativa.

## Cómo ejecutar

```bash
pip install -r requirements.txt
pytest -q
python -m pytest --cov=src --cov-report=term -q
uvicorn src.api.main:app --reload
```

Swagger local: `http://127.0.0.1:8000/docs`.
