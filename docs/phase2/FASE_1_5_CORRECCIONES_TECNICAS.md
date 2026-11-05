# Fase 1.5 — Complementación funcional

**Fecha:** 4 de noviembre de 2026  
**Base:** proyecto `fitzone-pia` de Fase 1 corregida + documentación Fase 2.

## Cambios incorporados

| Historia | Implementación | Validación |
|---|---|---|
| US-008 | `POST /api/v1/clases/{clase_id}/reservas/recepcion` registra reserva y devuelve empleado/canal. | Prueba API de recepción. |
| US-009 | `GET /api/v1/clases/{clase_id}/instructor/{instructor_id}/lista` consulta reservas confirmadas/asistidas y valida instructor asignado. | Prueba API de acceso correcto y rechazo 403. |
| US-012 | `PATCH /api/v1/clases/{clase_id}/capacidad`; método de dominio impide aforo no positivo o menor a ocupación. | Prueba unitaria y prueba API. |
| US-013 | `PATCH /api/v1/clases/{clase_id}/planes-incluidos` configura tipos de membresía permitidos y persiste la relación. | Prueba API: BASIC rechazado, PREMIUM aceptado. |
| US-016 | `POST /api/v1/reportes/alertas-vencimiento` lista socios activos con vencimiento dentro de N días; worker genera digest diario y lo persiste en outbox para ADMIN. | Prueba API, `test_daily_expiry_alerts_include_only_active_members_within_window` y `test_worker_daily_alerts_are_persisted_to_admin_outbox`. |
| US-018 | Worker desactiva socios vencidos, vence operaciones activas/suspendidas, cancela reservas y promociones pendientes, libera cupos y promueve FIFO. | `test_worker_expires_membership_cancels_reservation_and_promotes_fifo`; `test_membership_expiry_transitions_active_contract_to_expired`. |
| US-010 | Cancelación encola avisos persistentes para socios y ADMIN; devuelve clases de la misma disciplina con cupo como opciones de reprogramación. | `test_new_use_cases_reception_instructor_capacity_and_expiry_alerts`. |
| US-020 | Reasignación encola avisos a socios y rechaza suplente con otra clase al mismo inicio. | `test_new_use_cases_reception_instructor_capacity_and_expiry_alerts`. |

## Pruebas

Comando:

```bash
python -m pytest --cov=src --cov-report=term-missing -q
```

Resultado reproducido tras incorporar el vencimiento automático de membresías: **31 passed; 91.41% de cobertura**. El umbral configurado del proyecto es 80%.

## Corrección del cut-off de cancelación

La API calcula las horas de anticipación desde el horario persistido de la clase para cancelación de socio e instructor; ignora los campos legacy enviados por el cliente. Para horarios heredados `HH:MM`, toma la siguiente ocurrencia. Se valida con pruebas de API que envían intencionalmente una anticipación falsa de 99 horas frente a una clase a una hora.

## Automatización incorporada

- `src/application/scheduled_tasks.py` implementa los casos de uso para expirar promociones vencidas, desactivar membresías fuera de vigencia, cancelar sus reservas confirmadas/promociones pendientes, retirar socios vencidos de la lista de espera y generar el listado de membresías próximas a vencer.
- Al liberar una reserva por vencimiento, se ofrece el lugar al siguiente socio FIFO y se actualizan los contadores de reservas activas.
- Las operaciones de membresía en estado ACTIVA o SUSPENDIDA pasan a VENCIDA cuando el worker detecta que la vigencia del socio terminó.
- `src/jobs/worker.py` ejecuta el barrido de promociones y membresías vencidas cada 60 segundos (configurable), y genera el reporte de vencimientos una vez al día a la hora configurada.
- `docker-compose.yml` incorpora el servicio `worker`, separado de la API y conectado a la misma base PostgreSQL.
- El digest diario de alertas se guarda también en la outbox para ADMIN y se emite como registro estructurado `ALERTAS_VENCIMIENTO` en los logs. No se afirma envío por correo/SMS: requiere un proveedor externo configurado.

- Las rutas de cancelación por instructor y reasignación también requieren token/rol INSTRUCTOR o ADMIN, respectivamente.


## Notificaciones persistentes para US-010, US-016 y US-020

- Se agregó la tabla `notificaciones_outbox` y el adaptador `SqlOutboxNotificador`, que implementa `NotificadorPort` y guarda destinatario, asunto, mensaje, estado y fecha.
- La cancelación de una clase encola avisos para cada socio afectado y para ADMIN; la respuesta incluye clases futuras de la misma disciplina con cupo como opciones de reprogramación.
- La reasignación encola avisos a los socios con reserva activa y rechaza un suplente ya asignado a otra clase con el mismo inicio programado.
- El worker persiste el digest diario de membresías próximas a vencer para ADMIN.
- `GET /api/v1/notificaciones/pendientes` permite al administrador consultar la cola. La entrega por correo/SMS/Push sigue pendiente de un proveedor externo.
- La comprobación de disponibilidad de suplentes solo detecta coincidencia exacta de inicio; el caso no define duración de clase ni existe un calendario maestro de instructores.

## Limitaciones conocidas

- Las rutas de recepción, instructor y administración validan tokens compartidos por rol mediante variables de entorno. No existe directorio de usuarios ni sesiones individuales; los identificadores individuales siguen siendo datos de cabecera.
- Los avisos de cancelación, reasignación y digest de vencimientos se guardan en `notificaciones_outbox` con estado PENDIENTE. No se entregan por correo/SMS hasta configurar un adaptador externo; el administrador puede consultar la cola mediante `GET /api/v1/notificaciones/pendientes`.
- El worker está diseñado para una sola instancia; ejecutar varias réplicas sin bloqueo distribuido podría procesar dos veces la misma tarea diaria.
- No se pudo ejecutar Docker Compose localmente porque Docker no está instalado en el entorno de revisión. Se validó sintácticamente el YAML de Compose.
- Ruff está declarado como dependencia y paso de CI, pero no pudo ejecutarse localmente porque el ejecutable no está instalado.
- No se afirma despliegue productivo ni integración real con pasarela de pago o torniquete.

## Validación de US-018 (vencimiento automático)

- Se agregó `procesar_membresias_vencidas(session, hoy)` como tarea idempotente del worker.
- La membresía conserva vigencia durante su fecha final y se procesa a partir del día siguiente (`hoy > fecha_fin`).
- Se prueba cancelación de reserva, liberación de cupo, promoción FIFO, contador de reservas, transición de operación ACTIVA a VENCIDA y no reprocesamiento del socio ya inactivo.
- La expiración de una promoción pendiente también descuenta la reserva activa del socio expirado y suma la del siguiente socio promovido.

## Siguiente prioridad

1. Completar y probar cancelación/reasignación de instructor, incluyendo avisos a los socios afectados.
2. Probar PostgreSQL/Docker Compose y CI en un entorno con Docker y Ruff.
3. Revisar integración real de notificaciones y pasarela de pago; no declarar integraciones que no están configuradas.

### Persistencia de inclusión de planes por clase (US-013)

Se agregó `planes_incluidos_json` a `clases_programadas`, con migración aditiva para bases existentes. El repositorio conserva el conjunto configurado y `ClaseProgramada.reservar()` rechaza planes no incluidos; el flujo Drop-in sigue separado. El endpoint `PATCH /api/v1/clases/{clase_id}/planes-incluidos` requiere token/rol ADMIN.
