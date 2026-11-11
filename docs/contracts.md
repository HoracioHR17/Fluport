# Fluport — Contratos (M0)

> Congelados. Cualquier cambio requiere aprobación del desarrollador, una nueva migración Alembic y una entrada en la bitácora.
> Fuente de verdad en código: `backend/app/contracts/` (enums + schemas) y `backend/app/db/models.py`.
> Especificación completa: `docs/openapi.json` (también en `/docs` con la app corriendo). Ejemplo de mensaje WS: `docs/ejemplo-snapshot.json`.

## 1. Convenciones
- Fechas ISO 8601 con zona horaria de Veracruz (`-06:00`). Campos `ts_sim` = tiempo **simulado**.
- Tiempos en minutos (`float`). Progreso de ruta `0..1`.
- Identificadores de acceso tipo `"A1"`, rutas `"R-A1-norte"`, camiones `"T-0001"`.
- Mundo `A` = sin Fluport (llegada libre) · Mundo `B` = con Fluport (llegada según cita sugerida).
- Semáforo único (`semaforo_de`): `< 20` verde · `20–45` amarillo · `> 45` rojo (configurable).
- Errores: `422` validación, `404` no existe, `409` conflicto (acceso cerrado / ventana llena), `501` pendiente.

## 2. Base de datos (PostgreSQL)
| Tabla | Propósito | Claves |
|---|---|---|
| `acceso` | Accesos al puerto y su capacidad | `id` (str), `zona`, `carriles`, `tiempo_servicio_min`, `estado` |
| `transportista` | Usuarios del canal (solo teléfonos del equipo) | `telefono` único, `es_demo` |
| `cita` | Citas de entrada | `acceso_id`, `ventana_inicio/fin`, `tipo_carga`, `prioridad`, `estado`, `cita_anterior_id` |
| `buque` | Buques programados/atracados | `eta`, `contenedores`, `estado` |
| `sim_corrida` | Cada ejecución del simulador | `tipo` (vivo/historico), `semilla`, `parametros` (JSONB) |
| `lectura_congestion` | Serie temporal por corrida·mundo·acceso | `ts_sim`, `camiones_en_fila`, `espera_min` + variables para M2 |
| `evento_sim` | Eventos inyectados | `tipo`, `acceso_id`, `payload` (JSONB) |
| `pronostico` | Salida de M2 por franja de 30 min | `franja_inicio`, `espera_min`, `semaforo`, `modelo_version` |
| `aviso` | Avisos proactivos enviados | `canal`, `tipo`, `mensaje`, `estado` |
| `mensaje_asistente` | Historial del asistente por remitente | `remitente`, `rol`, `contenido` (JSONB) |

Enums: `tipo_carga` (contenedor_20, contenedor_40, refrigerado, peligroso, granel, carga_general) · `estado_cita` (agendada, en_ruta, cumplida, no_show, reprogramada, cancelada) · `tipo_evento_sim` (buque_atraca, norte, cierre_acceso, reapertura, carga_urgente, personalizado) · resto en `enums.py`.

## 3. Endpoints REST
| Método | Ruta | Entrada | Salida | Módulo |
|---|---|---|---|---|
| GET | `/api/salud` | — | `Salud` | — |
| GET | `/api/accesos` | — | `AccesoOut[]` | M1 |
| GET | `/api/accesos/estado?mundo=B` | — | `AccesoEstado[]` | M1 |
| GET | `/api/accesos/rutas` | — | GeoJSON `FeatureCollection` (accesos `Point`, rutas `LineString` en `[lon, lat]`) | M1 |
| GET | `/api/pronostico?acceso_id=&horas=12` | — | `PronosticoOut[]` | M2 |
| POST | `/api/citas` | `CitaCreate` | `CitaOut` (201) | M3 |
| GET | `/api/citas?telefono=&transportista_id=&acceso_id=&estado=` | — | `CitaOut[]` | M3 |
| POST | `/api/citas/sugerencias` | `SugerenciaRequest` | `Sugerencia[]` (top 3) | M3 |
| GET | `/api/citas/{id}` | — | `CitaOut` | M3 |
| PATCH | `/api/citas/{id}` | `CitaReprogramar` | `CitaOut` (nueva, con `cita_anterior_id`) | M3 |
| DELETE | `/api/citas/{id}` | — | `CitaOut` (cancelada) | M3 |
| GET | `/api/sim/estado` | — | `SimEstadoOut` | M1 |
| POST | `/api/sim/control` | `SimControl` `{accion: play\|pause\|velocidad\|reset}` | `SimEstadoOut` | M1 |
| POST | `/api/sim/eventos` | `EventoCreate` | `EventoOut` (201) | M1 |
| GET | `/api/sim/kpis` | — | `KpisResponse` | M1 |
| GET | `/api/sim/snapshot` | — | `SimSnapshot` (respaldo por polling) | M1 |
| POST | `/api/asistente/mensaje` | `AsistenteRequest` | `AsistenteResponse` | M4 |
| GET/POST | `/webhook/whatsapp` | WhatsApp Cloud API | verificación / 200 | M5 |
| POST | `/webhook/telegram` | Telegram Bot API | 200 | M5 |
| GET | `/api/publico/zonas` | — | `ZonaPublica[]` | M7 |

Payload de `EventoCreate.payload` por tipo:
- `buque_atraca`: `{contenedores, terminal}`
- `norte`: `{duracion_h, factor_servicio}`
- `cierre_acceso` / `reapertura`: `{}` + `acceso_id`
- `carga_urgente`: `{camiones, tipo_carga}`
- `personalizado`: libre (reservado para el giro)

Notas de simulación:
- `velocidad` = segundos simulados por segundo real (60 → 1 s real = 1 min simulado; 600 → 10 min).
- `503` en rutas de simulación si el simulador aún no arranca.
- Parámetros del escenario (accesos, carriles, demanda, buques, norte) en `backend/data/escenario.json`.

## 4. WebSocket `WS /ws/sim`
Servidor → cliente, JSON. Al conectar se envía un snapshot inmediato; luego uno por tick (1 s real por defecto) y un mensaje `evento` cada vez que se aplica uno. La conexión sobrevive a un `reset`. Unión discriminada por `tipo`:

```json
{ "tipo": "snapshot", "data": SimSnapshot }
{ "tipo": "evento",   "data": EventoOut }
{ "tipo": "aviso",    "data": AvisoOut }
```

`SimSnapshot`: `corrida_id, tick, ts_sim, velocidad, estado, clima, mundos{A,B}, comparacion, eventos_recientes[], etiqueta`.
`MundoEstado`: `camiones[]` (tope `sim_max_camiones_visibles`; el resto en `camiones_ocultos`), `accesos[]`, `kpis`.
`CamionEstado.progreso` es 0..1 sobre la polilínea `ruta_id` del GeoJSON; el front interpola la posición.

## 5. Herramientas del asistente (M4)
`consultar_espera(acceso_id?)` → `GET /api/accesos/estado` + `GET /api/pronostico`
`sugerir_horario(desde, hasta, tipo_carga, acceso_id?)` → `POST /api/citas/sugerencias`
`crear_cita(...)` → `POST /api/citas` · `reprogramar_cita(id, ...)` → `PATCH` · `cancelar_cita(id)` → `DELETE`
`mis_citas(telefono)` → `GET /api/citas?telefono=`

## 6. Estructura del repo
```
backend/app/{api,sim,prediction,assistant,messaging,db,contracts}   # un agente por carpeta
backend/alembic/                                                    # migraciones
frontend/{operador,publico,static/{geo,vendor}}                     # sin build, sin npm
docs/                                                               # contratos, openapi, ejemplos
```
