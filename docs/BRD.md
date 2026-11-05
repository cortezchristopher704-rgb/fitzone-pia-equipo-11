# Business Requirements Document (BRD) — FitZone (Caso 11)

**Universidad Autónoma de Nuevo León (UANL) — Facultad de Ingeniería Mecánica y Eléctrica (FIME)**  
**Curso:** Componentes de Lógica de Negocio · **Producto Integrador de Aprendizaje (PIA)**  
**Equipo 11:** Christopher Cortez Garcia (2159313), Oscar Elias Vera Moreno (2160859), Christofer Aaron Torres Puga (2159639)  
**Profesor:** Miguel Ángel Gómez Marroquín  

---

## 1. Contexto del Negocio y Operación Actual (AS-IS)
**FitZone** es una cadena de centros deportivos y gimnasios que comercializa membresías (mensuales, trimestrales, semestrales y anuales), además de clases grupales especializadas (CrossFit, Spinning, Yoga, Box) y entrenamiento personal. Los servicios a los que tiene acceso cada socio dependen del plan contratado.

En la operación tradicional (*AS-IS*), cada socio cuenta con una membresía con fecha de inicio y vencimiento y se identifica en recepción para ingresar. Sin embargo, se identificaron cuatro problemáticas operativas críticas:
1. **Fuga de capacidad por *no-shows*:** Socios que reservan lugares en clases de alta demanda y no asisten, dejando espacios vacíos que otros socios pudieron aprovechar.
2. **Control manual y propenso a errores de listas de espera:** Ausencia de un mecanismo automatizado FIFO con ventana de tiempo para reasignar lugares liberados.
3. **Accesos físicos inconsistentes:** Validaciones manuales en recepción que permiten ingresos ocasionales con membresías vencidas o suspendidas.
4. **Falta de visibilidad analítica:** Dificultad para medir la ocupación real por clase y la tasa de inasistencias por socio.

---

## 2. Levantamiento de Requerimientos (Entrevista con Stakeholder)
Para eliminar ambigüedades antes de diseñar la arquitectura, el Equipo 11 validó las reglas de negocio implícitas con el stakeholder (Administrador de FitZone):

| # | Pregunta formulada al Stakeholder | Respuesta / Regla de Negocio Confirmada |
|---|---|---|
| **P1** | ¿Qué canales puede usar el socio para reservar una clase? | App móvil/web responsiva o presencialmente en recepción (también vía telefónica asistida por recepción). |
| **P2** | ¿Existe un tiempo límite de anticipación para reservar? | Hasta con **7 días de anticipación** máximo para evitar saturar el calendario futuro. |
| **P3** | ¿El instructor puede cancelar una clase por sí mismo? | Sí, pero debe registrarlo y notificar al administrador con al menos **2 horas de anticipación**. |
| **P4** | ¿Cuántas clases simultáneas puede reservar un socio según su plan? | El **Plan Básico** permite máximo **2 reservas activas** simultáneas; el **Plan Premium/Preferente** no tiene límite. |
| **P5** | ¿Hasta cuántas horas antes se puede cancelar una reserva sin penalización? | Hasta **3 horas antes** del inicio de la clase (*Cut-off Time*) sin penalización. Cancelar con menos de 3 horas cuenta como cancelación tardía / falta. |
| **P6** | ¿Cuántos *no-shows* generan sanción o bloqueo? | **3 *no-shows* acumulados en el mes** generan un **bloqueo automático de 7 días** para realizar nuevas reservas de clases (el acceso físico general al gimnasio permanece permitido si la membresía está vigente). |
| **P7** | ¿Cuánto tiempo tiene un socio en lista de espera para confirmar un lugar liberado? | **30 minutos** desde la notificación; si no confirma en esa ventana, el lugar pasa automáticamente al siguiente en la fila. |
| **P8** | ¿Cómo se ordena la lista de espera? | Orden estricto de llegada (**FIFO** — *First-In, First-Out*), sin privilegios comerciales por tipo de plan. |
| **P9** | ¿Qué ocurre con las reservas futuras si vence la membresía del socio? | Se cancelan automáticamente al vencer la membresía y se liberan los cupos hacia la lista de espera. |
| **P10** | ¿Qué pasa cuando un instructor cancela una clase? | Se notifica a los socios inscritos y se ofrece reagendamiento sin costo; no existen reembolsos monetarios unitarios porque las clases son parte de la suscripción. |
| **P11** | ¿Se permite asistir a una clase no incluida en el plan del socio? | Sí, mediante un pago único de acceso extraordinario (**Drop-in**), sin alterar el plan base de su membresía. |
| **P12** | ¿Cuáles son las reglas comerciales de contratación de planes y beneficios VIP? | Toda solicitud de operación/membresía inicia en estado `SOLICITADA`, requiere socio activo, al menos un plan/recurso habilitado con stock disponible y autorización. Los socios **Preferentes (VIP)** con importe total `>= $1,500.00 MXN` y **sin promoción activa** reciben un beneficio del **10% de descuento**. |
| **P13** | ¿Cuál es la duración oficial de cada tipo de clase y cómo se determina la disponibilidad del instructor? | **Pendiente de validar con el stakeholder**; no se asigna una regla sin confirmación. |
| **P14** | ¿Qué canales oficiales se utilizarán para notificar promociones FIFO, cancelaciones y alertas de vencimiento? | **Pendiente de validar con el stakeholder**; el sistema actual conserva avisos en outbox, sin entrega externa. |
| **P15** | ¿Qué datos y evidencias debe conservar recepción al registrar reservas u operaciones para un socio? | **Pendiente de validar con el stakeholder**; falta directorio de usuarios y auditoría persistente. |

---

## 3. Alcance del Proyecto (TO-BE)

### 3.1 Dentro del Alcance
- **Gestión de Operaciones de Membresía y Planes Deportivos:** Alta en estado `SOLICITADA`, validación de precondiciones con *Specification Pattern*, cálculo exacto en `Decimal`, aplicación de beneficios preferentes y máquina de estados completa (`SOLICITADA` → `ACTIVA` → `SUSPENDIDA` → `VENCIDA`, y `SOLICITADA` → `CANCELADA`).
- **Control Automatizado de Accesos Físicos:** Verificación en recepción según estado y vigencia de la membresía. Si no existe vigencia registrada, el acceso se deniega de forma segura. Administración registra las fechas mediante `PUT /api/v1/socios/{id}/vigencia`; se emiten eventos de acceso permitido o denegado. El torniquete físico no está integrado.
- **Módulo de Reservación Dinámica de Clases y Lista de Espera FIFO:** Validación de cupo disponible, límite de reservas simultáneas según plan, inscripción automática en lista de espera cuando `cupo == 0`, cancelación anticipada (`>= 3h`) y promoción automática FIFO con ventana de 30 minutos.
- **Control de Asistencia, *No-Shows* y Bloqueo Disciplinario:** Registro de asistencia por instructor, conteo de inasistencias y bloqueo automático de reservas por 7 días al tercer *no-show* mensual.
- **Continuidad de Servicio y Analítica:** Reasignación de instructor de respaldo, cancelación por instructor (`>= 2h`), acceso *Drop-in* y reportes de ocupación y tasa histórica de *no-shows* calculada sobre reservas con resultado registrado (ASISTIDA o NO_SHOW).

### 3.2 Fuera del Alcance
- Procesamiento de cobros con tarjetas bancarias reales en producción (se aísla mediante puerto `PaymentGateway` / `Mock`).
- Módulo de nómina, contabilidad fiscal y pagos a instructores.

---

## 4. Matriz de Necesidades de Negocio (N1 – N6)

| ID | Necesidad de Negocio | Descripción | Criterio de Éxito Medible |
|---|---|---|---|
| **N1** | Validación Automática de Acceso | Verificar automáticamente la vigencia y estado de la membresía del socio en recepción/torniquete. | 100% de los accesos físicos validados sin intervención manual, indicando motivo exacto en rechazos. |
| **N2** | Gestión de Membresías y Reservas | Permitir contratar planes deportivos, evaluar beneficios VIP y reservar/cancelar clases respetando límites por plan y ventana de *cut-off* (3h). | 0% de sobreventa de capacidad máxima o contrataciones de planes deshabilitados. |
| **N3** | Automatización de Lista de Espera | Administrar cola FIFO cuando una clase agota su cupo y reasignar automáticamente lugares liberados con ventana de 30 min. | 100% de lugares cancelados a tiempo asignados en orden estricto de llegada (FIFO). |
| **N4** | Control de Asistencia y Sanciones | Registrar asistencia/inasistencia y aplicar bloqueo de 7 días para reservas al acumular 3 *no-shows* en el mes. | Reducción de *no-shows* >= 20% en 3 meses y aplicación determinista de sanciones. |
| **N5** | Analítica y Reportes Operativos | Proveer métricas en tiempo real de porcentaje de ocupación por clase, tasa de *no-shows* y alertas de vencimiento. | Disponibilidad inmediata vía API REST de indicadores de demanda y morosidad/inasistencia. |
| **N6** | Continuidad del Servicio | Permitir asignar un instructor suplente cuando el titular no asiste o cancelar con `>= 2h` de aviso reagendando a los socios. | 100% de eventos de contingencia notificados a los socios inscritos. |

---

## 5. Catálogo de 20 Historias de Usuario (User Stories) con Criterios Gherkin

| ID | Rol / Historia de Usuario | Escenario Gherkin (`Given` / `When` / `Then`) | Necesidad / Regla |
|---|---|---|---|
| **US-001** | **Como** socio, **quiero** reservar un lugar en una clase, **para** asegurar mi participación. | **Given** un socio con membresía vigente, sin bloqueo disciplinario y una clase incluida en su plan con cupo disponible (`cupo > 0`)<br>**When** el socio solicita reservar un lugar en esa clase<br>**Then** el sistema confirma la reserva (`CONFIRMADA`), descuenta 1 del cupo disponible y emite el evento `ReservaConfirmada`. | N2 · CU-01 |
| **US-002** | **Como** socio, **quiero** consultar la disponibilidad de una clase antes de reservar, **para** decidir si me anoto o busco otro horario. | **Given** una clase programada con horario, instructor y capacidad máxima definidos<br>**When** el socio consulta el detalle de la clase<br>**Then** el sistema muestra el cupo disponible actual, el total en lista de espera y si está incluida en su plan. | N2 · CQRS Query |
| **US-003** | **Como** socio, **quiero** anotarme en la lista de espera cuando una clase está llena, **para** tener oportunidad de asistir si se libera un lugar. | **Given** una clase sin cupo disponible (`cupo == 0`) y un socio elegible<br>**When** el socio solicita reservar en esa clase<br>**Then** el sistema lo registra en la `ListaDeEspera` en orden FIFO indicando su posición exacta. | N3 · CU-02 |
| **US-004** | **Como** socio, **quiero** cancelar mi reserva con al menos 3 horas de anticipación, **para** liberar mi lugar a otro socio sin penalización. | **Given** una reserva confirmada con `>= 3 horas` de anticipación al inicio de la clase<br>**When** el socio solicita cancelar su reserva<br>**Then** el sistema cambia la reserva a `CANCELADA` sin aplicar sanción, libera el cupo y emite `LugarLiberadoEnClase`. | N2, N3 · CU-03 |
| **US-005** | **Como** socio en espera, **quiero** ser promovido cuando se libere un lugar, **para** confirmar mi asistencia dentro del tiempo límite de 30 minutos. | **Given** un socio en la primera posición de la lista de espera (FIFO) y un cupo recién liberado<br>**When** el sistema procesa la liberación del lugar<br>**Then** promueve automáticamente al primer socio en espera, le notifica y le otorga 30 minutos para confirmar antes de pasar al siguiente. | N3 · CU-02, CU-03 |
| **US-006** | **Como** recepción, **quiero** verificar la vigencia de la membresía de un socio al ingresar, **para** autorizar o negar el acceso físico correctamente. | **Given** un socio que se identifica en el torniquete de recepción<br>**When** el sistema consulta el estado de su membresía<br>**Then** autoriza el acceso si está `ACTIVA` y vigente, incluso si el socio tiene bloqueo temporal de reservas por *no-shows*. | N1 · CU-04 |
| **US-007** | **Como** recepción, **quiero** ver el motivo explícito cuando el acceso de un socio es rechazado, **para** explicarle su situación con claridad. | **Given** un socio con membresía `VENCIDA`, `SUSPENDIDA` o inexistente<br>**When** intenta ingresar por recepción<br>**Then** el sistema deniega el paso, emite `AccesoFisicoDenegado` y devuelve el motivo específico (`"Membresía Vencida"` o `"Membresía Suspendida"`). | N1 · CU-04 |
| **US-008** | **Como** recepción, **quiero** registrar manualmente una reserva o solicitud de membresía para un socio, **para** atender solicitudes presenciales. | **Given** un socio activo y planes deportivos habilitados en catálogo<br>**When** recepción registra la operación a nombre del socio<br>**Then** el sistema valida las mismas reglas de dominio (`Specification`) y crea la operación en estado `SOLICITADA`. | N2 · CU-01 |
| **US-009** | **Como** instructor, **quiero** ver la lista de socios inscritos en mi clase, **para** prepararla y pasar asistencia. | **Given** una clase programada próxima a impartirse<br>**When** el instructor consulta el padrón de la sesión<br>**Then** el sistema devuelve la lista de socios con reserva confirmada y los socios en espera. | N4 |
| **US-010** | **Como** instructor, **quiero** cancelar una clase con al menos 2 horas de anticipación, **para** notificar a los socios y evitar asistencias en vano. | **Given** una clase programada con socios inscritos y `>= 2 horas` antes de su inicio<br>**When** el instructor cancela la sesión<br>**Then** el sistema marca la clase como cancelada, emite `ClaseCanceladaPorInstructor` y notifica a los inscritos para reagendar sin costo. | N6 |
| **US-011** | **Como** instructor, **quiero** registrar la asistencia o inasistencia (*no-show*) de cada socio, **para** mantener un historial confiable. | **Given** una clase en curso con socios confirmados<br>**When** el instructor marca asistencia o *no-show* para cada socio<br>**Then** el sistema actualiza el estado de la reserva y el contador mensual de inasistencias del socio. | N4 · CU-05 |
| **US-012** | **Como** administrador, **quiero** definir la capacidad máxima y stock de cada clase o plan, **para** evitar sobrecupo. | **Given** un plan o clase en el catálogo de FitZone<br>**When** el administrador establece su `capacidad_o_stock` y estado `habilitado`<br>**Then** el dominio impide cualquier operación que supere la capacidad o utilice un recurso deshabilitado. | N2 |
| **US-013** | **Como** administrador, **quiero** aplicar límites de reservas simultáneas según el plan del socio y beneficios VIP en contrataciones, **para** reflejar las políticas comerciales. | **Given** un socio con Plan Básico (máx. 2 reservas) o un Socio Preferente (VIP) con operación `>= $1,500 MXN` sin promoción activa<br>**When** se evalúa la regla comercial mediante `Specification`<br>**Then** el sistema restringe la 3ra reserva en Plan Básico y otorga 10% de beneficio en contrataciones elegibles. | N2 · Spec Pattern |
| **US-014** | **Como** administrador, **quiero** consultar reportes de ocupación por clase y estado de operaciones, **para** identificar demanda real. | **Given** clases programadas y operaciones de membresía registradas<br>**When** el administrador solicita el reporte de ocupación<br>**Then** el sistema calcula y devuelve el porcentaje de ocupación (`reservas / capacidad_maxima * 100`) por clase. | N5 |
| **US-015** | **Como** administrador, **quiero** consultar la tasa de *no-shows* por socio, **para** auditar las penalizaciones aplicadas. | **Given** el historial de reservas asistidas y no asistidas de los socios<br>**When** el administrador consulta las métricas de inasistencia<br>**Then** el sistema muestra el total de *no-shows*, la tasa porcentual y si el socio se encuentra sancionado. | N4, N5 |
| **US-016** | **Como** administrador, **quiero** recibir alertas de membresías próximas a vencer, **para** gestionar renovaciones oportunamente. | **Given** membresías activas cuya fecha de fin está dentro de los próximos `N` días<br>**When** se ejecuta la consulta de alertas de vencimiento<br>**Then** el sistema lista los socios cuyas membresías vencerán en dicho umbral. | N5 |
| **US-017** | **Como** sistema, **quiero** bloquear automáticamente las reservas de un socio que acumula 3 *no-shows* en el mes, **para** aplicar la política disciplinaria sin sesgos. | **Given** un socio con 2 *no-shows* en el mes en curso que incurre en su tercer *no-show*<br>**When** el dominio procesa la tercera inasistencia<br>**Then** bloquea al socio para nuevas reservas durante **7 días**, emite `SocioBloqueadoPorInasistencia` y conserva intacto su acceso físico al gimnasio. | N4 · CU-05 |
| **US-018** | **Como** sistema, **quiero** cancelar automáticamente las reservas activas de un socio cuando su membresía vence, **para** evitar que ocupe lugares sin contrato vigente. | **Given** un socio con membresía que transita al estado `VENCIDA` y que posee reservas futuras activas<br>**When** se procesa el vencimiento de la membresía<br>**Then** el sistema cancela sus reservas activas, libera los cupos, promueve de la lista de espera y emite `MembresiaVencida`. | N1, N2 |
| **US-019** | **Como** socio, **quiero** pagar un acceso extraordinario *"drop-in"* a una clase fuera de mi plan, **para** asistir ocasionalmente sin cambiar de contrato. | **Given** una clase con cupo disponible no incluida en el plan base del socio<br>**When** el socio solicita inscripción *drop-in* cubriendo la tarifa unitaria<br>**Then** el `ServicioDeInscripcionExtraordinaria` confirma la reserva con marca `es_drop_in=True` sin alterar su membresía base. | N2 |
| **US-020** | **Como** recepción, **quiero** asignar un instructor de respaldo cuando el titular no se presenta, **para** garantizar la continuidad de la sesión. | **Given** una clase próxima a iniciar cuyo instructor titular reporta ausencia imprevista<br>**When** recepción asigna un instructor suplente disponible en ese horario<br>**Then** la clase actualiza su instructor titular sin cancelar las reservas de los socios; si no hay suplente, se cancela la clase notificando a todos. | N6 |

---

## 6. Glosario Oficial de Dominio (Lenguaje Ubicuo)

| Término (Lenguaje Ubicuo) | Definición en el Dominio de FitZone | Representación en Código (`src/domain`) |
|---|---|---|
| **Socio (`Actor`)** | Cliente registrado en FitZone que adquiere membresías, ingresa a instalaciones y reserva clases. Puede ser Preferente (VIP) y estar activo o inactivo. | Aggregate Root `Socio` |
| **Plan Deportivo (`Recurso`)** | Producto o servicio del catálogo (Mensual, Trimestral, Semestral, Anual) con precio en MXN (`Decimal`), capacidad/stock y bandera `habilitado`. | Value Object / Entity `PlanDeportivo` |
| **Operación de Membresía** | Transacción mediante la cual un socio contrata uno o más planes deportivos. Inicia en `SOLICITADA` y transita por una máquina de estados estricta. | Aggregate Root `OperacionMembresia` |
| **Vigencia** | Periodo contractual inmutable (`fecha_inicio`, `fecha_fin`) que determina si una membresía está en curso o vencida. | Value Object `Vigencia` (`frozen=True`) |
| **Dinero (`Money`)** | Representación monetaria exacta en `Decimal` (MXN) que impide errores de coma flotante binaria y rechaza montos negativos. | Value Object `Money` (`frozen=True`) |
| **Clase Programada** | Sesión deportiva grupal con disciplina, horario, instructor asignado, capacidad máxima fija y lista de espera propia. | Aggregate Root `ClaseProgramada` |
| **Reserva** | Compromiso de lugar de un socio dentro de una `ClaseProgramada`. Estados: `CONFIRMADA`, `CANCELADA`, `ASISTIDA`, `NO_SHOW`. | Entity interna `Reserva` |
| **Lista de Espera** | Cola ordenada estrictamente bajo principio FIFO (`First-In, First-Out`) asociada a una clase sin cupo disponible. | Colección controlada en `ClaseProgramada` |
| **Cut-off Time** | Ventana mínima de anticipación (**3 horas** para socios al cancelar reserva; **2 horas** para instructores al cancelar clase). | Constante / Regla en `ClaseProgramada` |
| **No-Show** | Inasistencia de un socio que tenía reserva confirmada y no se presentó ni canceló antes del *cut-off time*. La tasa histórica se calcula como no-shows / (no-shows + asistencias) × 100. | Método `registrar_no_show()` |
| **Bloqueo Disciplinario** | Sanción temporal de **7 días** sin derecho a reservar nuevas clases tras acumular **3 *no-shows* mensuales** (no bloquea el torniquete físico). | Estado en `Socio` + `SocioBloqueadoPorInasistencia` |
| **Drop-in** | Inscripción extraordinaria de pago único que permite a un socio entrar a una clase no cubierta por su plan sin modificar su contrato. | `ServicioDeInscripcionExtraordinaria` |

---

## 7. Proceso de Negocio BPMN
El modelo BPMN oficial elaborado por el Equipo 11 contempla cuatro carriles (*Swimlanes*): **Socio**, **Recepción / Sistema de Control de Acceso**, **Motor de Dominio FitZone** e **Instructor / Administración**, cubriendo de extremo a extremo la contratación y validación de membresías, el ingreso por torniquete, la reservación de clase con derivación a lista de espera FIFO, la cancelación anticipada con promoción automática y el control de asistencia con sanción por 3 *no-shows*.

*(El diagrama de proceso principal se incluye en `docs/architecture/diagrams/diagrama_bpmn.png`; los subprocesos ampliados de membresía/acceso, reservas/FIFO y asistencia/continuidad se incluyen en `docs/phase2/diagrams/`. Los diagramas son modelos visuales de carriles y decisiones; deben revisarse con el stakeholder antes de afirmar que cada detalle operativo fue validado).*

---

## 8. Matriz de Trazabilidad Completa (BRD → US/Gherkin → Arquitectura DDD → Código → Pruebas)

| Necesidad BRD | Historias de Usuario (Gherkin) | Caso de Uso / Proceso BPMN | Componentes de Dominio, Specifications y Eventos (`src/domain`) | Servicios de Aplicación y Endpoints (`src/application` & `src/api`) | Decisiones (ADR) | Pruebas Automatizadas (`tests/`) |
|---|---|---|---|---|---|---|
| **N1:** Validación automática de acceso físico | US-006, US-007, US-018 | CU-04: Validar acceso en torniquete y vencimiento | `Socio.verificar_acceso_fisico()`, `Vigencia`, `OperacionMembresia.vencer()`, Eventos: `AccesoFisicoDenegado`, `MembresiaVencida` | `ControlAccesoService`, `POST /api/v1/socios/{id}/acceso`, `POST /api/v1/operaciones/{id}/vencer` | ADR-01, ADR-03 | `test_domain.py`, `test_api.py` (`test_acceso_fisico_*`, `test_vencimiento_*`) |
| **N2:** Contratación de membresías, beneficios VIP y reservas de clases | US-001, US-002, US-004, US-008, US-012, US-013, US-019 | CU-01: Reservar clase / Contratar plan / Drop-in | `OperacionMembresia`, `ClaseProgramada.reservar()`, `SocioActivoSpec`, `DetalleNoVacioSpec`, `RecursosHabilitadosYConStockSpec`, `OperacionAutorizadaSpec`, `SocioPreferenteSpec`, `MontoMinimoSpec`, `SinPromocionActivaSpec`, `ServicioDeInscripcionExtraordinaria` | `MembresiaAppService`, `ReservaAppService`, `POST /api/v1/operaciones/{id}/aprobar`, `POST /api/v1/clases/{id}/reservas` | ADR-01, ADR-04 | `test_csv_scenarios.py` (120 casos `FIT-T001..060`, `FIT-B001..060` + 20 transiciones `FIT-S001..020`) |
| **N3:** Gestión automática de lista de espera FIFO | US-003, US-004, US-005 | CU-02, CU-03: Lista de espera y cancelación con promoción FIFO | `ClaseProgramada.lista_espera`, `ClaseProgramada.cancelar_reserva()`, `ClaseProgramada.confirmar_promocion_espera()`, Evento: `LugarLiberadoEnClase` | `ReservaAppService.cancelar_reserva()`, `DELETE /api/v1/clases/{id}/reservas/{socio_id}` | ADR-01, ADR-02 (UoW) | `test_domain.py` (`test_lista_espera_fifo_y_promocion`) |
| **N4:** Registro de asistencia y bloqueo por 3 *no-shows* | US-009, US-011, US-017 | CU-05: Sanción automática por acumulación de *no-shows* | `Socio.registrar_no_show()`, `Socio.registrar_asistencia()`, `ClaseProgramada.registrar_inasistencia()`, `SocioSinBloqueoSpec`, Evento: `SocioBloqueadoPorInasistencia` | `AsistenciaAppService`, `POST /api/v1/clases/{id}/no-show/{socio_id}` | ADR-01 | `test_domain.py`, `test_api.py` (`test_tercer_no_show_bloquea_7_dias`) |
| **N5:** Reportes de ocupación, demanda y alertas | US-014, US-015, US-016 | Proceso transversal de analítica administrativa | Propiedades calculadas de `ClaseProgramada.porcentaje_ocupacion` y métricas de `Socio` | `ReportesQueryService` (CQRS), `GET /api/v1/reportes/ocupacion`, `GET /api/v1/reportes/no-shows` | ADR-03 (CQRS) | `test_api.py` (`test_reportes_ocupacion_y_noshows`) |
| **N6:** Continuidad del servicio ante ausencia de instructor | US-010, US-020 | Reasignación de suplente o cancelación por instructor (`>= 2h`) | `ClaseProgramada.reasignar_instructor()`, `ClaseProgramada.cancelar_por_instructor()`, Evento: `ClaseCanceladaPorInstructor` | `ReservaAppService`, `POST /api/v1/clases/{id}/cancelar-instructor`, `POST /api/v1/clases/{id}/reasignar-instructor` | ADR-01 | `test_domain.py` (`test_instructor_cancela_y_reasigna`) |


## Glosario de Dominio (20 términos)

| Término | Definición |
|---|---|
| Socio | Cliente registrado que adquiere membresías y reserva clases. |
| Membresía | Contrato que otorga acceso a servicios durante una vigencia definida. |
| Plan deportivo | Oferta comercial con servicios, precio y condiciones de acceso. |
| Operación de membresía | Solicitud de contratación que sigue una máquina de estados. |
| Instructor | Persona asignada para impartir una clase y registrar asistencia. |
| Clase programada | Sesión con disciplina, horario, instructor y capacidad. |
| Reserva | Compromiso de un socio para ocupar un lugar en una clase. |
| Lista de espera FIFO | Cola que atiende a los socios por orden de llegada. |
| Capacidad máxima | Límite de reservas confirmadas permitido en una clase. |
| Cupo disponible | Lugares libres calculados a partir de capacidad y reservas activas. |
| Vigencia | Intervalo de fechas en el que una membresía es válida. |
| Acceso físico | Decisión de permitir o denegar el ingreso al gimnasio. |
| Check-in | Registro de presentación del socio a una sesión o instalación. |
| No-show | Inasistencia de un socio que tenía una reserva confirmada. |
| Bloqueo de reservas | Restricción temporal para reservar clases por acumulación de no-shows. |
| Cut-off time | Anticipación mínima para cancelar sin penalización. |
| Drop-in | Acceso extraordinario de pago único a una clase fuera del plan. |
| Specification | Objeto que encapsula una regla de negocio verificable y componible. |
| Máquina de estados | Modelo de estados y transiciones válidas de una entidad. |
| Evento de dominio | Hecho relevante ocurrido dentro del dominio del negocio. |


### Reglas de implementación verificadas en la Fase 2
- **Vigencia no registrada:** el endpoint de acceso devuelve `permitido=false` con el motivo `Vigencia de membresía no registrada`. La fecha se captura mediante `PUT /api/v1/socios/{actor_id}/vigencia` con rol ADMIN.
- **Tasa histórica de no-show:** `GET /api/v1/reportes/no-shows` devuelve `no_shows_historicos`, `asistencias_historicas`, `reservas_con_resultado` y `tasa_no_show_porcentaje`. El porcentaje usa únicamente reservas en estado `NO_SHOW` o `ASISTIDA`; las reservas pendientes/canceladas no entran al denominador.
- **Límite de la analítica:** el porcentaje es sobre los registros que permanecen en las clases almacenadas; aún no existe filtro temporal configurable ni histórico independiente de reservas.
