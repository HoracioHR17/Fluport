# Fluport — Contratos (M0)

> Congelados. Cualquier cambio requiere aprobación del desarrollador, una nueva migración Alembic y una entrada en la bitácora.
> Fuente de verdad en código: `backend/app/nucleo/contracts/` (enums + schemas) y `backend/app/nucleo/db/models.py`.
> Especificación completa: `docs/openapi.json` (también en `/docs` con la app corriendo). Ejemplo de mensaje WS: `docs/ejemplo-snapshot.json`.

## 1. Convenciones
- Fechas ISO 8601 con zona horaria de Veracruz (`-06:00`). Campos `ts_sim` = tiempo **simulado**.
- Tiempos en minutos (`float`). Progreso de ruta `0..1`.
- Identificadores de acceso tipo `"A1"`, rutas `"R-A1-norte"`, camiones `"T-0001"`.
- Mundo `A` = sin Fluport (llegada libre) · Mundo `B` = con Fluport (llegada según cita sugerida).
- Semáforo único (`semaforo_de`): `< 30` verde (Fluye) · `30–90` amarillo (Lento) · `> 90` rojo (Saturado) (configurable). Los valores del enum no cambian; las etiquetas visibles se definen en `docs/diseno.md`.
- Errores: `422` validación, `404` no existe, `409` conflicto (acceso cerrado / ventana llena), `501` pendiente.

## 2. Base de datos (PostgreSQL)
| Tabla | Propósito | Claves |
|---|---|---|
| `acceso` | Accesos al puerto y su capacidad | `id` (str), `zona`, `carriles`, `tiempo_servicio_min`, `estado` |
| `transportista` | Usuarios del canal (solo teléfonos de prueba con consentimiento) | `telefono` único, `es_demo` |
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
| GET | `/api/pronostico?acceso_id=&horas=12&mundo=B` | — | `PronosticoOut[]` (24 franjas de 30 min) | M2 |
| GET | `/api/pronostico/modelo` | — | `{version, metricas}` del modelo en uso | M2 |
| POST | `/api/citas` | `CitaCreate` | `CitaOut` (201) | M3 |
| GET | `/api/citas?telefono=&transportista_id=&acceso_id=&estado=` | — | `CitaOut[]` | M3 |
| POST | `/api/citas/sugerencias` | `SugerenciaRequest` | `Sugerencia[]` (top 3) | M3 |
| GET | `/api/citas/resumen` | — | `ResumenCitas` (por estado, % cumplimiento, por acceso) | M3 |
| GET | `/api/citas/{id}` | — | `CitaOut` | M3 |
| PATCH | `/api/citas/{id}` | `CitaReprogramar` | `CitaOut` (nueva, con `cita_anterior_id`) | M3 |
| DELETE | `/api/citas/{id}` | — | `CitaOut` (cancelada) | M3 |
| GET | `/api/sim/estado` | — | `SimEstadoOut` | M1 |
| POST | `/api/sim/control` | `SimControl` `{accion: play\|pause\|velocidad\|reset}` | `SimEstadoOut` | M1 |
| POST | `/api/sim/eventos` | `EventoCreate` | `EventoOut` (201) | M1 |
| GET | `/api/sim/kpis` | — | `KpisResponse` | M1 |
| GET | `/api/sim/snapshot` | — | `SimSnapshot` (respaldo por polling) | M1 |
| POST | `/api/asistente/mensaje` | `AsistenteRequest` | `AsistenteResponse` | M4 |
| GET | `/api/avisos?limite=10` | — | `AvisoOut[]` (últimos avisos proactivos) | M5 |
| POST | `/webhook/telegram` | Update de Telegram + `X-Telegram-Bot-Api-Secret-Token` (solo en modo `webhook`) | `{ok: true}` · 403 secreto inválido · 404 si el modo no es `webhook` | M5 |
| GET | `/api/telegram/enlace` | — | `{usuario, enlace}` (t.me del bot) | M5 |
| GET | `/api/publico/zonas` | — | `ZonaPublica[]` (por caseta: semáforo actual, horas pico de 12 h, mejor hora) | M7 |

Payload de `EventoCreate.payload` por tipo:
- `buque_atraca`: `{contenedores, terminal}`
- `norte`: `{duracion_h, factor_servicio}`
- `cierre_acceso` / `reapertura`: `{}` + `acceso_id`
- `carga_urgente`: `{camiones, tipo_carga}`
- `personalizado`: libre (reservado para el giro)

Notas de citas:
- Las horas de las citas están en **tiempo simulado** (`ts_sim`). Una cita no puede empezar más de 30 min antes del reloj actual (422).
- `telefono` se normaliza a `+<dígitos>` (`+521…` de celular se guarda como `+52…`); si no existe, se crea el transportista.
- Errores: 404 acceso/cita/transportista inexistente · 409 acceso cerrado, cita no activa o camión ya en camino · 422 ventana inválida o teléfono inválido.
- Ciclo de estados: `agendada → en_ruta → cumplida` (lo actualiza el simulador) · `reprogramada` / `cancelada` (por la API) · `no_show` si la ventana terminó hace más de 60 min sin salir.
- Sugerencias: franjas de 30 min dentro de `[desde, hasta]` en accesos abiertos, ordenadas por espera prevista (pronóstico a 12 h; más allá, carga agendada vs. capacidad); `ahorro_vs_pico_min` = espera de la peor franja de la ventana − espera de la sugerida.

Notas de mensajería (M5):
- Canal de mensajería: **Telegram** (único). El bot pide compartir el número (botón de contacto) y guarda `transportista.telegram_chat_id`; desde ahí el transportista es el mismo en el panel de la agencia y en Telegram. Solo acepta el contacto propio del usuario y solo chats privados.
- Modo `polling` (por defecto): Fluport consulta a Telegram, no requiere URL pública. Modo `webhook`: para hosting.
- Los avisos se envían por Telegram si el transportista tiene `telegram_chat_id`; si no, el aviso queda registrado como `fallido` para que la agencia lo vea.
- Avisos proactivos, uno por cita y tipo: `turno_30min` (faltan ≤ 30 min) y `saturacion` (caseta cerrada o espera prevista ≥ 45 min en las próximas 3 h, con la mejor alternativa si ahorra ≥ 15 min). Se guardan en `aviso`, se publican en el WebSocket como `{"tipo": "aviso"}` y se agregan al historial del asistente para que un "SÍ" tenga contexto.

Notas de la vista pública:
- Usa el Mundo B (operación con Fluport). Nunca incluye citas, transportistas, teléfonos ni la comparación A/B.
- `horas_pico`: franjas consecutivas con semáforo Lento o Saturado unidas en intervalos; `semaforo` es el peor del intervalo.

Notas de simulación:
- `velocidad` = segundos simulados por segundo real (60 → 1 s real = 1 min simulado; 600 → 10 min).
- `503` en rutas de simulación si el simulador aún no arranca.
- Parámetros del escenario (accesos, carriles, demanda, buques, norte, factores de impacto) en `backend/data/escenario.json`.
- Pronóstico: `modelo_version` = `hgb-…` (modelo entrenado) o `balance-flujo-v1` (respaldo mientras no hay modelo).

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

## 5. Asistente (M4)
`POST /api/asistente/mensaje` `{canal, remitente, texto}` → `{respuesta, acciones[]}`. El remitente es el teléfono; `canal` ∈ `telegram | web`; el asistente solo ve y modifica las citas de ese teléfono. Sin `FLUPORT_LLM_API_KEY` responde con el estado de las casetas.

Herramientas:
`consultar_espera(acceso_id?)` → `GET /api/accesos/estado` + `GET /api/pronostico`
`sugerir_horario(desde, hasta, tipo_carga, acceso_id?)` → `POST /api/citas/sugerencias`
`crear_cita(...)` → `POST /api/citas` · `reprogramar_cita(id, ...)` → `PATCH` · `cancelar_cita(id)` → `DELETE`
`mis_citas(telefono)` → `GET /api/citas?telefono=`

## 6. Estructura del repo
```
backend/app/main.py                                                 # raíz de composición
backend/app/nucleo/{config,colas,puertos,dependencias,contracts,db} # núcleo compartido
backend/app/modulos/{simulacion,pronostico,citas,agencias,mensajeria,publico}  # ver docs/arquitectura.md
backend/alembic/                                                    # migraciones
frontend/{agencia,demo,publico,static/{js,css,vendor}}              # sin build, sin npm
docs/                                                               # contratos, openapi, ejemplos
```

## Agencias (`#017`)
- `GET /api/agencias` → `AgenciaOut[]` · `GET /api/agencias/{id}/transportistas` → `TransportistaOut[]` (teléfono enmascarado).
- Filtro opcional `agencia_id` en `GET /api/citas`, `GET /api/citas/resumen` y `GET /api/avisos`.
- `CitaCreate.agencia_id`: agencia del transportista si se crea uno nuevo.
- Snapshot: `CamionEstado.agencia_id` y `MundoEstado.flota[agencia_id]` (`FlotaAgencia`).
- `ZonaPublica.contingencia` ∈ `normal | lenta | saturada | cerrada` y `ZonaPublica.norte`.
- Bot: `t.me/<bot>?start=<agencia_id>` liga al transportista con la agencia.
- Páginas: `/` → `/publico/` · `/agencia/` · `/demo/` · `/operador/` → `/agencia/`.

## Alta y confirmación (`#018`)
- `POST /api/agencias/{id}/transportistas` (`TransportistaCreate`: alias, telefono, placas) → `TransportistaOut` (incluye `placas`); 409 si el número es de otra agencia.
- `CitaOut.confirmada_en`: el transportista respondió SÍ en el bot a la cita asignada.
- Citas con origen `web` se notifican al transportista (`aviso.tipo = cita_asignada`); un NO genera `cita_rechazada`.
- `FLUPORT_TELEGRAM_SOLO_REGISTRADOS` (por defecto `true`): el bot solo vincula números dados de alta.

## Panel de agencia por pantallas (`#019`)
- `/agencia/` (resumen) · `/agencia/flota/` · `/agencia/citas/` · `/agencia/transportistas/` · `/agencia/avisos/`; la agencia elegida se comparte entre pantallas (`localStorage` o `?agencia=AG01`).

## Solicitudes de alta desde el bot (`#023`)
- Número sin alta que comparte su contacto → el bot pregunta su agencia (botones con las 6 agencias o texto libre: código, nombre completo o parcial, sin acentos). Con enlace `?start=AGxx` la solicitud va directo a esa agencia.
- Tabla `solicitud_alta` (migración `0005`): `estado` ∈ `sin_agencia | pendiente | aprobada | rechazada`.
- `GET /api/agencias/{id}/solicitudes?estado=pendiente` → `SolicitudAltaOut[]` (id, nombre, telefono_fin, estado, creada_en).
- `POST /api/agencias/{id}/solicitudes/{sid}/aprobar` (`AprobarSolicitud`: placas opcional) → `TransportistaOut`; crea el transportista en la agencia y lo liga al chat. 404 si es de otra agencia, 409 si ya se resolvió o el número es de otra agencia.
- `POST /api/agencias/{id}/solicitudes/{sid}/rechazar` → `SolicitudAltaOut`. En ambos casos el bot avisa al transportista.
