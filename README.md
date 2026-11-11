# Fluport
**Menos fila, más puerto.**

Fluport predice la congestión en los accesos al puerto de Veracruz y redistribuye la llegada de camiones mediante citas en el horario de menor espera, avisando a cada actor por el canal que ya usa.

> ⚠️ **SIMULACIÓN.** Todos los datos de Fluport son sintéticos, generados por un simulador. No se usan datos reales de la terminal, la aduana ni de personas. Los teléfonos usados en la demo son números de prueba con consentimiento de sus titulares.

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

**Pruebas:**
```bash
cd backend
pip install -r requirements-dev.txt
pytest                 # todas (≈15 s)
pytest -m "not lento"  # sin la prueba de entrenamiento
```

---

## Bitácora de IA


### 2026-11-11 15:45 · `aae10d9` · Contratos M0 y esqueleto del proyecto

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
  | `docs/contracts.md` | Resumen legible de todos los contratos para el desarrollo de cada módulo. | Convenciones, tablas, endpoints, formato del WebSocket, herramientas del asistente. |
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


### 2026-11-11 16:05 · `d1a97ad` · M1 Simulador en tiempo real (mundos A/B, eventos, WebSocket, histórico)

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/data/escenario.json` | Parámetros de la simulación en un archivo editable sin tocar código. **Valores provisionales** hasta contar con datos públicos del puerto. | 3 accesos (carriles, tiempo de servicio, participación, coordenadas y rutas); 1 300 camiones/día; perfil de llegadas por hora; mezcla de tipos de carga; % de no-show (8 %) y de cumplimiento de la sugerencia (70 %); buques (0–1 por día) y probabilidad de norte (10 %). |
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

### 2026-11-11 17:20 · `#003` · Datos del puerto integrados al simulador

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/data/escenario.json` (reemplazado) | Parámetros de la simulación tomados de la hoja de datos `Fluport_Rol_Datos.xlsx`. | 3 accesos reales: casetas La Antigua (4 carriles, 3.9 min), Paso del Toro (4 carriles, 4.1 min) y San Julián (3 carriles, 4.5 min) con coordenadas aproximadas; 2 000 camiones/día; llegadas por franja (5 % de 00–06 h, 24 % de 06–10 h, 28 % de 10–14 h, 26 % de 14–18 h, 17 % de 18–24 h); 65 % con cita, 15 % de no-show y 50 % que acepta la hora sugerida; retraso medio de 20 min; carga refrigerada 6 % y peligrosa 17.5 %; 1.1 buques/día de ~2 050 contenedores; norte de 24 h (12–48 h) que reduce 30 % la atención; 10 % de revisión aduanal con 45 min extra; factores de impacto (3 L/h de diésel en ralentí, 26 MXN/L, 385 MXN por hora de camión parado, 2.68 kg CO₂/L). Participación por acceso (40/38/22 %) tomada de la hoja «Validación». |
  | `backend/app/sim/escenario.py` (modificado) | Valida el nuevo formato del escenario. | `FranjaLlegadas` y validador que exige que las franjas sumen 100 %; `perfil_horario` reparte cada franja en sus horas; `camiones_base_dia` y `camiones_buque_dia` (separa la demanda base de las olas por buque); `retraso_sigma_min` convierte el retraso promedio en la σ de una distribución normal (σ = promedio × √(π/2)); `NorteParam.factor_servicio` = 1 / (1 − reducción de atención); nuevos modelos `RevisionAduanal` e `Impacto`. |
  | `backend/app/sim/demanda.py` (modificado) | Sorteo de cada camión. | Nuevos atributos `con_cita` y `revision_aduanal`; el no-show y el seguimiento de la sugerencia solo aplican a camiones con cita; la revisión aduanal suma su tiempo a la estancia dentro del puerto (no ocupa carril en la caseta); `poisson()` ahora es pública para sortear el número de buques por día. |
  | `backend/app/sim/mundo.py` (modificado) | Mundo B. | Solo los camiones con cita que aceptan la sugerencia se reubican en otra franja; los demás llegan a su hora. |
  | `backend/app/sim/motor.py` (modificado) | Eventos automáticos y KPIs. | Buques por día con distribución de Poisson (media 1.1); duración de cada norte sorteada entre 12 y 48 h; el costo evitado usa el costo integral de la hora de camión parado (385 MXN/h) y el diésel/CO₂ los factores del escenario. |
  | `backend/app/config.py` (modificado) | Configuración. | Se retiran los factores de diésel y CO₂: ahora viven en `escenario.json` junto con su fuente. |

- **Funcionalidad:** la simulación ya corre con los parámetros del puerto entregados por Datos: tres casetas reales en el mapa, la demanda y su distribución por hora, el comportamiento de los transportistas y los factores de costo y emisiones. Si la hoja de datos cambia, basta con editar `escenario.json`; un validador avisa si los porcentajes por franja no suman 100 %. Con estos valores (en 8 semillas de 7 días) el Mundo A tiene una espera promedio mediana de 25 min y el Mundo B la reduce entre 4 % y 20 %; la mejora es moderada porque solo el 65 % tiene cita y de ellos la mitad acepta moverse. Los días con norte de 24 h la capacidad baja a ~110 camiones/h y las filas se disparan en ambos mundos.

- **Tecnologías usadas:**
  - `Pydantic` (`field_validator`, propiedades calculadas): ver `aae10d9`. Aquí valida que las franjas sumen 100 % y deriva valores (perfil por hora, σ del retraso, factor de norte) para que la hoja de datos se capture en las mismas unidades que entregó Datos.
  - Distribución **normal** con desvío absoluto medio: el dato entregado es "retraso promedio"; para una Normal(0, σ), E|X| = σ·√(2/π), de donde se obtiene σ. Permite que haya camiones adelantados y retrasados con el promedio solicitado.
  - Distribución de **Poisson** para el número de buques por día: modelo estándar para eventos independientes con una media conocida (1.1/día); hay días sin buques y días con dos o más.
  - `openpyxl`: lectura de la hoja de Excel de Datos para extraer los valores y calcular la calibración (esperas promedio por acceso y hora de la hoja «Validación»). Se usó solo como herramienta de análisis; no forma parte de la aplicación.

- **Herramientas de IA:** Claude (Opus 5.5) leyó la hoja de datos, convirtió cada valor al formato del escenario, adaptó el modelo a los datos nuevos (cita, revisión aduanal, buques Poisson, costo por hora) y calibró con 8 semillas de 7 días contra la hoja «Validación»; verificó la API en vivo (casetas, evento norte con factor 1.43 y KPIs).

### 2026-11-11 17:30 · `#004` · M2 Pronóstico de congestión a 12 horas

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/prediction/features.py` | Define las variables con las que se predice, iguales en entrenamiento y en vivo. | `HORIZONTES` (30, 60, …, 720 min); `capacidad_franja()` (camiones atendibles en 30 min); `espera_de_fila()`; `proyeccion_fluida()`: **balance de flujo** franja por franja, fila = máx(0, fila anterior + llegadas conocidas − capacidad); `dataset_entrenamiento()` convierte la serie de lecturas en ejemplos "estado en t → espera en t + h" con 15 variables (acceso, mundo, horizonte, hora y día objetivo, fila y espera actuales, llegadas y atendidos de la última hora, norte, citas de la franja objetivo, buques, espera por balance de flujo, carriles y tiempo de servicio). |
  | `backend/app/prediction/entrenar.py` | Entrena y evalúa el modelo. | `entrenar()`: genera 17 días simulados, separa los últimos 3 para evaluar (separación temporal, sin mezclar con el entrenamiento), entrena un `HistGradientBoostingRegressor` que aprende la **corrección** sobre el balance de flujo, mide el error medio contra dos referencias (balance de flujo solo y "persistencia": suponer que la espera no cambia) y guarda modelo + métricas en `backend/modelos/pronostico.joblib`. Comando: `python -m app.prediction.entrenar --dias 14`. |
  | `backend/app/prediction/pronosticador.py` | Pronóstico en vivo. | `Pronosticador.calcular()` arma las variables desde el estado actual del simulador (en el Mundo B usa las llegadas agendadas por el planificador) y predice las 24 franjas de cada acceso; si un acceso está cerrado supone que sigue cerrado la próxima hora; `obtener()` guarda el resultado en caché y lo recalcula cada 15 min simulados; `espera_en()` da la espera prevista en un instante (la usará M3 para sugerir horarios); si no hay modelo, responde con el balance de flujo (`balance-flujo-v1`). |
  | `backend/app/api/pronostico.py` (implementado) | Rutas del pronóstico. | `GET /api/pronostico?acceso_id=&horas=&mundo=` (404 si el acceso no existe); nuevo `GET /api/pronostico/modelo` con versión y métricas. |
  | `backend/app/sim/historico.py` (modificado) | Histórico simulado. | `generar()` ahora devuelve también las lecturas y puede correr sin PostgreSQL (`persistir=False`), para entrenar en cualquier entorno. |
  | `backend/app/sim/servicio.py` (modificado) | Servicio en vivo. | `_autoentrenar()`: si al arrancar no existe el modelo, lo entrena en segundo plano y lo activa al terminar (mientras tanto responde el balance de flujo); `_guardar_pronostico()` escribe en la tabla `pronostico` cada 60 min simulados. |
  | `backend/app/sim/persistencia.py` (modificado) | BD. | `guardar_pronosticos()`. |
  | `backend/app/config.py` (modificado) | Configuración. | `pronostico_autoentrenar`, `pronostico_guardar_cada_min`. |
  | `.gitignore` (modificado) | — | Excluye `modelos/` (el modelo se regenera con un comando en ~10 s). |
  | `docs/contracts.md`, `docs/openapi.json` (actualizados) | Contratos. | Parámetro `mundo` del pronóstico y ruta `/api/pronostico/modelo`. |

- **Funcionalidad:** el sistema estima para cada caseta la espera de las próximas 12 horas en franjas de 30 minutos, con su semáforo, y la actualiza cada 15 minutos simulados según lo que está pasando (fila actual, citas agendadas, buques, norte, cierres). Evaluado sobre 3 días que el modelo no vio, el error medio es de **2.5 min** frente a 6.7 min del balance de flujo solo y 7.5 min de suponer que la espera no cambia; en momentos de congestión (espera ≥ 20 min) el error es de 9.7 min. En 4 corridas de prueba adicionales con otras semillas el modelo superó siempre al balance de flujo, incluida una con norte (26 vs 38 min de error). Si no hay modelo, la app lo entrena sola al arrancar.

- **Tecnologías usadas:**
  - `scikit-learn` · `HistGradientBoostingRegressor`: modelo de árboles de decisión potenciados por gradiente que agrupa los valores en histogramas. **Por qué:** entrena en segundos con cientos de miles de filas, captura relaciones no lineales (hora pico × fila × buques) sin escalar variables y maneja directamente variables categóricas (acceso, mundo).
  - **Aprendizaje del residuo** (técnica): el modelo predice cuánto corregir la proyección por balance de flujo en vez de la espera directa. **Por qué:** los árboles no extrapolan fuera de los valores vistos; partir de una proyección física permite responder razonablemente ante situaciones extremas (nortes largos) y en pruebas redujo el error en el caso con norte de 57 a 26 min.
  - **Balance de flujo** (modelo de colas determinista): fila futura = fila actual + llegadas − capacidad. **Por qué:** es explicable en una frase ante el jurado, sirve de respaldo sin entrenamiento y de variable principal del modelo.
  - **Validación temporal** (hold-out por fecha): se evalúa con días posteriores a los de entrenamiento. **Por qué:** imita el uso real (predecir el futuro con datos del pasado) y evita resultados inflados por mezclar momentos cercanos.
  - `pandas` / `numpy`: tablas y arreglos numéricos. **Por qué:** construcción eficiente del conjunto de entrenamiento (≈190 000 ejemplos) a partir de las lecturas.
  - `joblib`: serialización de objetos de Python. **Por qué:** formato recomendado por scikit-learn para guardar y cargar modelos entrenados de forma rápida.
  - `asyncio.create_task` + `asyncio.to_thread`: ver `d1a97ad`. Aquí el entrenamiento automático corre en un hilo para que el simulador y la API sigan respondiendo.

- **Herramientas de IA:** Claude (Opus 5.5) diseñó las variables y el esquema de entrenamiento, comparó variantes (predicción directa vs. residuo, 14 vs. 28 días) en 4 semillas de prueba, implementó el pronóstico en vivo y lo verificó con el servidor corriendo: arranque sin modelo, entrenamiento automático, cambio de versión, reacción al cierre de un acceso, error 404 y escritura de pronósticos en PostgreSQL.

### 2026-11-11 17:45 · `#005` · Suite de pruebas automáticas y corrección de dos errores

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/requirements-dev.txt` | Dependencias solo para desarrollo. | Incluye `requirements.txt` + `pytest`. |
  | `backend/pytest.ini` | Configuración de las pruebas. | Carpeta `tests/`, ruta de importación y marca `lento` para la prueba de entrenamiento. |
  | `backend/tests/conftest.py` | Preparación común. | Apunta a una base de datos inexistente y desactiva el entrenamiento automático, para que las pruebas **no toquen tu PostgreSQL ni tu modelo**; fixtures `esc` (escenario real) y `sim` (simulador sin eventos automáticos). |
  | `backend/tests/test_escenario.py` (9) | Datos del puerto. | Validez del archivo, capacidad por hora, perfil horario que suma 100 %, rechazo de franjas que no suman 100 %, de ids repetidos y de 0 carriles, factor de norte, σ del retraso, demanda base con y sin buques. |
  | `backend/tests/test_demanda.py` (10) | Generación de camiones. | Misma semilla = misma demanda, días distintos difieren, llegadas ordenadas y dentro del día, volumen diario ±5 %, proporciones de cita y carga peligrosa, reglas de no-show/cumplimiento, prioridad, revisión aduanal, ola de buque, media de Poisson. |
  | `backend/tests/test_planificador.py` (6) | Franjas del Mundo B. | Evita franjas saturadas, respeta la hora si no hay carga, carga prioritaria conserva su horario, evita accesos cerrados, reserva lugar, candidatos ordenados. |
  | `backend/tests/test_mundo.py` (7) | Colas en las casetas. | Ciclo de vida completo del camión, no-show, fila cuando llegan más camiones que carriles, prioridad en el Mundo B, cierre/reapertura, desvío en el Mundo B, efecto del norte. |
  | `backend/tests/test_motor.py` (14) | Orquestación A/B. | Misma demanda en ambos mundos, Fluport reduce la espera con cumplimiento total, reloj, cada tipo de evento, error con acceso inválido, inyección de cita, lecturas cada 5 min, KPIs con los factores del escenario, snapshot válido con tope de camiones, publicación al WebSocket. |
  | `backend/tests/test_prediccion.py` (7) | Pronóstico. | Balance de flujo, capacidad y espera, conjunto de entrenamiento con 24 horizontes, respaldo sin modelo, un cierre sube el pronóstico inmediato, caché de 15 min, entrenamiento corto en archivo temporal (marca `lento`). |
  | `backend/tests/test_contratos.py` (10) | Contratos. | Umbrales del semáforo (5 casos), validaciones de cita y de control, esquema compilable para PostgreSQL. |
  | `backend/tests/test_api.py` (12) | API completa con el simulador corriendo y sin BD. | Salud, redirección, accesos y GeoJSON, estado por mundo, pausa/velocidad/play, eventos y errores 422, KPIs, pronóstico y 404, WebSocket (snapshot inicial y eventos), reset, rutas pendientes (501), verificación del webhook. |
  | `backend/app/sim/motor.py` (corregido) | Lecturas. | `_mover()` ahora se detiene en cada lectura: antes, si el reloj avanzaba más de 5 min en un paso (velocidades altas), se guardaba solo una lectura. |
  | `backend/app/sim/planificador.py` (corregido) | Franjas. | La distancia se mide a la franja que contiene la hora deseada: antes, en un empate, elegía la franja anterior y adelantaba 30 min a camiones que no necesitaban moverse. |
  | `backend/app/prediction/entrenar.py` (modificado) | Entrenamiento. | Parámetro `ruta` para guardar el modelo en otro archivo (lo usan las pruebas). |
  | `backend/app/api/sim.py` (modificado) | — | Código 422 explícito (la constante de Starlette quedó obsoleta). |

- **Funcionalidad:** 75 pruebas automáticas verifican los datos, la simulación, el planificador, el pronóstico, los contratos y la API completa en ~12 s, sin necesitar PostgreSQL. Al escribirlas se encontraron y corrigieron dos errores: lecturas perdidas a velocidad alta (afectaba el histórico y el pronóstico) y reprogramaciones innecesarias de 30 min en el Mundo B.

- **Tecnologías usadas:**
  - `pytest`: framework de pruebas de Python. **Por qué:** pruebas como funciones simples con `assert`, *fixtures* reutilizables (escenario, simulador, cliente), `parametrize` para casos tabulares (semáforo) y marcas para separar pruebas lentas.
  - `fastapi.testclient.TestClient`: cliente HTTP y WebSocket en memoria sobre la app. **Por qué:** prueba la API real, incluido el `lifespan` (arranque del simulador) y el WebSocket, sin levantar un servidor.
  - `pytest` · `tmp_path`: carpeta temporal por prueba. **Por qué:** el entrenamiento de prueba escribe ahí y no reemplaza el modelo de `backend/modelos/`.
  - `sqlalchemy.schema.CreateTable` con el dialecto de PostgreSQL: genera el DDL sin conexión. **Por qué:** comprueba que el esquema es válido para PostgreSQL aun sin base de datos disponible.

- **Herramientas de IA:** Claude (Opus 5.5) diseñó y escribió las pruebas, detectó con ellas los dos errores, los corrigió y verificó que las 75 pasan y que la calibración del simulador no cambió.
