# Auditoría de cumplimiento — FitZone PIA

## Cambios documentales incorporados en esta revisión
- Se añadieron P13–P15 como preguntas pendientes de validación; no se inventaron respuestas.
- Se amplió el glosario del reporte final a 20 términos.
- Se corrigió la métrica de cobertura del reporte a 91.49% sobre 1,646 sentencias (140 no cubiertas), conforme a la ejecución reproducida de 31 pruebas.
- Se corrigió la conclusión individual que todavía mencionaba 27 pruebas y 92.64%.
- Se eliminaron pies de figura obsoletos y repeticiones de los pies de los anexos.
- Se sustituyó la referencia a una captura de terminal no incrustada por referencias a los CSV de resultados reproducibles.

## Pendientes que requieren intervención del equipo

### Bloqueantes para considerar la entrega completa
1. Sincronizar este contenido corregido con el repositorio GitHub. La versión pública revisada no muestra todavía `.github/workflows`, `docker-compose.yml`, `.env.example`, `Dockerfile` ni `pyproject.toml`, y su README aún describe la Actividad 3.
2. Ejecutar Docker Compose en una máquina con Docker, verificar PostgreSQL + API + tests + worker y guardar evidencia real.
3. Desplegar la aplicación en Railway, Render, Fly.io o equivalente; incorporar URL pública y comprobar Swagger UI/OpenAPI en producción.
4. Completar el BPMN: el diagrama actual es un flujo simplificado, no un BPMN 2.0 completo, y no integra todos los procesos y excepciones de las historias.
5. Completar la entrevista simulada: P13–P15 están marcadas pendientes y requieren respuestas confirmadas.

### Brechas funcionales a priorizar
6. La vigencia ya cuenta con captura administrativa y tanto el acceso como la reserva se deniegan cuando falta. El CSV oficial de actores no contiene fechas de inicio/fin; el equipo debe registrar las fechas contractuales reales de los socios de demostración mediante `PUT /api/v1/socios/{id}/vigencia`. No inventar fechas.
7. US-009: corregido en esta revisión; la consulta del instructor ahora incluye confirmados, asistidos y socios en lista de espera.
8. US-015: ya se calcula tasa histórica de no-shows sobre reservas ASISTIDA/NO_SHOW. Pendiente: filtro seleccionable por periodo y almacenamiento histórico independiente de las reservas.
9. US-005/010/016/020: configurar un proveedor real de notificaciones si se exige entrega por correo/SMS; la outbox por sí sola no envía mensajes.
10. US-019: configurar un adaptador real de pago o documentar claramente el alcance simulado, según lo que acepte el docente.
11. Implementar control de concurrencia en PostgreSQL y pruebas para dos solicitudes simultáneas por el último cupo.
12. Fortalecer autenticación de personal con usuarios/sesiones individuales y auditoría persistente si el alcance de seguridad lo exige.

## Verificaciones reproducidas
- `python -m pytest --cov=src --cov-report=term-missing -q`: 31 pruebas aprobadas; cobertura total 91.49%.
- Acceso y reserva sin vigencia registrada: denegados; vigencia registrada por ADMIN: probada.
- Reporte no-show: probado con 3 inasistencias históricas y tasa de 100%.
- `python -m compileall -q src tests`: compilación correcta.
- `docker-compose.yml`: YAML parseable con servicios `db`, `app`, `tests` y `worker`.
- Docker y Ruff no estaban disponibles en el entorno de revisión; no se afirma que Docker Compose se haya levantado ni que Ruff haya pasado.


## Trabajo que aún requiere al equipo
- Registrar fechas reales de vigencia para los socios usados en la demostración. El paquete oficial no contiene esos datos.
- Ejecutar Docker Compose en un equipo con Docker; este entorno de auditoría no dispone del ejecutable Docker.
- Desplegar la aplicación y comprobar Swagger UI/OpenAPI en la URL pública. Se requieren una cuenta y credenciales del equipo.
- Confirmar con el profesor si acepta el modelo BPMN visual complementado por subprocesos; los diagramas no son un archivo BPMN 2.0 ejecutable.

- Reserva de clase sin vigencia registrada: denegada por regla de dominio; reserva con vigencia válida: probada.
- Se añadieron diagramas de subproceso para completar el mapa BPMN general.
