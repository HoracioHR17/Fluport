# Fluport
**Menos fila, más puerto.**

Fluport predice la congestión en los accesos al puerto de Veracruz y redistribuye la llegada de camiones mediante citas en el horario de menor espera, avisando a cada actor por el canal que ya usa.

> ⚠️ **SIMULACIÓN.** Todos los datos de Fluport son sintéticos, generados por un simulador. No se usan datos reales de la terminal, la aduana ni de personas. Los teléfonos usados en la demo pertenecen al equipo, con su consentimiento.

## El problema
Cientos de camiones llegan al puerto todos los días a las mismas horas. Se forman filas largas en los accesos, se pierden horas de trabajo, se quema diésel en ralentí y el tráfico se desborda a la ciudad.

**Para quién:** transportistas, agentes aduanales y terminales, y vecinos de las zonas cercanas al puerto.

## Cómo funciona
1. **Simulador en vivo:** recrea el flujo de camiones hacia los accesos. Corre dos mundos a la vez, uno *sin Fluport* y otro *con Fluport*, para medir la diferencia.
2. **Pronóstico:** estima la espera de cada acceso durante las próximas 12 horas.
3. **Citas:** sugiere los tres mejores horarios para llegar y permite agendar, cambiar o cancelar.
4. **Asistente por WhatsApp:** el transportista pregunta en lenguaje natural, agenda su cita y recibe avisos.
5. **Tablero del operador:** mapa en vivo, semáforo por acceso, pronóstico y ahorro en horas, diésel, costo y CO₂.
6. **Vista pública:** semáforo y horas pico por zona para los vecinos.

## Cómo usarlo
**Demo en línea:** _(enlace pendiente)_

**Correrlo localmente:**
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ajustar la conexión a PostgreSQL
alembic upgrade head
uvicorn app.main:app --reload
```
Abrir `http://localhost:8000` (tablero) · `http://localhost:8000/publico/` (vecinos) · `http://localhost:8000/docs` (API).

## Equipo
| Rol | Integrante |
|---|---|
| Desarrollo | Angel |
| Datos | _(pendiente)_ |
| Pruebas | _(pendiente)_ |
| Documentación | _(pendiente)_ |
| Presentación | _(pendiente)_ |

---

## Bitácora de IA


### 2026-11-11 15:45 · `#001` · Contratos M0 y esqueleto del proyecto

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/requirements.txt` | Lista y fija las versiones de las dependencias de Python. | 13 paquetes agrupados por uso: API, simulación, BD, configuración, predicción, IA. |
  | `backend/.env.example` | Plantilla de variables de entorno; se copia a `.env` (que no se sube al repo). | URL de PostgreSQL, semilla y velocidad de la simulación, llaves de LLM, WhatsApp y Telegram. |
  | `.gitignore` | Evita subir al repositorio el entorno virtual, cachés, secretos (`.env`) y modelos entrenados. | — |
  | `backend/app/config.py` | Configuración central: lee `.env` y expone valores tipados con valores por defecto. | `Settings` (semilla, velocidad del reloj, umbrales del semáforo 20/45 min, factores de diésel/costo/CO₂, horizonte de 12 h, credenciales); `get_settings()` la crea una sola vez y la reutiliza. |
  | `backend/app/contracts/enums.py` | Todos los valores válidos de estados y tipos, compartidos por BD, API y WebSocket. | 14 enumeraciones: `TipoCarga`, `EstadoCita`, `Mundo` (A = sin Fluport, B = con Fluport), `EstadoCamion`, `Semaforo`, `TipoEventoSim`, etc.; `semaforo_de(espera)` es la única regla para calcular verde/amarillo/rojo. |
  | `backend/app/contracts/schemas.py` | Formato exacto de cada dato que entra o sale de la API y del WebSocket. | Accesos (`AccesoOut`, `AccesoEstado`); pronóstico (`PronosticoOut`, `FranjaPronostico`); citas (`CitaCreate` con validación de ventana y transportista, `CitaReprogramar`, `CitaOut`, `SugerenciaRequest`, `Sugerencia`); simulación (`CamionEstado` con progreso 0–1, `Kpis`, `KpisComparacion`, `MundoEstado`, `SimSnapshot`, `SimControl`, `EventoCreate`); mensajes WS (`WsSnapshot`, `WsEvento`, `WsAviso` unidos por el campo `tipo`); asistente (`AsistenteRequest/Response`); vista pública (`ZonaPublica`); `Salud`. |
  | `backend/app/db/base.py` | Conexión a PostgreSQL. | `Base` (clase madre de las tablas, con convención de nombres para índices y llaves); `engine` (conexión con verificación previa `pool_pre_ping`); `SessionLocal`; `get_db()` entrega una sesión por petición y la cierra al terminar. |
  | `backend/app/db/models.py` | Esquema de la base de datos: 10 tablas. | `Acceso`, `Transportista`, `Cita` (con `cita_anterior_id` para reprogramaciones y validación `ventana_fin > ventana_inicio`), `Buque`, `SimCorrida`, `LecturaCongestion` (serie temporal por corrida·mundo·acceso, alimenta el modelo), `EventoSim`, `Pronostico`, `Aviso`, `MensajeAsistente` (historial del asistente); `pg_enum()` guarda los enums con sus valores en texto. |
  | `backend/alembic.ini`, `backend/alembic/env.py`, `script.py.mako` | Configuración de migraciones. | `env.py` toma la URL de `config.py` y las tablas de `models.py`, en modo en línea y fuera de línea, comparando también tipos de columna. |
  | `backend/alembic/versions/0001_esquema_inicial.py` | Migración que crea todo el esquema. | `upgrade()` crea 10 tablas, 13 tipos ENUM e índices; `downgrade()` las elimina e incluye el borrado de los ENUM (Alembic no lo genera solo). |
  | `backend/app/api/_stub.py` | Respuesta común para endpoints aún no construidos. | `pendiente(modulo)` devuelve HTTP 501 indicando el módulo responsable. |
  | `backend/app/api/accesos.py` | Rutas de accesos (M1). | `GET /api/accesos`, `GET /api/accesos/estado?mundo=`. |
  | `backend/app/api/pronostico.py` | Ruta del pronóstico (M2). | `GET /api/pronostico?acceso_id=&horas=`. |
  | `backend/app/api/citas.py` | Rutas de citas (M3). | Crear, listar con filtros, sugerir 3 horarios, consultar, reprogramar (`PATCH`) y cancelar (`DELETE`). |
  | `backend/app/api/sim.py` | Control y stream de la simulación (M1). | `POST /api/sim/control`, `POST /api/sim/eventos`, `GET /api/sim/kpis`, `GET /api/sim/snapshot` (respaldo por polling), `WS /ws/sim`. |
  | `backend/app/api/asistente.py` | Asistente IA (M4) y webhooks (M5). | `POST /api/asistente/mensaje`; `GET /webhook/whatsapp` ya verifica el token de Meta (responde el `challenge` o 403); `POST /webhook/whatsapp` y `/webhook/telegram`. |
  | `backend/app/api/publico.py` | Vista para vecinos (M7). | `GET /api/publico/zonas`. |
  | `backend/app/main.py` | Punto de entrada: arma la aplicación. | Registra los 6 routers; `GET /api/salud` revisa la conexión a la BD con `SELECT 1`; `/` redirige al tablero; sirve `frontend/operador`, `frontend/publico` y `frontend/static`. |
  | `frontend/operador/index.html`, `frontend/publico/index.html` | Páginas provisionales mientras se define el diseño. | Muestran la etiqueta "SIMULACIÓN" y el enlace a la documentación de la API. |
  | `docs/contracts.md` | Resumen legible de todos los contratos para el equipo y los agentes. | Convenciones, tablas, endpoints, formato del WebSocket, herramientas del asistente. |
  | `docs/openapi.json` | Especificación completa de la API generada por FastAPI. | 15 rutas con sus esquemas de entrada y salida. |
  | `docs/ejemplo-snapshot.json` | Mensaje de ejemplo del WebSocket. | Permite construir el tablero con datos simulados antes de que exista el simulador. |

- **Funcionalidad:** define los contratos que comparten todos los módulos para construirlos en paralelo sin choques. La app ya arranca: `/api/salud` informa si hay conexión con PostgreSQL, `/docs` muestra la API interactiva, y las entradas inválidas se rechazan con 422 (p. ej. una cita cuya ventana termina antes de empezar o sin transportista). Los endpoints no construidos responden 501 indicando qué módulo los implementará.

- **Tecnologías usadas:**
  - `FastAPI`: framework web de Python para APIs REST y WebSocket. **Por qué:** genera la documentación OpenAPI a partir de los tipos (los contratos quedan documentados sin trabajo extra), valida automáticamente con Pydantic y soporta WebSocket nativo, necesario para el mapa en vivo. Permite que un solo proceso sirva API, WebSocket y páginas → un solo deploy y un solo dominio.
  - `Uvicorn` (`[standard]`: `uvloop`, `httptools`, `websockets`, `watchfiles`): servidor ASGI que ejecuta FastAPI. **Por qué:** es asíncrono (indispensable para enviar snapshots cada segundo sin bloquear la API), incluye soporte de WebSocket y recarga automática al editar código.
  - `Pydantic v2`: validación de datos con tipos de Python. **Por qué:** los schemas son un contrato ejecutable: la misma clase valida la petición, serializa la respuesta y genera la documentación; si un agente envía un campo mal, falla de inmediato.
  - `pydantic-settings` + `python-dotenv`: carga de configuración desde variables de entorno y `.env`. **Por qué:** separa secretos y parámetros del código; el mismo código corre en local y en el hosting cambiando solo variables.
  - `SQLAlchemy 2.1`: ORM de Python. **Por qué:** el esquema se define una vez en clases tipadas (`Mapped[...]`) que reutilizan la API, el simulador y la predicción; evita SQL escrito a mano repetido en cada módulo.
  - `Alembic`: migraciones de esquema para SQLAlchemy. **Por qué:** permite crear y modificar la BD de forma reproducible en la laptop y en el hosting con `alembic upgrade head`; la migración inicial se generó comparando los modelos contra una BD vacía y se probó de ida y vuelta.
  - `psycopg 3` (`[binary]`): driver oficial de PostgreSQL para Python. **Por qué:** es el driver moderno recomendado por SQLAlchemy 2 y la variante binaria trae todo precompilado (no requiere compilar librerías del sistema).
  - `PostgreSQL 16`: base de datos relacional. **Por qué:** requisito del proyecto; se usan tipos `ENUM` (la BD rechaza estados inválidos), `JSONB` (parámetros flexibles de eventos y corridas, útil para absorber el giro sin migrar) e índices compuestos para consultar series temporales rápido.
  - `StrEnum` (biblioteca estándar de Python 3.11+): enumeraciones cuyos valores son texto. **Por qué:** el mismo valor (`"contenedor_40"`) viaja idéntico en BD, JSON y código; un solo origen de verdad.
  - `StaticFiles` (FastAPI/Starlette): sirve archivos estáticos. **Por qué:** el frontend sin compilación se entrega desde el mismo servidor que la API.

- **Herramientas de IA:** Claude (Opus 5.5) diseñó el esquema, los schemas, los routers y la migración; los verificó en un PostgreSQL 16 de prueba (migración de ida y vuelta, `alembic check` sin diferencias, arranque de la app, validación de entradas y verificación del webhook).

- **Decisiones clave:**
  - Contratos en código (Pydantic + SQLAlchemy) y no solo en documento: los agentes no pueden desviarse sin que falle la validación.
  - Un solo proceso FastAPI (API + WebSocket + frontend): un único deploy y dominio, menos puntos de falla en la demo.
  - Frontend sin paso de compilación (Leaflet y Chart.js como archivos estáticos): no depende de npm.
  - El simulador envía el progreso 0–1 de cada camión sobre su ruta y el navegador calcula su posición: menos carga en el servidor y animación fluida.
  - `GET /api/sim/snapshot` como respaldo por polling si el WebSocket falla en el hosting.
  - Reprogramar crea una cita nueva ligada a la anterior (`cita_anterior_id`): conserva la traza y permite medir cumplimiento.
  - Tipo de evento `personalizado` con `payload` JSONB reservado para el giro del jueves.

### 2026-11-11 16:05 · `#002` · M1 Simulador en tiempo real (mundos A/B, eventos, WebSocket, histórico)

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/data/escenario.json` | Parámetros de la simulación en un archivo editable sin tocar código. **Valores provisionales** hasta que el equipo de Datos entregue los reales. | 3 accesos (carriles, tiempo de servicio, participación, coordenadas y rutas); 1 300 camiones/día; perfil de llegadas por hora; mezcla de tipos de carga; % de no-show (8 %) y de cumplimiento de la sugerencia (70 %); buques (0–1 por día) y probabilidad de norte (10 %). |
  | `backend/app/sim/escenario.py` | Lee y valida `escenario.json`. | `Escenario`, `AccesoParam`, `Ruta`, `BuquesParam`, `NorteParam` (modelos Pydantic que rechazan valores imposibles, p. ej. 0 carriles o ids repetidos); `capacidad_hora` = carriles × 60 / servicio; `cargar_escenario()` y `escenario_actual()`. |
  | `backend/app/sim/demanda.py` | Genera los camiones que llegarán. | `CamionPlan`: cada camión con **todos sus valores aleatorios ya sorteados** (tipo de carga, acceso, ruta, tiempo de trayecto, de revisión y de estancia, retraso, si falta a la cita, si sigue la sugerencia); `demanda_dia()` crea las llegadas de un día con un proceso de Poisson por hora (reproducible por semilla y día); `ola_buque()` agrega la ola de camiones que provoca un buque; `crear_camion()`. |
  | `backend/app/sim/planificador.py` | El "cerebro" de Fluport en el Mundo B: reparte las llegadas en franjas de 30 min. | `Planificador.asignar()` elige la franja con menor carga dentro de −60/+180 min de la hora deseada, penalizando moverse lejos o cambiar de acceso; la carga refrigerada y peligrosa conserva su horario; `candidatos()` devuelve las opciones ordenadas (lo reutilizará M3 para sugerir los 3 mejores horarios); `registrar()` cuenta a quienes no siguen la sugerencia. |
  | `backend/app/sim/mundo.py` | Un mundo de simulación con SimPy. | `MundoSim`: cada acceso es un recurso con `c` carriles; `_camion()` es el ciclo de vida `en_ruta → en_fila → en_revision → dentro → saliendo`; en el Mundo B la carga prioritaria pasa primero y, si su acceso está cerrado, el camión se desvía al acceso abierto con menor espera; `cerrar()`/`reabrir()` bloquean y liberan todos los carriles; `espera_estimada()` (fila ÷ capacidad efectiva); `progreso()` (0–1 sobre la ruta para animar el mapa); métricas acumuladas de espera, atendidos y pico de fila. |
  | `backend/app/sim/motor.py` | Orquesta los dos mundos con el mismo reloj y la misma demanda. | `Simulador.avanzar()` mueve el reloj y dispara eventos programados; `_asegurar_demanda()` mantiene generado el día actual y el siguiente; `aplicar_evento()` (cierre, reapertura, buque, norte, carga urgente, personalizado); `inyectar_cita()` para que M3 agregue camiones con cita; `kpis()` y `comparacion()` (horas ahorradas, diésel, costo, CO₂, % de reducción de espera y de pico); `snapshot()` arma el mensaje del WebSocket (camiones de demo primero, con tope de visibles); `_registrar_lecturas()` guarda cada 5 min simulados la fila y espera por acceso y mundo. |
  | `backend/app/sim/persistencia.py` | Escribe en PostgreSQL. Si la base no está disponible la simulación sigue sin guardar (la demo no se cae). | `sembrar_accesos()` (inserta o actualiza los accesos del escenario), `crear_corrida()`, `finalizar_corrida()`, `guardar_lecturas()`, `guardar_eventos()`, `guardar()` (con captura de errores). |
  | `backend/app/sim/servicio.py` | Ejecuta el simulador en vivo dentro del servidor. | `ServicioSim.iniciar()` crea la corrida y arranca el bucle; `_bucle()` avanza un tick por segundo real y publica el snapshot; cada 5 ticks escribe en la BD **en un hilo aparte** para no frenar el WebSocket; `suscribir()/publicar()` reparte mensajes a los navegadores conectados (sobreviven a un reset); `control()` play/pause/velocidad/reset; `SimNoIniciada` → respuesta 503. |
  | `backend/app/sim/historico.py` | Comando para generar días simulados en segundos (dataset de entrenamiento de M2). | `python -m app.sim.historico --dias 14 --semilla 100`; termina "ayer" para no traslaparse con la corrida en vivo; una lectura cada 15 min simulados. |
  | `backend/app/api/accesos.py` (implementado) | Rutas de accesos. | `GET /api/accesos`, `GET /api/accesos/estado?mundo=`, nuevo `GET /api/accesos/rutas` (GeoJSON de accesos y rutas para el mapa). |
  | `backend/app/api/sim.py` (implementado) | Control y stream. | `GET /api/sim/estado` (nuevo), `POST /api/sim/control`, `POST /api/sim/eventos` (422 si el acceso no existe), `GET /api/sim/kpis`, `GET /api/sim/snapshot`, `WS /ws/sim` (envía un snapshot al conectar y luego uno por tick más los eventos). |
  | `backend/app/main.py` (modificado) | Arranque y cierre ordenado. | `ciclo_vida()` inicia la simulación al levantar la app y la detiene guardando lo pendiente al apagarla; `/api/salud` reporta el estado real del simulador; manejador 503. |
  | `backend/app/config.py` (modificado) | Configuración. | `sim_autostart`; se aclara que `velocidad` = segundos simulados por segundo real. |
  | `docs/contracts.md`, `docs/openapi.json` (actualizados) | Contratos. | Nuevas rutas `/api/accesos/rutas` y `/api/sim/estado`, semántica de velocidad y del WebSocket. |

- **Funcionalidad:** al iniciar el servidor arranca una simulación en vivo de los camiones que llegan a 3 accesos del puerto, en dos mundos paralelos con exactamente los mismos camiones: **A, sin Fluport** (cada quien llega cuando quiere) y **B, con Fluport** (llegan en la franja sugerida si la siguen, la carga prioritaria pasa primero y se desvían si su acceso cierra). Cada segundo el tablero recibe por WebSocket la posición de cada camión, la fila y espera por acceso y los KPIs de ambos mundos. Desde la API se puede pausar, acelerar, reiniciar con otra semilla e inyectar eventos (cerrar/reabrir un acceso, atraque de buque, norte, carga urgente). Las lecturas se guardan en PostgreSQL y un comando genera días de historia para entrenar el pronóstico. En pruebas de 3 días con los valores provisionales, el Mundo B redujo la espera promedio entre 42 % y 45 % y el pico de fila entre 37 % y 45 %.

- **Tecnologías usadas:**
  - `SimPy`: biblioteca de simulación de eventos discretos. **Por qué:** modela de forma natural filas con varios carriles (`PriorityResource`), tiempos de servicio y eventos; el reloj simulado se adelanta tanto como se quiera, lo que permite correr en vivo (un tick por segundo) o generar 14 días en segundos con el mismo código.
  - `simpy.PriorityResource`: recurso con cola por prioridad. **Por qué:** con un solo mecanismo se implementan los carriles, la prioridad de carga refrigerada/peligrosa en el Mundo B y el cierre de un acceso (peticiones de máxima prioridad que ocupan todos los carriles hasta la reapertura).
  - **Números aleatorios comunes** (técnica de simulación): los dos mundos reciben los mismos camiones con los mismos valores sorteados. **Por qué:** la diferencia entre A y B se debe solo a Fluport y no al azar; el ahorro es medido, no supuesto.
  - `random.Random` (biblioteca estándar): generador pseudoaleatorio con semilla. **Por qué:** cada día usa su propia semilla derivada, así un día es idéntico aunque se inyecten eventos antes; permite repetir exactamente una demo.
  - Proceso de **Poisson no homogéneo** por hora y distribución **lognormal** para el servicio. **Por qué:** son los modelos estándar para llegadas aleatorias con picos y para tiempos de atención siempre positivos con cola larga.
  - `asyncio` (biblioteca estándar): tareas asíncronas. **Por qué:** el bucle del simulador corre en el mismo event loop que FastAPI; los endpoints de simulación son `async` para que nunca dos hilos modifiquen el estado a la vez; `asyncio.Queue` por cliente WebSocket descarta mensajes viejos si un navegador es lento.
  - `asyncio.to_thread`: ejecuta una función bloqueante en un hilo. **Por qué:** las escrituras a PostgreSQL no detienen el envío de snapshots.
  - `PostgreSQL INSERT ... ON CONFLICT DO UPDATE` (vía `sqlalchemy.dialects.postgresql.insert`): inserción o actualización en una sola sentencia. **Por qué:** sembrar los accesos del escenario es idempotente: se puede reiniciar la app o cambiar parámetros sin duplicados.
  - `contextlib.asynccontextmanager` + `lifespan` de FastAPI: código de arranque y apagado. **Por qué:** garantiza que la simulación inicie con la app y que al apagarse se escriba lo pendiente y la corrida quede como detenida.
  - `zoneinfo` (biblioteca estándar): zonas horarias. **Por qué:** el reloj simulado arranca en hora de Veracruz (`America/Mexico_City`).
  - GeoJSON: formato estándar de datos geográficos. **Por qué:** Leaflet lo dibuja directamente; el mapa no necesita conocer el formato interno del escenario.

- **Herramientas de IA:** Claude (Opus 5.5) diseñó e implementó el simulador y su API, y lo verificó: corridas de 3 días con dos semillas, cierre y reapertura de acceso (en A la fila crece en el acceso cerrado; en B los camiones se desvían), inyección de una cita de demo, servidor en vivo con cliente WebSocket (snapshots, eventos, pausa que congela el reloj, reset sin perder la conexión), errores 422 y escritura de lecturas y eventos en PostgreSQL 16.

- **Decisiones clave:**
  - Parámetros en JSON y no en código: el equipo de Datos los ajusta y el giro del jueves se puede absorber cambiando valores.
  - Primera calibración: con 1 500 camiones/día y buques grandes el sistema quedaba saturado todo el día (esperas de 10 h, irreal); se bajó a 1 300/día, buques más pequeños y la participación de cada acceso proporcional a su capacidad, para que haya picos que se disipan de noche.
  - La demanda se genera con un día de anticipación: así el Mundo B puede planificar, como ocurre con citas reales.
  - En el Mundo A los camiones no saben que un acceso cerró (esperan); en el B se desvían: es justamente el valor de informar a tiempo.
  - Un mismo archivo de código sirve para vivo e histórico: el modelo de M2 se entrena con datos coherentes con lo que se ve en el mapa.
  - Si PostgreSQL falla, la simulación continúa sin guardar: prioridad a que la demo no se caiga.
