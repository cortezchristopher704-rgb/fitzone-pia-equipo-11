# Documento de Arquitectura y Decisiones Técnicas (DDD + UML + SOLID + ADRs)

**Proyecto:** FitZone — Sistema Integral de Gestión de Membresías, Accesos y Reservación de Clases  
**Curso:** Componentes de Lógica de Negocio · **PIA Equipo 11**  
**Integrantes:** Christopher Cortez Garcia (2159313), Oscar Elias Vera Moreno (2160859), Christofer Aaron Torres Puga (2159639)  

---

## 1. Selección y Justificación del Patrón de Lógica de Negocio

Para resolver las problemáticas operativas de FitZone (fuga de capacidad por *no-shows*, listas de espera FIFO con ventana de 30 minutos, límites por plan y contrataciones de membresías con reglas combinatorias), se evaluaron los tres patrones arquitectónicos clásicos de Martin Fowler:

| Criterio de Evaluación (FitZone) | Transaction Script | Table Module | Domain Model (Elegido) | Evidencia de Trazabilidad (U2/U3) |
|---|---|---|---|---|
| **Complejidad condicional de reglas** | **Inadecuado:** Duplicaría reglas de *cut-off* (3h), bloqueo de 7 días y composición de *Specifications* en cada endpoint. | **Parcial:** Centraliza por tabla, pero falla en reglas que cruzan `Socio`, `PlanDeportivo`, `OperacionMembresia` y `ClaseProgramada`. | **Óptimo:** Encapsula invariantes matemáticos, máquina de estados y *Specifications* dentro de entidades ricas en memoria. | BRD N1–N4; US-001 a US-020. |
| **Protección de invariantes y concurrencia** | **Deficiente:** Consultas secuenciales vulnerables a sobreventa de cupo (*race conditions*). | **Deficiente:** No garantiza que la cancelación libere el lugar y promueva al socio en espera en un solo límite de consistencia. | **Óptimo:** El Aggregate Root `ClaseProgramada` protege su propio cupo y gestiona autónomamente su `ListaDeEspera` FIFO. | BRD N2, N3; US-003, US-004, US-005. |
| **Mantenibilidad y pruebas unitarias (FIRST)** | **Baja:** Obliga a probar acoplado a base de datos o framework HTTP. | **Media:** Acoplado a estructuras tabulares/ORM. | **Alta:** Dominio 100% libre de dependencias de infraestructura; permite pruebas unitarias en `< 5 ms`. | Unidad 5: Pirámide de pruebas 70/20/10. |

---

## 2. Diseño Orientado al Dominio (DDD) y Mapa Táctico

### 2.1 Elementos Tácticos del Dominio (`src/domain/`)

1. **Value Objects (Inmutables `@dataclass(frozen=True)`):**
   - `Money(amount: Decimal, currency: str = "MXN")`: Garantiza aritmética decimal exacta, prohíbe `float` y rechaza montos negativos o infinitos.
   - `Vigencia(fecha_inicio: date, fecha_fin: date)`: Valida que `fecha_fin >= fecha_inicio` y calcula elegibilidad temporal de acceso.
   - `LineaOperacion(recurso_id: str, descripcion: str, precio_unitario: Money, cantidad: int)`: Protege que `cantidad > 0` y calcula su subtotal exacto.
2. **Entidades y Aggregates (Raíces de Consistencia):**
   - **Aggregate Root 1 — `OperacionMembresia`:** Gobierna el ciclo de vida contractual de los planes deportivos adquiridos por un `Socio` (`SOLICITADA` → `ACTIVA` → `SUSPENDIDA` → `VENCIDA`, y `SOLICITADA` → `CANCELADA`). Protege que no se apruebe dos veces, que no se salten estados y que solo se active si satisface la *Specification* compuesta `PuedeProcesarseSpec`.
   - **Aggregate Root 2 — `Socio`:** Gestiona la elegibilidad del cliente, su condición preferente (VIP), el estado de su membresía activa y el contador de inasistencias (*no-shows*). Aplica autónomamente el bloqueo de 7 días para reservas al llegar a 3 *no-shows* mensuales sin bloquear el acceso físico al gimnasio.
   - **Aggregate Root 3 — `ClaseProgramada`:** Única frontera transaccional para interactuar con las `Reserva`s y la `ListaDeEspera` de una sesión. Protege que las reservas confirmadas jamás superen `capacidad_maxima`, deriva automáticamente a lista de espera FIFO cuando `cupo_disponibles == 0`, aplica la regla de *cut-off* de **3 horas** en cancelaciones de socios y **2 horas** en cancelaciones de instructor.
3. **Specification Pattern (`src/domain/specifications.py`) con Composición Booleana (`&`, `|`, `~`):**
   - `SocioActivoSpec`: Verifica que el socio esté activo (`activo == True`).
   - `DetalleNoVacioSpec`: Verifica que la operación tenga al menos una línea (`len(lineas) > 0`).
   - `RecursosHabilitadosYConStockSpec`: Verifica que cada plan deportivo solicitado esté `habilitado == True` y con `cantidad <= capacidad_o_stock`.
   - `OperacionAutorizadaSpec`: Verifica que la solicitud cuente con bandera `autorizado == True`.
   - **Regla Compuesta 1 (`PuedeProcesarseSpec`):** `SocioActivoSpec() & DetalleNoVacioSpec() & RecursosHabilitadosYConStockSpec() & OperacionAutorizadaSpec()`
   - `SocioPreferenteSpec`: Verifica si el socio es VIP (`es_preferente == True`).
   - `MontoMinimoSpec(Decimal("1500.00"))`: Verifica si el total de la operación es `>= $1,500.00 MXN`.
   - `PromocionActivaSpec`: Verifica si la operación ya cuenta con una promoción activa (`promocion_activa == True`).
   - **Regla Compuesta 2 (`BeneficioPreferenteSpec`):** `SocioPreferenteSpec() & MontoMinimoSpec(Decimal("1500.00")) & ~PromocionActivaSpec()` (usa operadores `AND` y `NOT`).
   - **Regla Compuesta 3 (`ElegibleParaReservarClaseSpec`):** `SocioActivoSpec() & SocioSinBloqueoSpec() & CupoDeReservasPorPlanSpec()`.
4. **Domain Services:**
   - `ServicioDeInscripcionExtraordinaria`: Orquesta la inscripción *Drop-in* (US-019) validando pago único y confirmando lugar en `ClaseProgramada` sin alterar el plan base del socio.
5. **Domain Events (`src/domain/events.py`):**
   - `OperacionActivada`, `OperacionCancelada`, `OperacionSuspendida`, `MembresiaVencida`, `BeneficioAplicado`, `ReservaConfirmada`, `SocioEnListaDeEspera`, `LugarLiberadoEnClase`, `SocioBloqueadoPorInasistencia`, `AccesoFisicoPermitido`, `AccesoFisicoDenegado`, `ClaseCanceladaPorInstructor`.

---

## 3. Aplicación Demostrable de los Principios SOLID

| Principio SOLID | Aplicación en FitZone y Hallazgo Corregido | Ubicación en Código |
|---|---|---|
| **S — Single Responsibility Principle (SRP)** | `ReservaAppService` y `MembresiaAppService` solo coordinan transacciones y delegan notificaciones a `NotificadorPort`. Las reglas de aforo, sanciones y *Specifications* viven exclusivamente en `src/domain/`. | `src/application/services.py`, `src/domain/models.py` |
| **O — Open/Closed Principle (OCP)** | El patrón `Specification` permite agregar nuevas políticas comerciales o de elegibilidad combinando objetos con `&`, `|`, `~` sin modificar el código interno de `OperacionMembresia` ni `Socio`. Asimismo, el umbral de *no-shows* (`max_no_shows=3`) es configurable. | `src/domain/specifications.py` |
| **L — Liskov Substitution Principle (LSP)** | Se descartó crear una subclase `ReservaDropIn(Reserva)` que lanzara excepciones al cancelar; en su lugar, se utilizó el atributo `es_drop_in: bool` dentro de `Reserva`, preservando el contrato uniforme en todo el sistema. | `src/domain/models.py` |
| **I — Interface Segregation Principle (ISP)** | En lugar de un repositorio monolítico gigante, se segregaron interfaces específicas por Aggregate Root: `SocioRepositoryPort`, `CatalogoRepositoryPort`, `OperacionRepositoryPort` y `ClaseProgramadaRepositoryPort`. | `src/application/ports.py` |
| **D — Dependency Inversion Principle (DIP)** | Los servicios de aplicación dependen de puertos abstractos (`Protocol` / `ABC`) definidos en `src/application/ports.py`, nunca de SQLAlchemy o SQLite directamente. | `src/application/ports.py`, `src/infrastructure/repositories.py` |

---

## 4. Architecture Decision Records (ADRs)

### ADR-01: Adoptar Domain Model Puro con Arquitectura Hexagonal
- **Estado:** Aceptada
- **Contexto:** FitZone posee invariantes fuertemente interdependientes (máquina de estados de membresías, *Specifications* booleanas, aforo máximo con lista de espera FIFO y bloqueo disciplinario por 3 *no-shows*).
- **Alternativas consideradas:** *Transaction Script* (descartado por duplicación de validaciones y riesgo de condiciones de carrera) y *Table Module* (descartado por acoplamiento a tablas relacionales).
- **Decisión:** Implementar un *Domain Model* puro en `src/domain/` desacoplado de la persistencia (`src/infrastructure/`) y del transporte HTTP (`src/api/`).
- **Consecuencias:** El núcleo de negocio se puede probar de forma aislada y reutilizar desde scripts por lotes (CSVs) o la API REST FastAPI. La cobertura global y los escenarios cubiertos se reportan en los resultados de pytest; no se afirma cobertura absoluta.

### ADR-02: Patrón Unit of Work para delimitar transacciones compuestas
- **Estado:** Aceptada
- **Contexto:** En CU-03 (Cancelación anticipada), liberar el cupo de un socio y promover automáticamente al primer socio de la lista de espera FIFO deben confirmarse como una única operación atómica. Lo mismo aplica al aprobar una `OperacionMembresia` descontando stock del catálogo.
- **Alternativas consideradas:** Ejecutar `commit()` individuales por cada tabla modificada (riesgo de dejar aforos corruptos o lugares huérfanos ante un fallo intermedio).
- **Decisión:** Implementar control transaccional explícito (`commit` / `rollback`) en la capa de repositorio SQLAlchemy, asegurando que cualquier excepción de dominio revierta íntegramente la sesión.
- **Consecuencias:** El Unit of Work centraliza commit/rollback y cuenta con pruebas de persistencia y reversión; la concurrencia requiere controles adicionales.

### ADR-03: Aplicar CQRS Básico en Consultas de Disponibilidad y Analítica
- **Estado:** Aceptada
- **Contexto:** Mientras los *Commands* de reserva, cancelación, aprobación y sanción exigen cargar Aggregates completos y verificar invariantes, las consultas masivas de disponibilidad de clases (US-002) y reportes administrativos de ocupación y *no-shows* (US-014, US-015) son de solo lectura.
- **Decisión:** Separar los métodos de consulta rápida (`ReportesQueryService`) de los servicios transaccionales de comando (`MembresiaAppService`, `ReservaAppService`).
- **Consecuencias:** Lecturas rápidas y desacopladas sin comprometer la protección de invariantes en la escritura.

### ADR-04: Uso de `Decimal` y `Specification Pattern` para Reglas Comerciales y Paquete de Datos Oficial
- **Estado:** Aceptada
- **Contexto:** El paquete oficial de pruebas de FitZone (`11_FitZone.zip`) requiere evaluar 60 operaciones (`FIT-O001` a `FIT-O060`), 120 casos de prueba (`FIT-T001..060` y `FIT-B001..060`) y 20 transiciones de máquina de estados (`FIT-S001..020`) con importes en pesos mexicanos (MXN).
- **Decisión:** Utilizar el Value Object `Money` basado exclusivamente en `decimal.Decimal` y modelar `validar_operacion` y `evaluar_beneficio` mediante composición de objetos `Specification` (`&`, `|`, `~`).
- **Consecuencias:** Cero errores de redondeo binario y trazabilidad directa 1 a 1 entre las reglas del CSV oficial, el BRD y los tests automatizados.

---

## 5. Diagramas de Arquitectura Incluidos
En el directorio `docs/architecture/diagrams/` se encuentran los diagramas del proyecto:
1. `diagrama_bpmn.png`: Proceso de negocio con carriles (*swimlanes*); los subprocesos ampliados de membresía/acceso, reservas FIFO y asistencia/instructor se incluyen en `docs/phase2/diagrams/`.
2. `diagrama_dominio.png`: Mapa táctico DDD con Aggregates, Entities, Value Objects y Domain Events.
3. `diagrama_clases.png`: Diagrama de clases UML de las capas (`domain`, `application`, `infrastructure`, `api`).
4. `diagrama_secuencia_1_reserva_fifo.png`: Diagrama de secuencia UML del flujo de reserva, lista de espera FIFO y promoción por cancelación.
5. `diagrama_secuencia_2_noshow_sancion.png`: Diagrama de secuencia UML del registro de *no-show* y bloqueo de reservas.
6. `diagrama_arquitectura_capas.png`: Vista de alto nivel de la interacción entre cliente, API, aplicación, dominio e infraestructura.
7. `diagrama_maquina_estados.png`: Transiciones de `OperacionMembresia` y errores de transición/precondición.

Los archivos editables `diagrama_arquitectura_capas.dot` y `maquina_estados.mmd` acompañan a sus respectivas imágenes para facilitar futuras modificaciones. Los diagramas representan el diseño documentado y deben mantenerse sincronizados con la implementación.


---

## Revisión Fase 2 — Alcance real de las decisiones

- El modelo actual contiene los Aggregate Roots `Socio`, `OperacionMembresia` y `ClaseProgramada`. `Reserva` se administra como entidad interna de `ClaseProgramada`; no hay una clase agregada independiente `ListaDeEspera`. La espera FIFO se representa mediante `ClaseProgramada.lista_espera` (lista de identificadores).
- Las interfaces de instructor mencionadas en versiones conceptuales anteriores no existen en `src/application/ports.py`. Los puertos reales son `SocioRepositoryPort`, `CatalogoRepositoryPort`, `OperacionRepositoryPort`, `ClaseProgramadaRepositoryPort`, `UnitOfWorkPort`, `NotificadorPort`, `TorniquetePort` y `PasarelaPagoPort`.
- ADR-02 debe interpretarse como uso de commit/rollback mediante Unit of Work. No prueba ausencia de condiciones de carrera ni garantiza por sí solo serialización/concurrencia segura. Falta implementar y probar locking o versionado optimista en PostgreSQL.
- NotificadorPort, TorniquetePort y PasarelaPagoPort son contratos; la presencia del protocolo no demuestra que exista un proveedor externo conectado.
- La expiración de promoción dispone de lógica de dominio y endpoint de procesamiento, pero falta un scheduler/worker que lo invoque automáticamente.


---

## Revisión Fase 2 — Alcance real de las decisiones

- El modelo actual contiene los Aggregate Roots `Socio`, `OperacionMembresia` y `ClaseProgramada`. `Reserva` se administra como entidad interna de `ClaseProgramada`; no hay una clase agregada independiente `ListaDeEspera`. La espera FIFO se representa mediante `ClaseProgramada.lista_espera` (lista de identificadores).
- Las interfaces de instructor mencionadas en versiones conceptuales anteriores no existen en `src/application/ports.py`. Los puertos reales son `SocioRepositoryPort`, `CatalogoRepositoryPort`, `OperacionRepositoryPort`, `ClaseProgramadaRepositoryPort`, `UnitOfWorkPort`, `NotificadorPort`, `TorniquetePort` y `PasarelaPagoPort`.
- ADR-02 debe interpretarse como uso de commit/rollback mediante Unit of Work. No prueba ausencia de condiciones de carrera ni garantiza por sí solo serialización/concurrencia segura. Falta implementar y probar locking o versionado optimista en PostgreSQL.
- NotificadorPort, TorniquetePort y PasarelaPagoPort son contratos; la presencia del protocolo no demuestra que exista un proveedor externo conectado.
- La expiración de promoción dispone de lógica de dominio y endpoint de procesamiento, pero falta un scheduler/worker que lo invoque automáticamente.


## Actualización de implementación — 4 de noviembre de 2026

- El worker `src/jobs/worker.py` procesa promociones expiradas y membresías vencidas automáticamente; el ciclo corre con intervalo configurable.
- `procesar_membresias_vencidas()` desactiva socios fuera de vigencia, vence operaciones ACTIVA/SUSPENDIDA, cancela reservas y promociones pendientes, libera cupos y promueve la lista FIFO.
- La tabla `notificaciones_outbox` y `SqlOutboxNotificador` persisten avisos para socios y administración. No existe aún adaptador de entrega por correo/SMS/Push.
- La reasignación de instructor rechaza coincidencias exactas de inicio en el calendario actual; no reemplaza un directorio ni un calendario completo de disponibilidad.
- La API administrativa `GET /api/v1/notificaciones/pendientes` consulta la cola pendiente.
- Las notas previas que indicaban que no existía worker se consideran supersedidas por esta actualización.
