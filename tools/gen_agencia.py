"""Genera las pantallas del panel de agencia (frontend/agencia/**/index.html) con el mismo menú y encabezado."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "frontend" / "agencia"
PANT = [("resumen", "/agencia/", "Resumen"), ("flota", "/agencia/flota/", "Flota en vivo"),
        ("citas", "/agencia/citas/", "Citas"), ("transportistas", "/agencia/transportistas/", "Transportistas"),
        ("avisos", "/agencia/avisos/", "Avisos")]

def shell(clave, h1, acciones, cuerpo, mapa=False):
    nav = "\n".join(
        f'      <a href="{url}"{" aria-current=\"page\"" if c == clave else ""}><span>{t}</span>'
        f'<span class="contador oculto" data-contador="{c}"></span></a>' for c, url, t in PANT)
    leaflet_css = '<link rel="stylesheet" href="/static/vendor/leaflet/leaflet.css">\n' if mapa else ""
    leaflet_js = '<script src="/static/vendor/leaflet/leaflet.js"></script>\n' if mapa else ""
    titulo = dict((c, t) for c, _, t in PANT)[clave]
    return f'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fluport · {titulo}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
{leaflet_css}<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/ui.css">
</head>
<body data-vista="agencia" data-pantalla="{clave}">
<div class="ag">
  <aside class="ag-menu" aria-label="Menú de la agencia">
    <div class="ag-menu__top">
      <a class="marca" href="/agencia/" aria-label="Fluport, resumen de la agencia"><span><b>FLU</b>PORT</span><span class="marca__puntos" aria-hidden="true"><i></i><i></i><i></i></span></a>
      <button type="button" class="ag-menu__boton" id="btn-menu" aria-expanded="false" aria-controls="menu-cuerpo" aria-label="Abrir menú">
        <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"></path></svg>
      </button>
    </div>
    <div class="ag-menu__cuerpo" id="menu-cuerpo">
      <div class="ag-menu__agencia">
        <label for="agencia">Agencia</label>
        <select id="agencia"></select>
      </div>
      <nav class="ag-nav" aria-label="Secciones">
{nav}
      </nav>
      <a class="ag-menu__pie" href="/publico/">Vista pública ↗</a>
    </div>
  </aside>

  <div class="ag-cuerpo">
    <header class="ag-cab">
      <div class="ag-cab__titulo">
        <h1>{h1}</h1>
        <span class="tenue" style="font-size:14px" id="reloj">Conectando…</span>
      </div>
      <span class="sim" id="etiqueta">SIMULACIÓN</span>
      {acciones}
    </header>
    <main class="ag-main">
{cuerpo}
    </main>
  </div>
</div>
{leaflet_js}<script src="/static/vendor/qrcode/qrcode.js"></script>
<script src="/static/js/comun.js"></script>
<script src="/static/js/agencia.js"></script>
</body>
</html>
'''

RESUMEN = '''      <section aria-label="Indicadores de la flota" class="kpis" id="kpis"></section>
      <section aria-labelledby="t-cas" class="bloque">
        <h2 id="t-cas" class="titulo-bloque">Casetas ahora</h2>
        <div class="casetas" id="casetas" aria-live="polite"></div>
      </section>
      <section aria-labelledby="t-mod" class="bloque">
        <h2 id="t-mod" class="titulo-bloque">Ir a</h2>
        <div class="modulos" id="modulos"></div>
      </section>
      <section class="tarjeta" aria-labelledby="t-at">
        <div class="cabeza"><h2 id="t-at">Requiere tu atención</h2><span class="tenue" style="font-size:14px" id="total-atencion"></span></div>
        <ul class="atencion atencion--rejilla" id="atencion" aria-live="polite"></ul>
      </section>'''

FLOTA = '''      <div class="cabeza">
        <div class="segmentos" role="group" aria-label="Filtro de la flota" id="filtro-flota"></div>
        <label class="campo campo--linea">Buscar camión<input type="search" id="buscar-camion" placeholder="Placas, chofer o número"></label>
      </div>
      <div class="fila-2">
        <section class="tarjeta ancho" aria-labelledby="t-mapa">
          <div class="cabeza"><h2 id="t-mapa">Mapa</h2><span class="tenue" style="font-size:14px" id="resumen-mapa"></span></div>
          <div class="mapa mapa--grande" id="mapa"></div>
          <div class="leyenda-mapa"><span>● En ruta</span><span>■ En fila</span><span>● En revisión</span><span>◯ Con cita de un transportista registrado</span><span>Solo tus camiones</span></div>
        </section>
        <aside class="tarjeta angosto" aria-labelledby="t-sel">
          <h2 id="t-sel">Camión seleccionado</h2>
          <div id="ficha" aria-live="polite"></div>
        </aside>
      </div>
      <section class="tarjeta" aria-labelledby="t-lista">
        <div class="cabeza"><h2 id="t-lista">Camiones activos</h2><span class="tenue" style="font-size:14px">Ordenados por estado · toca uno para ver su ficha</span></div>
        <div class="tabla-caja">
          <table class="tabla">
            <caption class="sr">Camiones activos de la agencia</caption>
            <thead><tr><th scope="col">Camión</th><th scope="col">Transportista</th><th scope="col">Estado</th><th scope="col">Caseta</th><th scope="col">Carga</th><th scope="col">Cita</th></tr></thead>
            <tbody id="tabla-camiones"></tbody>
          </table>
        </div>
      </section>'''

CITAS = '''      <div class="fila-2 fila-2--arriba">
        <div class="ancho bloque">
          <div class="cabeza">
            <div class="pildoras" role="group" aria-label="Filtro de citas" id="filtros"></div>
            <span class="tenue" style="font-size:14px" id="resumen-citas"></span>
          </div>
          <section class="tarjeta" aria-label="Citas de la agencia">
            <div class="tabla-caja">
              <table class="tabla">
                <caption class="sr">Citas de la agencia</caption>
                <thead><tr><th scope="col">Hora</th><th scope="col">Transportista</th><th scope="col">Placas</th><th scope="col">Caseta</th><th scope="col">Espera prevista</th><th scope="col">Estado</th><th scope="col"><span class="sr">Acción</span></th></tr></thead>
                <tbody id="tabla-citas"></tbody>
              </table>
            </div>
          </section>
        </div>
        <aside class="tarjeta angosto" aria-labelledby="t-asig" id="asignar">
          <h2 id="t-asig">Asignar cita</h2>
          <form class="form form--columna" id="form-cita">
            <label class="campo">Transportista<select id="cita-transportista" required></select></label>
            <label class="campo">Tipo de carga
              <select id="cita-carga">
                <option value="contenedor_40">Contenedor 40'</option>
                <option value="contenedor_20">Contenedor 20'</option>
                <option value="refrigerado">Refrigerado</option>
                <option value="peligroso">Peligroso</option>
                <option value="granel">Granel</option>
                <option value="carga_general">Carga general</option>
              </select>
            </label>
            <label class="campo">Caseta<select id="cita-caseta"><option value="">La de menor espera</option></select></label>
            <div class="form form--dos">
              <label class="campo">Desde<input id="cita-desde" type="time" required></label>
              <label class="campo">Hasta<input id="cita-hasta" type="time" required></label>
            </div>
            <button type="submit" class="btn">Buscar las mejores ventanas</button>
          </form>
          <div class="sugerencias sugerencias--lista" id="sugerencias"></div>
          <p class="estado-msg" id="estado-cita" role="status"></p>
          <p class="tenue" style="margin:0;font-size:13px">El transportista recibe la cita en Telegram y la confirma respondiendo SÍ.</p>
        </aside>
      </div>'''

TRANS = '''      <div class="fila-2 fila-2--arriba">
        <section class="tarjeta ancho" aria-labelledby="t-alta">
          <h2 id="t-alta">Alta de transportista</h2>
          <form class="form" id="form-alta">
            <label class="campo">Nombre<input id="alta-nombre" autocomplete="off" required minlength="2"></label>
            <label class="campo">Teléfono<input id="alta-tel" type="tel" inputmode="tel" autocomplete="off" placeholder="+52 229 000 0000" required></label>
            <label class="campo">Placas<input id="alta-placas" autocomplete="off" placeholder="XKL-45-21"></label>
            <button type="submit" class="btn">Dar de alta</button>
          </form>
          <p class="estado-msg" id="estado-alta" role="status"></p>
          <p class="tenue" style="margin:0;font-size:13px">Solo los números dados de alta pueden conectarse al bot.</p>
        </section>
        <aside class="tarjeta angosto" aria-labelledby="t-inv">
          <h2 id="t-inv">Invitación al bot</h2>
          <div class="invitacion" id="invitacion"></div>
        </aside>
      </div>
      <section class="tarjeta" aria-labelledby="t-lista">
        <div class="cabeza">
          <h2 id="t-lista">Mis transportistas</h2>
          <div class="pildoras" role="group" aria-label="Filtro de transportistas" id="filtro-trans"></div>
        </div>
        <div class="tabla-caja">
          <table class="tabla">
            <caption class="sr">Transportistas de la agencia</caption>
            <thead><tr><th scope="col">Nombre</th><th scope="col">Placas</th><th scope="col">Teléfono</th><th scope="col">Telegram</th><th scope="col">Citas activas</th><th scope="col">Próxima cita</th><th scope="col"><span class="sr">Acción</span></th></tr></thead>
            <tbody id="tabla-trans"></tbody>
          </table>
        </div>
      </section>'''

AVISOS = '''      <div class="pildoras" role="group" aria-label="Filtro de avisos" id="filtro-avisos"></div>
      <section class="tarjeta" aria-label="Avisos">
        <ol class="avisos" id="lista-avisos" aria-live="polite"></ol>
      </section>'''

BTN_ALTA = '<a class="btn btn--sec" href="/agencia/transportistas/">Alta de transportista</a>'
BTN_ASIG = '<a class="btn" href="/agencia/citas/#asignar">Asignar cita</a>'
PAGINAS = {
    "resumen": ("Resumen de hoy", BTN_ALTA + "\n      " + BTN_ASIG, RESUMEN, False),
    "flota": ("Flota en vivo", BTN_ASIG, FLOTA, True),
    "citas": ("Citas", BTN_ALTA, CITAS, False),
    "transportistas": ("Transportistas", BTN_ASIG, TRANS, False),
    "avisos": ("Avisos", "", AVISOS, False),
}

for clave, (h1, acc, cuerpo, mapa) in PAGINAS.items():
    destino = RAIZ / ("" if clave == "resumen" else clave) / "index.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(shell(clave, h1, acc, cuerpo, mapa), encoding="utf-8")
    print(destino.relative_to(RAIZ.parents[1]))
