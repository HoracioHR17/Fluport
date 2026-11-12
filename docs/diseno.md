# Fluport — Plan de diseño

Fuente: documento de identidad visual del proyecto. Tokens listos para usar en `frontend/static/css/tokens.css`.

## 1. Concepto
Claro y luminoso, como el malecón de Veracruz de día. Dos fondos suaves (**Arena** y **Bruma**) cubren ~80 % de la superficie; un solo color oscuro (**Abismo**) para texto, títulos y botones. El **semáforo** es el lenguaje del sistema y solo se usa para estados de los accesos.

## 2. Paleta

| Token | Nombre | Hex | Uso |
|---|---|---|---|
| `--arena` | Arena | `#F4EFE6` | Fondo principal de pantallas y tarjetas |
| `--bruma` | Bruma | `#E3EEF6` | Fondo de secciones, tablas y paneles |
| `--abismo` | Abismo | `#0A2238` | Texto, títulos y botones (único color oscuro) |
| `--fluye` | Fluye | `#3FAE7A` | Semáforo verde: acceso libre, < 30 min |
| `--lento` | Lento | `#E9B03B` | Semáforo ámbar: 30 a 90 min |
| `--saturado` | Saturado | `#D9574B` | Semáforo rojo: > 90 min y alertas |

Reglas:
- El semáforo **solo** comunica estado de accesos/franjas; no se usa para decorar.
- Siempre **texto + forma junto al color** (accesibilidad para daltonismo): `● Fluye · < 30 min`, `● Lento · 30 a 90 min`, `▲ Saturado · > 90 min`.
- Texto sobre semáforo: usar Abismo (`#0A2238`) sobre Fluye y Lento; sobre Saturado verificar contraste (usar Abismo o etiqueta fuera del color).

### Correspondencia con la API
| Valor en la API (`semaforo`) | Etiqueta visible | Color | Símbolo | Umbral |
|---|---|---|---|---|
| `verde` | Fluye | `--fluye` | ● | < 30 min |
| `amarillo` | Lento | `--lento` | ● | 30–90 min |
| `rojo` | Saturado | `--saturado` | ▲ | > 90 min (o acceso cerrado) |

Los umbrales del backend ya están en 30/90 (`semaforo_amarillo_min`, `semaforo_rojo_min`).

## 3. Tipografía
Una sola familia sans serif del sistema, sin descargas: `font-family: Arial, Helvetica, sans-serif;`. La jerarquía se marca solo con tamaño y grosor.

| Estilo | Uso | Tamaño |
|---|---|---|
| Bold | Logotipo y títulos | 28–40 px |
| Regular | Interfaz, textos, botones | 14–16 px |
| Bold + números tabulares (`font-variant-numeric: tabular-nums`) | Cifras, horarios, placas (`87 min · 12:30 · ABC-123`) | según contexto |

## 4. Logotipo
"FLU" en Abismo **bold**, "PORT" en Abismo **regular/delgado**, seguido de los tres puntos del semáforo (Fluye · Lento · Saturado). Lema: **Menos fila, más puerto.**

## 5. Elementos obligatorios en pantalla
- Etiqueta **SIMULACIÓN** visible (campo `etiqueta` del snapshot).
- Leyenda del semáforo con texto y símbolo.

## 6. Implementación
- Pantallas: tablero del operador (`frontend/operador/`) y vista pública (`frontend/publico/`), según el lienzo de diseño aprobado.
- Sin npm: HTML + CSS + JS servidos por FastAPI, con Leaflet como archivo local; la gráfica del pronóstico son barras HTML/CSS (el documento de identidad menciona React y Recharts; se sustituyen por equivalentes sin paso de compilación).
