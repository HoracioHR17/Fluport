# Fluport
**Menos fila, más puerto.**

Fluport predice la congestión en los accesos al puerto de Veracruz y redistribuye la llegada de camiones mediante citas en el horario de menor espera, avisando a cada actor por el canal que ya usa.

> ⚠️ **SIMULACIÓN.** Todos los datos de Fluport son sintéticos, generados por un simulador. No se usan datos reales de la terminal, la aduana ni de personas. Los teléfonos usados en la demo son números de prueba con consentimiento de sus titulares.

## El problema
Cientos de camiones llegan al puerto todos los días a las mismas horas. Se forman filas largas en los accesos, se pierden horas de trabajo, se quema diésel en ralentí y el tráfico se desborda a la ciudad.

**Para quién:** agencias transportistas y sus choferes, agentes aduanales y terminales, y vecinos de las zonas cercanas al puerto.

## Cómo funciona
1. **Simulador en vivo:** recrea el flujo de camiones hacia los accesos. Corre dos mundos a la vez, uno *sin Fluport* y otro *con Fluport*, para medir la diferencia.
2. **Pronóstico:** estima la espera de cada acceso durante las próximas 12 horas.
3. **Citas:** sugiere los tres mejores horarios para llegar y permite agendar, cambiar o cancelar.
4. **Vista pública:** estado de contingencia de cada entrada (normal, lenta, saturada o cerrada), espera estimada en tiempo real, horas pico y un acceso directo (botón y QR) al bot de Telegram.
5. **Bot de Telegram (WhatsApp listo para conectarse):** cada transportista se registra con su número, agenda, cambia o cancela sus citas en lenguaje natural y recibe avisos si su caseta se satura o se cierra.
6. **Vista de agencia:** cada agencia supervisa a sus transportistas: sus camiones en el mapa, su flota por estado, sus citas y los avisos que reciben, además del estado y el pronóstico de las casetas. Invita a sus choferes con un enlace del bot propio de la agencia.
7. **Panel de demostración:** controla la simulación (velocidad y eventos como cierres, buques o norte) y compara el mundo *sin Fluport* con el *con Fluport*: ahorro en horas, diésel, costo y CO₂.

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
Abrir `http://localhost:8000/publico/` (vista pública, también en `/`) · `/agencia/` (agencias) · `/demo/` (panel de demostración) · `/docs` (API).

**Pruebas:**
```bash
cd backend
pip install -r requirements-dev.txt
pytest                 # todas las que no necesitan PostgreSQL (≈15 s)
pytest -m "not lento"  # sin la prueba de entrenamiento

# con PostgreSQL (incluye citas), usando una base aparte que se borra y recrea:
sudo -u postgres createdb -O fluport fluport_test
FLUPORT_TEST_DATABASE_URL=postgresql+psycopg://fluport:fluport@localhost:5432/fluport_test pytest
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

### 2026-11-11 17:50 · `#006` · Plan de diseño y semáforo alineado a la identidad visual

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `docs/diseno.md` | Plan de diseño para el frontend, tomado del documento de identidad visual. | Paleta (Arena `#F4EFE6`, Bruma `#E3EEF6`, Abismo `#0A2238`, Fluye `#3FAE7A`, Lento `#E9B03B`, Saturado `#D9574B`) y su uso; reglas de accesibilidad (color siempre con texto y símbolo ●/▲); tabla de correspondencia entre el valor del semáforo en la API (`verde`/`amarillo`/`rojo`) y su etiqueta visible (Fluye/Lento/Saturado); tipografía Arial/Helvetica con jerarquía por tamaño y grosor; logotipo; elementos obligatorios en pantalla. |
  | `frontend/static/css/tokens.css` | Variables CSS listas para todas las pantallas. | `--arena`, `--bruma`, `--abismo`, `--fluye`, `--lento`, `--saturado`, `--fuente`; clases base `.panel`, `.boton`, `.cifra` (números tabulares), `.semaforo--verde/amarillo/rojo` (agregan ● o ▲ con su color), `.logo` y `.etiqueta-simulacion`. |
  | `backend/app/config.py`, `backend/app/contracts/enums.py` (modificados) | Umbrales del semáforo. | De 20/45 min a **30/90 min** (Fluye < 30 · Lento 30–90 · Saturado > 90), como define la identidad visual; afecta estado de accesos, pronóstico y vista pública. |
  | `backend/app/prediction/entrenar.py` (modificado) | Métrica de congestión. | El error "en congestión" ahora se mide con esperas ≥ 30 min, coherente con el nuevo umbral. |
  | `backend/tests/test_contratos.py`, `docs/contracts.md` (actualizados) | — | Casos de prueba y documentación con los nuevos umbrales. |

- **Funcionalidad:** el sistema ya clasifica los accesos con los mismos umbrales que verá el usuario (Fluye, Lento, Saturado) y el frontend cuenta con una hoja de estilos base con la paleta, la tipografía y el semáforo accesible. Las 75 pruebas siguen pasando.

- **Tecnologías usadas:**
  - **CSS Custom Properties** (variables `--nombre`): valores reutilizables en toda la hoja de estilos. **Por qué:** un solo lugar para la paleta y la tipografía; cambiar un color se refleja en todas las pantallas sin compilar nada.
  - **Pseudo-elementos `::before` / `::after`**: insertan contenido visual desde CSS. **Por qué:** añaden automáticamente el símbolo ● o ▲ junto al estado, así el semáforo nunca depende solo del color.
  - `font-variant-numeric: tabular-nums`: dígitos de ancho fijo. **Por qué:** las cifras y horarios no "bailan" al actualizarse cada segundo.
  - Fuente del sistema (Arial/Helvetica): **Por qué:** no requiere descargas ni CDN, carga al instante y se lee bien en pantallas pequeñas.

- **Herramientas de IA:** Claude (Opus 5.5) extrajo del documento de identidad solo lo relativo al diseño, lo tradujo a tokens CSS y a la correspondencia con la API, alineó los umbrales del backend y verificó las pruebas.

### 2026-11-11 18:15 · `#007` · M3 Citas: sugerir, agendar, reprogramar, cancelar y medir cumplimiento

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/citas/servicio.py` | Toda la lógica de citas. | `sugerir()`: recorre las franjas de 30 min de la ventana pedida en las casetas abiertas, estima la espera de cada una y devuelve las mejores (menor espera; en empate, la más cercana a lo pedido; ligera preferencia por la caseta pedida) con su semáforo y los minutos que ahorra frente a la peor franja; `espera_estimada()` usa el pronóstico de 12 h y, más allá, la carga agendada contra la capacidad; `crear()` valida caseta y horario, encuentra o crea al transportista por teléfono, asigna prioridad a carga refrigerada/peligrosa, guarda la cita y **la inyecta en el simulador**; `reprogramar()` crea una cita nueva ligada a la anterior y retira el camión original; `cancelar()`; `listar()` con filtros; `resumen()` (citas por estado, % de cumplimiento, citas por caseta); `aplicar_cambios()` pasa a la BD los estados que ocurrieron en la simulación (en_ruta, cumplida); `marcar_no_shows()`; `citas_por_reinyectar()` tras un reset; `normalizar_telefono()` (acepta el formato `whatsapp:+52…` de Twilio); `ErrorCita` con su código HTTP. |
  | `backend/app/api/citas.py` (implementado) | Rutas de citas. | `POST /api/citas`, `GET /api/citas` (filtros por teléfono, transportista, caseta, estado), `POST /api/citas/sugerencias`, nuevo `GET /api/citas/resumen`, `GET/PATCH/DELETE /api/citas/{id}`; traduce `ErrorCita` a 404/409/422. |
  | `backend/app/contracts/schemas.py` (modificado) | Contratos. | Nuevo `ResumenCitas`; `SugerenciaRequest` valida que `hasta` sea posterior a `desde`. |
  | `backend/app/sim/demanda.py`, `mundo.py`, `motor.py` (modificados) | Simulación con citas reales. | `CamionPlan.cancelado`: el camión de una cita cancelada no sale; `MundoSim.al_cambiar_cita` avisa cuando un camión con cita sale (en_ruta) y cuando empieza su revisión (cumplida); `Simulador.cancelar_cita()` lo retira y libera su lugar en la franja; `vaciar_cambios_cita()`. |
  | `backend/app/sim/servicio.py` (modificado) | Servicio en vivo. | Cada 5 ticks sincroniza en la BD los estados de las citas y marca no-shows; al iniciar o reiniciar la simulación vuelve a inyectar las citas activas. |
  | `backend/tests/conftest.py` (modificado) | Pruebas. | Con `FLUPORT_TEST_DATABASE_URL` las pruebas usan una base aparte que se borra y recrea; sin ella, las de citas con BD se omiten. |
  | `backend/tests/test_citas.py` (15) | Pruebas de citas. | Sin BD: teléfono, sugerencias ordenadas y dentro de la ventana, evita caseta cerrada, ventana pasada, cancelación en el simulador, aviso en_ruta→cumplida. Con BD: crear, prioridad, listar/obtener, errores (404, 422, 409), reprogramar, cancelar, sugerencias por API, cumplimiento y resumen, reinyección tras reset. |
  | `backend/tests/test_api.py` (modificado) | — | Ajustes por las rutas de citas ya implementadas. |
  | `docs/contracts.md`, `docs/openapi.json` (actualizados) | Contratos. | Ruta `/api/citas/resumen`, reglas de horario, errores y ciclo de estados. |

- **Funcionalidad:** un transportista (o el asistente, en M4) puede pedir los 3 mejores horarios para llegar en una ventana, agendar uno, cambiarlo o cancelarlo. Cada cita aparece como un camión en el Mundo B de la simulación y su estado se actualiza solo: pasa a "en ruta" cuando sale y a "cumplida" cuando llega a la caseta; si nunca sale, queda como no-show. El panel de cumplimiento muestra cuántas citas hay en cada estado, el % de cumplimiento y las citas por caseta. Probado con el servidor en vivo: sugerencia → cita → `cumplida` automática. Pruebas: 90 con PostgreSQL de prueba, 81 sin él.

- **Tecnologías usadas:**
  - `SQLAlchemy` ORM · `Session`, `select()`, `db.get()`: ver `aae10d9`. Aquí se usan consultas con filtros combinables y `flush()` para obtener el id de la cita antes de inyectarla en el simulador y confirmar (`commit`) solo si todo salió bien.
  - `FastAPI` · `Depends(get_db)`: inyección de dependencias. **Por qué:** cada petición recibe su propia sesión de BD y se cierra al terminar, sin código repetido en cada ruta.
  - Excepciones de dominio (`ErrorCita`) con código HTTP: **Por qué:** la lógica de citas no depende de FastAPI (la reutilizará el asistente por WhatsApp) y la API solo traduce el error a la respuesta.
  - `re` (expresiones regulares, biblioteca estándar): **Por qué:** normaliza teléfonos de distintas fuentes (formulario, Twilio) a un único formato para encontrar al mismo transportista.
  - `asyncio.to_thread`: ver `d1a97ad`. Aquí la sincronización de estados de citas con la BD corre fuera del event loop; las modificaciones al simulador (inyectar citas) se hacen siempre dentro del loop.
  - Patrón **callback** (`al_cambiar_cita`): **Por qué:** el simulador avisa de los cambios de estado sin conocer la BD; el servicio decide cuándo guardarlos.

- **Herramientas de IA:** Claude (Opus 5.5) diseñó e implementó el flujo de citas y su integración con el simulador y el pronóstico, escribió 15 pruebas nuevas, verificó las 90 con PostgreSQL de prueba y el flujo completo con el servidor en vivo.

### 2026-11-11 18:25 · `#008` · M7 API pública para vecinos

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/publico/servicio.py` | Arma la información pública por caseta. | `horas_pico()`: une las franjas consecutivas con semáforo Lento o Saturado del pronóstico de 12 h en intervalos (inicio, fin, peor semáforo y espera máxima); `zonas()`: para cada caseta, semáforo y espera actuales, si está abierta, horas pico y la mejor hora para circular (franja con menor espera prevista). Usa el Mundo B y solo datos agregados de tráfico. |
  | `backend/app/api/publico.py` (implementado) | Ruta pública. | `GET /api/publico/zonas`. |
  | `backend/app/contracts/schemas.py` (modificado) | Contratos. | `ZonaPublica` agrega `acceso_id`, `nombre`, `abierto` y `mejor_hora`; `HoraPico` agrega `espera_max_min`. |
  | `backend/tests/test_publico.py` (5) | Pruebas. | Unión de franjas en horas pico, sin congestión no hay picos, zonas desde el simulador, caseta cerrada en rojo, y que la respuesta pública no contenga teléfonos, transportistas, citas ni la comparación A/B. |
  | `backend/tests/test_api.py` (modificado) | — | Se retira la prueba de "pendiente" de la vista pública. |
  | `docs/contracts.md`, `docs/openapi.json` (actualizados) | Contratos. | Campos nuevos y reglas de privacidad de la vista pública. |

- **Funcionalidad:** cualquier vecino puede consultar, sin iniciar sesión, cómo está cada caseta en este momento (Fluye, Lento o Saturado), a qué horas de las próximas 12 h se espera congestión y cuál es la mejor hora para pasar. La respuesta nunca incluye datos personales ni de operación del puerto. Pruebas: 94 con PostgreSQL de prueba, 85 sin él.

- **Tecnologías usadas:**
  - `Pydantic`: ver `aae10d9`. Aquí el modelo `ZonaPublica` define exactamente qué campos salen a la vista pública; lo que no está en el esquema no se puede filtrar por error.
  - `datetime.timedelta` (biblioteca estándar): aritmética de fechas. **Por qué:** calcula el fin de cada franja y detecta franjas consecutivas para unirlas en un solo intervalo de hora pico.

- **Herramientas de IA:** Claude (Opus 5.5) diseñó e implementó la vista pública, amplió el contrato con los campos que necesita la pantalla y escribió 5 pruebas, incluida una de privacidad de la respuesta.

### 2026-11-11 18:50 · `#009` · M6 y M7 Frontend: tablero del operador y vista pública

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `frontend/operador/index.html` | Tablero del operador (`/operador/`, también en `/`). | Encabezado con logotipo, etiqueta SIMULACIÓN, reloj simulado, pausa/reanudar y velocidad; tarjetas por caseta; mapa en vivo (sin Fluport, con Fluport o lado a lado); inyección de eventos y eventos recientes; pronóstico de 12 h; impacto de Fluport; citas (estados, % de cumplimiento, formulario para agendar y tabla). Estructura accesible: `<header>`, `<nav>`, `<main>`, secciones con título, botones y campos reales con etiqueta. |
  | `frontend/publico/index.html` | Vista pública para vecinos (`/publico/`), pensada para celular. | Una tarjeta por caseta con estado, espera actual, horas pico y mejor hora para pasar; ordenadas de la más saturada a la más libre. |
  | `frontend/static/js/comun.js` | Utilidades compartidas. | `el()` crea elementos sin interpretar texto como HTML (evita inyección de código); `chip()` dibuja el semáforo con símbolo y texto; `hora()` y `fecha()` muestran todo en hora de Veracruz; `api()` llama a la API y traduce errores a mensajes legibles; `conectarSimulacion()` usa el WebSocket y, si falla, consulta `/api/sim/snapshot` cada segundo y reintenta el WebSocket cada 5 s; `horasPico()`. |
  | `frontend/static/js/operador.js` | Lógica del tablero. | `crearMapa()` con Leaflet: dibuja las rutas del GeoJSON y las casetas; `posicion()` interpola la ubicación de cada camión sobre su ruta a partir de su progreso 0–1; la fila se dibuja hacia atrás sobre la ruta; los marcadores se reutilizan entre actualizaciones; `render()` actualiza casetas, impacto, eventos y mapas con cada snapshot; `cargarPronostico()` (cada 15 s) dibuja las barras con los umbrales de 30 y 90 min, las horas pico y la mejor hora; `cargarCitas()` (cada 10 s); `buscarHorarios()` y `agendar()` usan las sugerencias y crean la cita; `inyectarEvento()` y `control()`. |
  | `frontend/static/js/publico.js` | Lógica de la vista pública. | Consulta `/api/publico/zonas` cada 30 s y arma las tarjetas. |
  | `frontend/static/css/app.css` | Estilos de las pantallas. | Diseño fluido: en celular las columnas se apilan y la tabla se desplaza dentro de su caja; botones de al menos 44 px; foco visible para teclado; números tabulares en cifras y horas. |
  | `frontend/static/css/tokens.css` (modificado) | Tokens. | Se retira el pseudo-elemento de puntos del logotipo (se dibujaban dos veces); los puntos son `<span>` en el HTML. |
  | `frontend/static/favicon.svg` | Ícono de la pestaña con los tres puntos del semáforo. | — |
  | `frontend/static/vendor/leaflet/` | Leaflet 1.9.4 (JS, CSS e imágenes), servido localmente. | Descargado del release oficial en GitHub (`leaflet.zip`), sin npm. |
  | `backend/app/db/base.py` (modificado) | Conexión a PostgreSQL. | La sesión usa la zona horaria `America/Mexico_City`: las fechas de las citas salían en UTC (16:00 en vez de 10:00). |
  | `backend/tests/test_frontend.py` (11) | Pruebas. | Las dos páginas y sus 8 archivos estáticos se sirven; ninguna página carga scripts o estilos externos. |

- **Funcionalidad:** con `uvicorn app.main:app` y el navegador en `http://localhost:8000` el operador ve el puerto en vivo: casetas con su semáforo, camiones moviéndose por las rutas hacia cada caseta, la comparación con y sin Fluport, el pronóstico, el ahorro acumulado y las citas. Desde la misma pantalla puede pausar o acelerar la simulación, cerrar o reabrir una caseta, provocar un buque, un norte o carga urgente, y agendar una cita eligiendo entre los 3 mejores horarios. Los vecinos tienen su propia página en `/publico/`. Verificado en Chrome de escritorio y de celular: cita agendada desde la página, evento aplicado, vista lado a lado y sin errores de JavaScript. Pruebas: 105 con PostgreSQL de prueba, 96 sin él.

- **Tecnologías usadas:**
  - `Leaflet`: biblioteca de mapas interactivos en JavaScript. **Por qué:** ligera (~150 KB), funciona con un archivo local sin compilación y dibuja directamente GeoJSON, líneas y marcadores; se sirve desde el propio servidor para no depender de un CDN.
  - Mosaicos de **OpenStreetMap**: fondo del mapa con su atribución obligatoria. **Por qué:** gratuitos para uso ligero; si no hay internet, el mapa sigue mostrando rutas, casetas y camiones sobre el fondo de color.
  - **JavaScript sin framework ni compilación** (DOM + `fetch` + `WebSocket`): **Por qué:** cumple la restricción de no usar npm y basta para pantallas que solo muestran datos de la API; se actualiza al guardar el archivo.
  - `Intl.DateTimeFormat` / `Intl.NumberFormat` (APIs estándar del navegador): **Por qué:** muestran horas en la zona de Veracruz y cifras con el formato de México sin librerías.
  - `L.circleMarker` y `L.divIcon` de Leaflet: **Por qué:** cientos de camiones se dibujan como círculos vectoriales (rápidos) y las casetas como etiquetas con el estilo del semáforo.
  - `playwright` con Chrome: navegador automatizado. **Por qué:** se usó solo para verificar las pantallas durante el desarrollo (capturas y flujo de cita); no forma parte de la aplicación ni de sus dependencias.
  - PostgreSQL `timezone` por conexión (`options=-c timezone=…`): **Por qué:** que la base devuelva las fechas en la misma zona que el simulador.

- **Herramientas de IA:** Claude (Opus 5.5) diseñó las pantallas (lienzo de diseño aprobado), las implementó en HTML, CSS y JavaScript conectadas a la API, las probó en Chrome automatizado en escritorio y celular, corrigió tres defectos encontrados (logotipo duplicado, horas en UTC, porcentaje engañoso al arrancar) y escribió 11 pruebas.

### 2026-11-11 18:55 · `#010` · M4 Asistente de citas con Gemini

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/assistant/llm.py` | Cliente de Gemini. | `ClienteGemini.generar()` llama a la API REST `generateContent` de Gemini con la clave en el encabezado `x-goog-api-key`, las instrucciones del sistema y las herramientas declaradas, y devuelve el turno del modelo tal cual (incluida su firma de pensamiento, que la API pide reenviar en el siguiente paso); `ClienteLLM` (interfaz) permite cambiar de proveedor o usar uno simulado en pruebas; `ErrorLLM`. |
  | `backend/app/assistant/agente.py` | El asistente. | `HERRAMIENTAS`: 6 funciones que el modelo puede pedir (`consultar_espera`, `sugerir_horario`, `crear_cita`, `reprogramar_cita`, `cancelar_cita`, `mis_citas`) con sus parámetros; `instrucciones()`: fecha y hora del reloj simulado, casetas, tipos de carga y reglas (respuestas breves, ofrecer 3 opciones y agendar solo cuando el usuario confirme, no inventar datos, la terminal conserva el control); `Herramientas` ejecuta cada función sobre el servicio de citas y el pronóstico, interpreta fechas en hora de Veracruz y **solo permite tocar las citas del teléfono que escribe**; `Asistente.responder()`: carga el historial del remitente, llama al modelo, ejecuta herramientas hasta 5 rondas y guarda la conversación; respaldo sin LLM o si Gemini falla (estado de las casetas en texto); `cargar_historial()` / `guardar_turnos()` en la tabla `mensaje_asistente`. |
  | `backend/app/api/asistente.py` (modificado) | Ruta del asistente. | `POST /api/asistente/mensaje` implementado (422 si el teléfono es inválido). |
  | `backend/app/citas/servicio.py` (modificado) | Teléfonos. | `normalizar_telefono()` unifica los celulares de México que llegan como `+521…` (con el "1" extra) y `+52…`, para que sean el mismo transportista. |
  | `backend/app/config.py`, `backend/.env.example` (modificados) | Configuración. | Modelo por defecto `gemini-3.6-flash`; variable `FLUPORT_LLM_API_KEY`. |
  | `backend/requirements.txt` (modificado) | Dependencias. | Se retira `anthropic`: el asistente usa Gemini mediante `httpx`, que ya estaba instalado. |
  | `backend/tests/test_asistente.py` (14) | Pruebas con un LLM simulado que sigue un guion. | Declaraciones de herramientas, instrucciones con la hora simulada, respaldo sin clave, consulta de espera, herramienta desconocida y datos inválidos, fechas sin zona; con BD: flujo completo "llego mañana a las 9 con un contenedor de 40" → 3 opciones → "la primera" → cita creada con origen WhatsApp y con el historial del primer mensaje, no puede cancelar citas ajenas, mis citas y cancelar, falla de Gemini, límite de 5 rondas, teléfono inválido, y formato exacto de la petición REST a Gemini. |
  | `backend/tests/test_citas.py` (modificado) | — | Caso del celular `+521…`. |
  | `docs/contracts.md`, `docs/openapi.json` (actualizados) | Contratos. | Ruta y reglas del asistente. |

- **Funcionalidad:** un transportista puede escribir en lenguaje natural ("llego mañana a las 9 con un contenedor de 40"); el asistente busca los 3 horarios con menor espera, los ofrece con caseta y minutos estimados, y al confirmar agenda la cita, que aparece en el tablero y en la simulación. También responde cómo está la fila, lista sus citas, las cambia o cancela. Recuerda la conversación de cada teléfono. Si no hay clave de Gemini o el servicio falla, responde con el estado de las casetas. Pruebas: 119 con PostgreSQL de prueba, 104 sin él. Pendiente: probar con la clave real de Gemini.

- **Tecnologías usadas:**
  - **Gemini API** (`generateContent`, modelo `gemini-3.6-flash`): modelo de lenguaje de Google con **llamadas a herramientas** (*function calling*). **Por qué:** el modelo no inventa horarios ni citas; decide qué función llamar y con qué datos, y Fluport ejecuta la acción con sus propias reglas y validaciones. Modelo estable de la familia Flash: rápido y económico para mensajes cortos.
  - `httpx.AsyncClient`: cliente HTTP asíncrono. **Por qué:** la llamada a Gemini no bloquea el simulador ni las demás peticiones mientras espera la respuesta, y evita agregar el SDK de Google como dependencia.
  - Esquemas **OpenAPI/JSON Schema** para declarar herramientas: **Por qué:** es el formato que Gemini entiende para saber qué parámetros pedir (por ejemplo, el tipo de carga con sus valores válidos).
  - `zoneinfo`: ver `d1a97ad`. Aquí interpreta las horas que da el modelo en hora de Veracruz cuando no traen zona.
  - `httpx.MockTransport` (pruebas): responde peticiones HTTP sin red. **Por qué:** verifica que la petición a Gemini tiene el formato correcto sin gastar llamadas reales.
  - Tabla `mensaje_asistente` con `JSONB`: ver `aae10d9`. Guarda cada turno de la conversación tal cual lo espera Gemini.

- **Herramientas de IA:** Claude (Opus 5.5) consultó la documentación vigente de Gemini (formato REST, firmas de pensamiento, modelos estables), diseñó el asistente y sus herramientas, lo probó con un LLM simulado (14 pruebas) y corrigió con ellas la duplicación de teléfonos `+521`/`+52`.

### 2026-11-11 19:05 · `#011` · Ajustes del asistente tras la primera prueba con Gemini real

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/assistant/agente.py` (modificado) | Instrucciones del asistente. | Formato de WhatsApp: negritas con un solo asterisco y sin Markdown (Gemini respondía con `**07:30**`, que WhatsApp no interpreta); la ventana de búsqueda se centra en la hora que menciona el transportista. |
  | `backend/app/citas/servicio.py` (modificado) | Orden de las sugerencias. | Las esperas que difieren menos de 5 min se consideran iguales (`TRAMO_EMPATE_MIN`) y se desempata por la franja que empieza más cerca de la hora pedida: con el puerto tranquilo, "llego a las 9" ahora sugiere primero las 9:00 y no las 7:30. |
  | `backend/tests/test_citas.py` (modificado) | Pruebas. | Nueva prueba de desempate por cercanía a la hora pedida; la prueba de orden compara por tramos de 5 min. |

- **Funcionalidad:** en la primera prueba con Gemini real el asistente entendió "llego mañana a las 9 con un contenedor de 40", consultó los horarios y ofreció 3 opciones; con estos ajustes las opciones quedan alrededor de la hora pedida y el texto se ve bien en WhatsApp. Pruebas: 120 con PostgreSQL de prueba, 105 sin él.

- **Tecnologías usadas:** sin tecnologías nuevas (ver `#010`).

- **Herramientas de IA:** Claude (Opus 5.5) analizó la respuesta real de Gemini, ajustó instrucciones y orden de sugerencias, y agregó la prueba correspondiente.

### 2026-11-11 19:10 · `#012` · Asistente más rápido y robusto

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/assistant/llm.py` (modificado) | Cliente de Gemini. | Envía `generationConfig.thinkingConfig.thinkingLevel` (por defecto `low`): Gemini 3 razona en nivel alto si no se indica, y en la prueba real la primera respuesta superó los 30 s del límite; reintenta una vez si Gemini responde 429/5xx o se agota el tiempo; el error registrado ahora incluye el tipo de excepción (antes un tiempo agotado aparecía vacío). |
  | `backend/app/assistant/agente.py` (modificado) | Asistente. | `formato_whatsapp()` convierte en código `**x**` → `*x*`, `__x__` → `_x_` y quita encabezados `#` (el modelo seguía usando Markdown pese a las instrucciones); el historial enviado se limita a los últimos 30 minutos reales para que respuestas como "la primera" no se refieran a opciones de una conversación anterior. |
  | `backend/app/config.py`, `backend/.env.example` (modificados) | Configuración. | `FLUPORT_LLM_PENSAMIENTO` (minimal \| low \| medium \| high) y `llm_historial_min`. |
  | `backend/tests/test_asistente.py` (modificado) | Pruebas. | La petición incluye el nivel de razonamiento, reintento tras un 503, conversión de formato a WhatsApp. |

- **Funcionalidad:** el asistente responde más rápido y con el formato correcto de WhatsApp; si Gemini se satura o tarda, reintenta antes de usar la respuesta de respaldo. Pruebas: 122 con PostgreSQL de prueba, 107 sin él.

- **Tecnologías usadas:**
  - `thinkingLevel` de Gemini 3: controla cuánto razona el modelo antes de responder. **Por qué:** en un chat de citas las decisiones las toman las herramientas de Fluport; un nivel bajo reduce la latencia y el costo sin perder calidad.
  - `re` (expresiones regulares): ver `#007`. Aquí normaliza el formato del texto para WhatsApp.

- **Herramientas de IA:** Claude (Opus 5.5) diagnosticó el tiempo agotado a partir del log del servidor, consultó la documentación de Gemini sobre niveles de razonamiento e implementó y probó los ajustes.

### 2026-11-11 19:20 · `#013` · Asistente: una sola llamada a Gemini por mensaje

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/assistant/agente.py` (modificado) | Respuestas con plantilla. | `redactar()` arma el mensaje de WhatsApp a partir del resultado de cada herramienta (opciones numeradas, confirmación de cita, cambio, cancelación, lista de citas, estado de casetas); si todas las herramientas de la ronda terminaron sin error, se responde con la plantilla y **no se vuelve a llamar a Gemini**; si alguna falló, Gemini redacta la explicación. El turno de plantilla se guarda en el historial como respuesta del modelo para que el siguiente mensaje ("la 1") tenga contexto. |
  | `backend/app/assistant/llm.py` (modificado) | Cliente de Gemini. | Un tiempo agotado ya no se reintenta (duplicaba la espera a ~60 s); el límite por llamada baja a 25 s y es configurable. |
  | `backend/app/config.py` (modificado) | Configuración. | `llm_timeout_s`. |
  | `backend/tests/test_asistente.py` (modificado) | Pruebas. | El flujo completo hace una sola llamada al LLM por mensaje; plantillas; con error, el LLM redacta; tiempo agotado sin reintento. |

- **Funcionalidad:** cada mensaje del transportista requiere ahora una sola respuesta de Gemini (decidir qué hacer); la redacción la hace Fluport al instante, así que el tiempo de respuesta baja aproximadamente a la mitad y las respuestas tienen siempre el mismo formato claro. En la prueba real previa, las llamadas a Gemini tardaron entre 2 y más de 30 s según la carga del servicio. Pruebas: 124 con PostgreSQL de prueba, 109 sin él.

- **Tecnologías usadas:** sin tecnologías nuevas (ver `#010` y `#012`).

- **Herramientas de IA:** Claude (Opus 5.5) midió el problema con los tiempos reportados en la prueba real, rediseñó el flujo del asistente para reducir llamadas al LLM y actualizó las pruebas.

### 2026-11-11 19:25 · `#014` · Asistente: modelo de respaldo cuando Gemini está saturado

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/assistant/llm.py` (modificado) | Cliente de Gemini con respaldo. | `ClienteGemini.generar()` intenta el modelo principal y, si responde 429/5xx, falla la conexión o tarda más del límite, repite la petición con el modelo de respaldo; un error 400 (petición inválida) no se reintenta; `_sin_firmas()` quita las firmas de pensamiento al cambiar de modelo, porque pertenecen al modelo que las generó (el historial original no se modifica); `ultimo_modelo` indica cuál respondió; `_Temporal` distingue fallas pasajeras. |
  | `backend/app/config.py`, `backend/.env.example` (modificados) | Configuración. | `FLUPORT_LLM_MODELO_RESPALDO` (por defecto `gemini-3.5-flash-lite`) y `FLUPORT_LLM_TIMEOUT_S` (12 s por modelo). |
  | `backend/app/assistant/agente.py` (modificado) | — | Pasa el modelo de respaldo y el límite al cliente. |
  | `backend/tests/test_asistente.py` (modificado) | Pruebas. | 503 del principal → responde el respaldo sin firmas; tiempo agotado en ambos → error tras 2 intentos; 400 → no usa respaldo. |

- **Funcionalidad:** medición directa con la petición completa del asistente: `gemini-3.6-flash` respondió en 3.5 s, y en el siguiente intento devolvió 503 por alta demanda; la lentitud venía de la saturación del modelo, no de Fluport. Ahora, si el modelo principal está saturado o tarda más de 12 s, el asistente usa automáticamente `gemini-3.5-flash-lite`, de modo que la respuesta tarda como máximo unos 25 s y casi siempre mucho menos. Pruebas: 125 con PostgreSQL de prueba, 110 sin él.

- **Tecnologías usadas:**
  - **Gemini 3.5 Flash-Lite** como modelo de respaldo: modelo más ligero y rápido de la familia. **Por qué:** en el asistente el modelo solo decide qué herramienta usar con qué datos; un modelo ligero basta y tiene menos demanda que el principal.
  - Patrón de **respaldo (*fallback*)** ante fallas pasajeras: **Por qué:** en una demo en vivo una saturación momentánea del proveedor no debe dejar al transportista sin respuesta.

- **Herramientas de IA:** Claude (Opus 5.5) diseñó la prueba de diagnóstico que aisló el problema (petición directa a Gemini fuera del servidor), implementó el respaldo y sus pruebas.

### 2026-11-11 19:35 · `#015` · M5 WhatsApp con Twilio y avisos proactivos

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/messaging/twilio.py` | Integración con Twilio. | `firma()` / `firma_valida()`: verifican que cada webhook viene de Twilio (HMAC-SHA1 con el Auth Token sobre la URL más los parámetros ordenados, comparación en tiempo constante); `parsear_formulario()` lee el formulario de Twilio sin dependencias extra; `enviar()` manda un WhatsApp por la API REST de Twilio; `a_whatsapp()` y `recordar_direccion()` responden con la misma dirección con la que escribió el transportista (`+521…` o `+52…`). |
  | `backend/app/messaging/avisos.py` | Reglas de los avisos proactivos. | `revisar()` revisa las citas activas y genera, una sola vez por cita: `turno_30min` ("En 20 min es tu turno…") y `saturacion` cuando la caseta está cerrada o tendrá ≥ 45 min de espera en las próximas 3 h, proponiendo la mejor alternativa (otra hora o caseta que ahorre ≥ 15 min) con "Responde *SÍ* para cambiarla". |
  | `backend/app/messaging/servicio.py` | Orquestación. | `atender_mensaje()`: mensaje entrante → asistente → respuesta por WhatsApp; `ciclo_avisos()`: lee citas en un hilo, calcula avisos con el simulador, los guarda en la tabla `aviso`, los publica en el tablero (WebSocket), los envía y marca enviado/fallido; cada aviso se agrega al historial del asistente; `en_segundo_plano()` guarda referencias a las tareas. |
  | `backend/app/api/asistente.py` (modificado) | Rutas. | `POST /webhook/whatsapp` (firma validada, 403 si no coincide; responde de inmediato con TwiML vacío y contesta en segundo plano); `GET /api/avisos`; `GET /api/whatsapp/enlace` (enlace wa.me de respaldo). Se retiran las rutas de WhatsApp Cloud API (Meta) y Telegram. |
  | `backend/app/assistant/agente.py` (modificado) | Asistente. | El historial conserva un aviso automático como contexto aunque sea el primer turno; nueva regla: un "SÍ" a un aviso reprograma la cita a la opción propuesta. |
  | `backend/app/sim/servicio.py` (modificado) | Servicio en vivo. | Ejecuta el ciclo de avisos cada 5 ticks (requiere BD). |
  | `backend/app/config.py`, `backend/.env.example` (modificados) | Configuración. | `FLUPORT_TWILIO_ACCOUNT_SID`, `…_AUTH_TOKEN`, `…_WHATSAPP_FROM`, `…_WEBHOOK_URL`, `twilio_validar_firma`, `FLUPORT_AVISOS_ACTIVOS`. |
  | `frontend/operador/index.html`, `frontend/static/js/operador.js` (modificados) | Tablero. | Nueva tarjeta "Avisos por WhatsApp": carga los últimos al abrir y agrega en vivo los que llegan por WebSocket. |
  | `backend/tests/test_whatsapp.py` (14) | Pruebas con Twilio y Gemini simulados. | Firma (ida y vuelta, alteraciones, vector calculado de forma independiente), formulario y direcciones, envío sin configuración, petición exacta a la API de Twilio, aviso de turno sin repetición, aviso por cierre con alternativa en otra caseta, sin aviso si ya va en camino o si fluye; con BD: webhook con firma inválida (403), webhook que responde por WhatsApp, ciclo de avisos (guarda, publica, envía, no repite, queda en el historial), flujo aviso → "SÍ" → cita reprogramada, enlace wa.me. |
  | `backend/tests/test_api.py` (modificado) | — | Se retira la prueba de verificación de Meta. |
  | `docs/contracts.md`, `docs/openapi.json` (actualizados) | Contratos. | Webhook de Twilio, avisos y enlace. |

- **Funcionalidad:** el transportista escribe al número de WhatsApp de Fluport y el asistente le contesta ahí mismo: consulta la fila, agenda, cambia o cancela citas. Fluport además le escribe por iniciativa propia: 30 minutos antes de su turno y cuando su caseta se cierra o se satura, proponiéndole otra hora o caseta; si responde "SÍ", la cita se cambia sola. Cada aviso aparece en vivo en el tablero del operador. Verificado en el navegador: el aviso llegó al tablero. Pruebas: 137 con PostgreSQL de prueba, 117 sin él. Pendiente: probar con el Sandbox real de Twilio.

- **Tecnologías usadas:**
  - **Twilio WhatsApp Sandbox**: número de WhatsApp de prueba de Twilio. **Por qué:** permite enviar y recibir WhatsApp reales en minutos, sin aprobación de Meta; ideal para una demo con teléfonos del equipo.
  - **Webhooks con firma HMAC-SHA1** (`hmac`, `hashlib`, `base64` de la biblioteca estándar): **Por qué:** garantizan que solo Twilio puede mandar mensajes al webhook; `hmac.compare_digest` evita ataques por tiempo de comparación.
  - **API REST de Twilio** con `httpx` (autenticación básica con Account SID y Auth Token): **Por qué:** responder fuera del webhook evita el límite de tiempo de Twilio cuando Gemini tarda, y permite los avisos proactivos; no requiere el SDK de Twilio.
  - **TwiML**: XML de respuesta de Twilio; se devuelve vacío para confirmar la recepción de inmediato.
  - `urllib.parse.parse_qsl`: lee formularios `application/x-www-form-urlencoded` sin agregar `python-multipart`.
  - `asyncio.create_task`: procesa cada mensaje en segundo plano.

- **Herramientas de IA:** Claude (Opus 5.5) verificó en la documentación de Twilio el algoritmo de firma y la recomendación de responder rápido, implementó el canal y los avisos, escribió 14 pruebas con Twilio y Gemini simulados (incluido el flujo aviso → "SÍ" → reprogramación) y comprobó el aviso en el tablero con Chrome automatizado.

### 2026-11-11 19:55 · `#016` · Canal de Telegram para el asistente y los avisos

- **Justificación del cambio:** el plan proponía WhatsApp con el Sandbox de Twilio. Al configurarlo, los mensajes `join <código>` enviados al número del Sandbox no llegaron a Twilio (no aparecían en el registro de mensajes de la consola), lo que impedía cualquier prueba real a pocas horas del cierre. Se adopta **Telegram** como canal de la demo porque: el bot se crea en minutos y sin aprobación; no exige unir cada teléfono a un sandbox; no tiene la restricción de WhatsApp de enviar texto libre solo dentro de una ventana de 24 h (crítica para los avisos proactivos); y con *long polling* funciona sin URL pública ni túnel. El canal de WhatsApp con Twilio (`#015`) se conserva completo y probado: si el Sandbox se resuelve, se activa solo con las variables de entorno, y el asistente, las citas y los avisos son los mismos en ambos canales.

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/app/messaging/telegram.py` | Cliente de la Bot API de Telegram. | `enviar()` manda mensajes con formato `*negritas*` y, si Telegram no puede interpretar el formato, los reenvía como texto plano; `obtener_actualizaciones()` hace *long polling* (`getUpdates`, espera hasta 25 s por mensajes nuevos); `quitar_webhook()`; `TECLADO_CONTACTO` (botón "Compartir mi número") y `QUITAR_TECLADO`. |
  | `backend/app/messaging/bot_telegram.py` | El bot. | `procesar_update()`: chat nuevo → bienvenida y botón para compartir el número; contacto → `registrar_contacto()` liga el chat con el transportista de ese teléfono (lo crea si no existe) **solo si es el propio contacto del usuario**; texto → asistente (el mismo de WhatsApp y web) → respuesta; ignora grupos; `/start` recuerda cómo usarlo. `PollingTelegram`: tarea en segundo plano que lee mensajes, avanza el `offset` y reintenta si falla la red. |
  | `backend/alembic/versions/0002_telegram_en_transportista.py` | Migración. | Agrega `transportista.telegram_chat_id` (único). Probada de ida y vuelta. |
  | `backend/app/db/models.py` (modificado) | Esquema. | Campo `telegram_chat_id`. |
  | `backend/app/messaging/avisos.py`, `servicio.py` (modificados) | Avisos por canal. | `canal_de()` elige Telegram si el transportista se registró en el bot y, si no, WhatsApp; `enviar_aviso()`; el aviso se guarda en el historial del asistente del mismo canal, para que un "SÍ" tenga contexto. |
  | `backend/app/api/asistente.py` (modificado) | Rutas. | `POST /webhook/telegram` (modo webhook, valida el encabezado secreto de Telegram); `GET /api/telegram/enlace` (enlace t.me del bot). |
  | `backend/app/main.py` (modificado) | Arranque. | Inicia y detiene el *polling* de Telegram junto con la app. |
  | `backend/app/config.py`, `backend/.env.example` (modificados) | Configuración. | `FLUPORT_TELEGRAM_TOKEN`, `FLUPORT_TELEGRAM_MODO` (`polling` \| `webhook` \| `off`), `FLUPORT_TELEGRAM_WEBHOOK_SECRET`. |
  | `frontend/operador/index.html`, `frontend/static/js/operador.js` (modificados) | Tablero. | La tarjeta pasa a "Avisos a transportistas" y muestra el canal de cada aviso. |
  | `backend/tests/test_telegram.py` (10) | Pruebas con la Bot API simulada. | Envío sin configuración, reenvío sin formato ante error de interpretación, *long polling* con `offset`, bucle de *polling* que procesa y avanza; con BD: chat nuevo pide contacto, grupos ignorados, contacto ajeno rechazado, registro y conversación con el asistente, aviso enviado por Telegram (no por WhatsApp), webhook (404 en modo polling, 403 con secreto inválido, 200 con secreto correcto). |
  | `README.md`, `docs/contracts.md`, `docs/openapi.json` (actualizados) | Documentación. | Canal de Telegram, rutas y reglas. |

- **Funcionalidad:** el transportista abre el bot de Fluport en Telegram, comparte su número con un botón y desde ahí conversa con el asistente igual que por WhatsApp: consulta la fila, agenda, cambia o cancela citas. Los avisos de turno y de caseta saturada o cerrada le llegan por Telegram y aparecen en el tablero con su canal. No requiere túnel ni URL pública. Pruebas: 147 con PostgreSQL de prueba, 121 sin él. Pendiente: crear el bot y probarlo con un teléfono real.

- **Tecnologías usadas:**
  - **Telegram Bot API** (`sendMessage`, `getUpdates`, `deleteWebhook`, `getMe`): API HTTP oficial para bots. **Por qué:** gratuita, sin aprobación ni sandbox, permite mensajes proactivos en cualquier momento y se usa con `httpx` sin bibliotecas extra.
  - **Long polling**: Fluport pide los mensajes nuevos y Telegram mantiene abierta la petición hasta que llega alguno. **Por qué:** funciona detrás de cualquier red (laptop, hosting) sin exponer una URL pública; el `offset` garantiza que cada mensaje se procese una sola vez.
  - **Botón de contacto** (`request_contact`): Telegram comparte el número verificado de la cuenta. **Por qué:** identifica al transportista por su teléfono sin que lo escriba, y se comprueba que el contacto es el suyo (`user_id`) para que nadie registre un número ajeno.
  - **Webhook con secreto** (`X-Telegram-Bot-Api-Secret-Token`): alternativa para hosting; Telegram firma cada petición con el secreto configurado.
  - `Alembic`: ver `aae10d9`. Segunda migración del esquema.

- **Herramientas de IA:** Claude (Opus 5.5) comparó alternativas a Twilio (Telegram, WhatsApp Cloud API directa, otros proveedores y chat en el tablero), implementó el canal de Telegram reutilizando el asistente y los avisos, generó y probó la migración, y escribió 10 pruebas.

### 2026-11-11 21:45 · `#017` · Flujo por actores: vista pública, agencias y panel de demostración

- **Justificación del cambio:** el tablero único mezclaba tres papeles distintos: el del público, el de quien supervisa a los transportistas y el del presentador que controla la simulación. Se separa el flujo por actores: **la agencia** controla a sus transportistas y ve cómo van sus camiones y el flujo del puerto; **el público** ve el estado de contingencia de cada entrada y los tiempos estimados en tiempo real, y desde ahí entra directo al bot; **el transportista** lleva sus citas en el bot de Telegram. Los controles de la simulación salen de la vista de agencia, porque una agencia no cierra casetas ni acelera el reloj.

- **Qué se agregó:**

  | Archivo | Qué hace | Funciones / elementos principales |
  |---|---|---|
  | `backend/data/escenario.json`, `backend/app/sim/escenario.py` (modificados) | Agencias de la demo. | Tres agencias ficticias con su participación en los camiones simulados (`AgenciaParam`); `agencia_de()` asigna cada camión simulado a una agencia según el `crc32` de su id, de forma fija y sin consumir números aleatorios, para no alterar los resultados de la simulación ni de las pruebas. |
  | `backend/app/db/models.py` (modificado) y `backend/alembic/versions/0003_agencias.py` | Esquema. | Tabla `agencia` y `transportista.agencia_id` (FK con índice; si se borra la agencia, el transportista queda independiente). Migración probada de ida y vuelta y verificada con `alembic check`. |
  | `backend/app/sim/persistencia.py` (modificado) | Siembra. | `sembrar_accesos()` también inserta o actualiza las agencias del escenario al arrancar. |
  | `backend/app/sim/demanda.py`, `mundo.py`, `motor.py` (modificados) | Simulación por agencia. | `CamionPlan.agencia_id`; cada mundo acumula esperas, camiones atendidos y paso por la fila por agencia; `flota()` cuenta **todos** los camiones activos de cada agencia por estado (no solo los dibujados) y su espera promedio; el camión de una cita real hereda la agencia de su transportista. |
  | `backend/app/contracts/schemas.py` (modificado) | Contratos. | `FlotaAgencia` y `MundoEstado.flota`; `CamionEstado.agencia_id`; `CitaCreate.agencia_id` (agencia del transportista si se crea uno nuevo); `ZonaPublica.contingencia` (`normal`, `lenta`, `saturada`, `cerrada`) y `norte`; `AgenciaOut` y `TransportistaOut` (teléfono enmascarado: solo los últimos 4 dígitos). |
  | `backend/app/api/agencias.py` | API de agencias. | `GET /api/agencias` (con número de transportistas); `GET /api/agencias/{id}/transportistas` (alias, final del teléfono, si usa Telegram, citas activas y próxima cita). |
  | `backend/app/api/citas.py`, `asistente.py`, `backend/app/citas/servicio.py` (modificados) | Filtros por agencia. | `agencia_id` opcional en `GET /api/citas`, `GET /api/citas/resumen` y `GET /api/avisos`; valida que la agencia exista al crear un transportista. |
  | `backend/app/messaging/bot_telegram.py` (modificado) | Enlace de agencia. | `t.me/<bot>?start=AG01` llega como `/start AG01`: si el chat es nuevo, el código se guarda hasta que comparte su número y queda ligado a esa agencia; si ya estaba registrado, cambia de agencia. Un código inexistente se ignora. |
  | `backend/app/publico/servicio.py` (modificado) | Contingencia. | Traduce el semáforo y el estado de cada caseta a la contingencia pública y marca si hay norte. |
  | `backend/app/main.py` (modificado) | Rutas de páginas. | `/` lleva a la vista pública; `/agencia/` y `/demo/`; `/operador/` redirige a `/agencia/`. |
  | `frontend/agencia/index.html` | Vista de agencia. | Selector de agencia (se recuerda en el navegador o se elige con `?agencia=AG01`); casetas; mapa solo con los camiones de la agencia; "Mi flota ahora" (en ruta, en fila, en revisión, dentro, atendidos y espera promedio); invitación al bot con QR y enlace propio de la agencia; avisos a sus transportistas; pronóstico; lista de sus transportistas; citas de la agencia con formulario para agendar a uno de sus choferes. |
  | `frontend/demo/index.html` | Panel de demostración. | Lo que era el tablero del operador sin la sección de citas: reloj, pausa y velocidad, mapas sin y con Fluport, inyección de eventos, avisos, pronóstico e impacto. |
  | `frontend/static/js/tablero.js` (antes `operador.js`) | Lógica de ambos tableros. | El modo sale de `<body data-vista>`; en `agencia`: `iniciarAgencia()`, `elegirAgencia()`, `renderFlota()`, `cargarTransportistas()`, `renderInvitacion()` y filtros por agencia en citas y avisos; en `demo`: controles, mundos A/B e impacto. |
  | `frontend/publico/index.html`, `frontend/static/js/publico.js` (modificados) | Vista pública. | Alerta de contingencia (norte, entradas cerradas o saturadas); etiqueta de contingencia por entrada; tarjeta "¿Eres transportista?" con botón y QR al bot; actualización cada 10 s. |
  | `frontend/static/vendor/qrcode/` | Generador de QR. | `qrcode.js` de Kazuhiko Arase (licencia MIT), copiado al proyecto como Leaflet. |
  | `frontend/static/css/app.css` (modificado) | Estilos. | Flota, invitación, QR, alerta, tarjeta del bot y etiquetas de contingencia con la paleta del proyecto. |
  | `backend/tests/conftest.py` (corregido) | Aislamiento de las pruebas. | Las pruebas vacían la llave de Gemini y las credenciales de Twilio y Telegram antes de cargar la app: con un `.env` real, dos pruebas fallaban y una llegaba a llamar a Telegram. |
  | `backend/tests/test_agencias.py` (10), `test_frontend.py` y `test_api.py` (actualizadas) | Pruebas. | Reparto fijo y proporcional de camiones; flota que cuadra con los camiones en fila y atendidos del mundo; agencia heredada por la cita; contingencia cerrada y norte; con BD: catálogo, cita de agencia y filtros (citas, resumen, avisos), teléfono enmascarado, agencia inexistente (404), enlace `/start AG02` antes y después del registro; páginas `/agencia/`, `/demo/` y redirección de `/operador/`. |

- **Funcionalidad:** el público abre `/publico/` y ve, por entrada, si opera normal, lenta, saturada o cerrada, cuánto se espera ahora, las horas pico y la mejor hora; si es transportista, toca "Agenda tu cita en Telegram" o escanea el QR. La agencia abre `/agencia/`, elige su nombre y ve en el mapa solo sus camiones, cuántos van en ruta, en fila o dentro del puerto, la espera promedio de su flota, a sus transportistas con su próxima cita, sus citas y los avisos que reciben; con su QR invita a sus choferes, que al registrarse en el bot quedan ligados a ella. El presentador usa `/demo/` para acelerar el reloj, provocar eventos y mostrar el impacto. Pruebas: 160 con PostgreSQL de prueba.

- **Tecnologías usadas:**
  - **qrcode-generator** (JavaScript, MIT): genera el QR como SVG en el navegador. **Por qué:** un solo archivo sin dependencias, copiado al repositorio (sin npm ni CDN) y sin llamadas de red; el QR se genera a partir de la URL del propio bot.
  - **Deep linking de Telegram** (`?start=<código>`): Telegram abre el chat y envía `/start <código>`. **Por qué:** liga al chofer con su agencia sin que escriba nada ni la agencia capture datos.
  - **crc32** (`zlib`, biblioteca estándar): reparte los camiones simulados entre agencias de forma reproducible. **Por qué:** sortear con el generador aleatorio cambiaría la secuencia de toda la simulación.
  - `Alembic`: ver `aae10d9`. Tercera migración del esquema.

- **Herramientas de IA:** Claude (Opus 5.5) propuso el flujo por actores, implementó las agencias en la simulación, la base de datos, la API, el bot y las tres vistas, generó y verificó la migración, y escribió 10 pruebas nuevas.
