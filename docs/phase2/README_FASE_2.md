# Fase 2 — Corrección documental y trazabilidad FitZone

## Alcance y criterio
Este paquete sustituye las afirmaciones de arquitectura que no correspondían con el código de `fitzone-pia` corregido en Fase 1. Los diagramas se generaron a partir de las clases, servicios, puertos, repositorios y rutas actualmente presentes en `src/`. No representan funcionalidades futuras como si ya existieran.

## Diagramas actualizados
- `diagrams/ddd.png` + `ddd.dot`: agregados y value objects realmente definidos.
- `diagrams/uml.png` + `uml.dot`: capas, servicios, puertos y adaptadores actuales.
- `diagrams/bpmn.png` + `bpmn.dot`: flujo de reserva, espera, promoción, asistencia y no-show. Se documenta el worker que expira promociones automáticamente cada 60 segundos.

## Criterios del modelo
- Aggregate Roots: `Socio`, `OperacionMembresia`, `ClaseProgramada`.
- `Reserva` es una entidad interna administrada por `ClaseProgramada`; no se presenta como agregado independiente.
- `PlanDeportivo` es entidad de catálogo.
- Value Objects: `Money`, `Vigencia`, `LineaOperacion`.
- Domain Events: `DomainEvent` genérico con nombre, entidad, detalles y timestamp.
- Servicios de aplicación: `MembresiaAppService`, `ReservaAppService`, `AsistenciaAppService`, `ControlAccesoAppService`, `ReportesQueryService`.
- Puertos: repositorios, Unit of Work, notificador, torniquete y pasarela de pago.

## Matriz de trazabilidad
La matriz usa tres estados: **Cumple** (flujo representado por código y prueba), **Parcial** (parte del criterio está implementado, pero falta automatización, integración, autorización o cobertura de alcance), **No cumple** (no se encontró caso de uso funcional que satisfaga la historia). La existencia de un método aislado no basta para declarar la historia cumplida.

| Historia | Requisito | Estado | Código / ruta | Prueba existente | Brecha / nota |
|---|---|---|---|---|---|
| US-001 | Reserva con vigencia, plan y cupo | Parcial | ClaseProgramada.reservar(); ReservaAppService.reservar_clase() | test_clase_programada_reserva_fifo_cutoff_and_drop_in; test_reservation_rejects... | El control de clases por plan se limita a incluida_en_plan_basico; no hay catálogo completo de asociaciones. |
| US-002 | Consultar disponibilidad y cobertura del plan | Parcial | GET /api/v1/clases; ClaseProgramada.cupos_disponibles | test_api_end_to_end_flows_and_status_codes | La consulta muestra disponibilidad; inclusión en plan no se calcula para todos los planes. |
| US-003 | Lista de espera con posición FIFO | Cumple en dominio | ClaseProgramada.reservar(); lista_espera.append() | test_clase_programada_reserva_fifo_cutoff_and_drop_in | No se acredita consulta específica de posición mediante endpoint separado. |
| US-004 | Cancelar con ≥3 h sin penalización y liberar cupo | Parcial | ClaseProgramada.cancelar_reserva(); ReservaAppService.cancelar_reserva() | test_clase_programada_reserva_fifo_cutoff_and_drop_in | La API calcula anticipación desde el horario persistido; los campos legacy enviados por el cliente se ignoran. Faltan notificaciones externas y horarios completos para registros heredados. |
| US-005 | Promoción FIFO y ventana de confirmación 30 min | Parcial | confirmar_promocion(); expirar_promocion(); POST .../promociones/procesar-expiracion | test_waitlist_promotion_requires_confirmation_and_expires_fifo | Worker procesa expiraciones FIFO cada 60 s; falta notificación real al socio promovido. |
| US-006 | Verificar vigencia al ingresar | Parcial | Socio.verificar_acceso_fisico(); PUT /api/v1/socios/{id}/vigencia; POST /api/v1/socios/{id}/acceso | test_api_end_to_end_flows_and_status_codes | Deniega acceso si falta vigencia; administración registra fechas contractuales. Falta integración con torniquete físico. |
| US-007 | Mostrar motivo de rechazo | Cumple en dominio/API | verificar_acceso_fisico(); POST /api/v1/socios/{id}/acceso | test_api_end_to_end_flows_and_status_codes | Motivos devueltos por la lógica; interfaz de recepción no incluida. |
| US-008 | Recepción crea reserva manual | Parcial | POST .../reservas/recepcion | Prueba API de recepción | Valida token/rol RECEPCION y empleado autenticado; falta directorio de usuarios y bitácora persistente. |
| US-009 | Instructor consulta padrón de inscritos | Parcial | GET .../instructor/{instructor_id}/lista | Prueba API de instructor | Valida token/rol INSTRUCTOR e instructor asignado; falta directorio de usuarios y bitácora persistente. |
| US-010 | Instructor cancela ≥2 h, notifica y ofrece reagendar | Parcial | POST .../cancelar-instructor; SqlOutboxNotificador; notificaciones_outbox | test_new_use_cases_reception_instructor_capacity_and_expiry_alerts | Encola aviso persistente a cada socio afectado y administración; devuelve clases de la misma disciplina con cupo. Falta entrega externa y confirmación de reagendamiento. |
| US-011 | Registrar asistencia / no-show | Parcial | AsistenciaAppService; POST .../asistencia y .../no-show | test_attendance_updates_reservation_state_without_erasing_monthly_no_shows; test_socio... | La regla de dominio existe; validar que API y persistencia actualicen la misma reserva/socio en todos los escenarios. |
| US-012 | Administrador configura capacidad | Parcial | PATCH .../capacidad | Pruebas API y dominio | Valida token/rol ADMIN y actualiza aforo; falta directorio de usuarios y bitácora persistente. |
| US-013 | Configurar clases incluidas en planes | Parcial | PATCH .../planes-incluidos; ClaseProgramada.actualizar_planes_incluidos() | Prueba API de mapeo de planes | Configura y persiste tipos BASICO/PREMIUM; falta catálogo de productos de plan y panel administrativo. |
| US-014 | Reporte de ocupación | Cumple en consulta | ReportesQueryService.reporte_ocupacion_clases(); GET /api/v1/reportes/ocupacion | test_api_end_to_end_flows_and_status_codes | Reporte agregado disponible; validar filtros por periodo antes de afirmar analítica histórica. |
| US-015 | Reporte de no-shows por socio | Parcial | ReportesQueryService.reporte_no_shows_socios(); GET /api/v1/reportes/no-shows | test_api_end_to_end_flows_and_status_codes | Se muestra contador mensual actual, no tasa porcentual por periodo histórico. |
| US-016 | Alertas de membresías próximas a vencer | Parcial | POST .../alertas-vencimiento + worker diario | Pruebas API y scheduled_tasks | Genera reporte diario en logs; falta notificación al administrador. |
| US-017 | 3 no-shows/mes → bloqueo de reservas 7 días | Cumple en dominio | Socio.registrar_no_show(); actualizar_bloqueo(); ClaseProgramada.registrar_no_show() | test_socio_plan_basico_limit_no_shows_and_physical_access; test_monthly_no_show_counter_resets_by_month_and_block_expires | El contador y bloqueo están en dominio; el envío real de notificación depende de NotificadorPort. |
| US-018 | Vencimiento cancela reservas y libera cupos | Parcial | procesar_membresias_vencidas(); worker de tareas programadas | test_worker_expires_membership_cancels_reservation_and_promotes_fifo; test_membership_expiry_transitions_active_contract_to_expired | El worker desactiva al socio vencido, vence operaciones activas/suspendidas, cancela reservas confirmadas y promociones pendientes y libera cupos; notificación externa aún no integrada. |
| US-019 | Drop-in con pago único | Parcial | ServicioDeInscripcionExtraordinaria; PasarelaPagoPort; ReservaAppService | test_clase_programada_reserva_fifo_cutoff_and_drop_in | Sin pasarela configurada el pago falla de forma segura; falta proveedor real y prueba de cobro integrado. |
| US-020 | Asignar instructor respaldo o cancelar | Parcial | POST .../reasignar-instructor; SqlOutboxNotificador; notificaciones_outbox | test_new_use_cases_reception_instructor_capacity_and_expiry_alerts | Rechaza suplente ocupado en el mismo inicio y encola avisos persistentes; falta calendario completo y entrega externa. |


## Correcciones obligatorias al reporte original
1. Sustituir las Figuras 1–3 por los diagramas incluidos aquí. Los diagramas anteriores describían clases/servicios inexistentes como `ListaDeEspera` agregada independiente, `IInstructorRepository` y `ReservaService`.
2. Sustituir cualquier frase como “fidelidad absoluta”, “100% funcional”, “garantía total de integridad ACID” o “evita condiciones de carrera” por descripciones limitadas a lo que el código y pruebas demuestran. Unit of Work implementa commit/rollback, pero no prueba por sí solo concurrencia serializable ni prevención de sobreventa.
3. No afirmar que hay despliegue productivo, CI/CD de despliegue o notificaciones reales sin URL activa, ejecución del workflow y adaptadores externos configurados.
4. En la primera revisión Fase 2 se obtuvo 95.28% (19 pruebas). Tras Fase 1.5, el worker y US-018 automático, la ejecución reproducida fue **31 pruebas aprobadas y 91.49% de cobertura**. Se verificó que el YAML de Docker Compose es válido; Docker no está instalado en el entorno de revisión.
5. La matriz completa y las brechas por historia están en `MATRIZ_TRAZABILIDAD_FITZONE.md`.

## Brechas que deben quedar explícitas
- US-008 valida token/rol RECEPCION y empleado autenticado; falta directorio de usuarios y bitácora persistente.
- US-009 valida token/rol INSTRUCTOR e instructor asignado; falta directorio de usuarios y bitácora persistente.
- US-012 valida token/rol ADMIN y permite configurar aforo protegiendo reservas activas; sigue faltando directorio de usuarios y auditoría persistente; US-013 cuenta con configuración por tipo de plan, pero no con catálogo de productos de membresía.
- US-016 genera un digest diario y lo persiste en la outbox para ADMIN; falta canal externo de entrega.
- US-005 se procesa automáticamente mediante worker cada 60 segundos; los avisos de promoción se persisten en la outbox, pero la entrega externa al socio sigue pendiente.
- US-010/020 generan notificaciones persistentes y sugerencias de clases similares, pero no hay entrega externa ni validación completa de disponibilidad de instructores; US-019 sigue requiriendo pasarela real.
- La vigencia es obligatoria para permitir acceso físico y reservar clases. Si no hay fechas registradas, el sistema rechaza el acceso/reserva; administración debe capturar fechas contractuales reales mediante `PUT /api/v1/socios/{actor_id}/vigencia`. El CSV oficial no contiene esas fechas.
- La API calcula el cut-off desde el horario persistido para cancelación de socio e instructor; los campos legacy enviados por el cliente se ignoran. Los horarios heredados HH:MM se interpretan como la siguiente ocurrencia.

## Resultado de pruebas reproducido
Fase 2 inicial: `19 passed`, cobertura `95.28%`. Fase 1.5 inicial: `21 passed`, cobertura `94.82%`. Tras incorporar worker, pruebas adicionales y cálculo de cut-off desde el horario: `31 passed`, cobertura `91.41%`. Los resultados no demuestran integración externa, identidad individual del personal, auditoría ni ejecución productiva.

## Avance Fase 1.5
- US-008: ruta `POST /api/v1/clases/{clase_id}/reservas/recepcion` registra `empleado_id` y canal RECEPCION.
- US-009: ruta `GET /api/v1/clases/{clase_id}/instructor/{instructor_id}/lista` valida que el instructor coincida con el asignado y devuelve socios con reserva confirmada/asistida.
- US-012: ruta `PATCH /api/v1/clases/{clase_id}/capacidad`; el dominio impide capacidad menor que reservas activas.
- US-016: ruta `POST /api/v1/reportes/alertas-vencimiento` consulta socios activos cuyo vencimiento cae dentro de N días; el worker genera el digest diario y lo persiste en la outbox para ADMIN.
- La cobertura se mantiene por encima del 80%: 91.49% con 31 pruebas aprobadas.


## Worker de tareas programadas

El servicio `worker` se ejecuta junto con la API y PostgreSQL mediante `docker compose up --build`. Revisa promociones pendientes cada 60 segundos y genera diariamente el listado de membresías que vencen dentro del umbral configurado. La configuración está en `.env.example`: `FITZONE_WORKER_INTERVAL_SECONDS`, `FITZONE_ALERTA_HORA` y `FITZONE_ALERTA_DIAS`. Para revisar alertas, consultar los logs del servicio (`docker compose logs -f worker`). El registro `ALERTAS_VENCIMIENTO` es una salida operativa estructurada, no un correo/SMS enviado. Ejecutar una sola réplica del worker hasta implementar bloqueo distribuido.


### Acceso de personal

Las rutas de recepción, instructor y administrador requieren `X-Staff-Role`, `X-Staff-Token` y `X-Staff-Id`. Los tokens se configuran mediante `FITZONE_STAFF_TOKEN_RECEPCION`, `FITZONE_STAFF_TOKEN_INSTRUCTOR` y `FITZONE_STAFF_TOKEN_ADMIN`. Son claves compartidas por rol para el alcance académico; no sustituyen un directorio de usuarios, sesiones individuales ni auditoría persistente.


## Cambios posteriores de funcionalidad
- Se reforzó la invariante de reserva: no se puede reservar sin vigencia registrada y vigente, incluso si el socio aparece activo en el CSV.
- El endpoint `PUT /api/v1/socios/{actor_id}/vigencia` permite que un administrador registre el periodo contractual.
- US-015 calcula tasa histórica con estados `ASISTIDA` y `NO_SHOW`; no ofrece todavía filtro temporal.
- Se agregaron tres diagramas de subproceso para complementar el BPMN general: membresía/acceso, reserva/FIFO y asistencia/continuidad de instructor.
- Resultado final reproducido de esta revisión: **31 pruebas aprobadas; 91.49% de cobertura**.
