/* Fluport · componentes visuales compartidos: símbolos del semáforo, gráficas en SVG y mapa del puerto.
 * Sin dependencias (Leaflet solo para el mapa). Requiere comun.js.
 * Simbología: el estado nunca depende solo del color; cada uno tiene su forma.
 *   fluye ● círculo verde · lento ◆ rombo ámbar · saturado ▲ triángulo rojo · cerrada ■ cuadro oscuro con X */
(function () {
  "use strict";
  var F = window.Fluport;
  var NS = "http://www.w3.org/2000/svg";
  var COLOR = { verde: "#3FAE7A", amarillo: "#E9B03B", rojo: "#D9574B", cerrado: "#0A2238" };
  var ETIQUETA = { verde: "Fluye", amarillo: "Lento", rojo: "Saturado", cerrado: "Cerrada" };
  var FONDO = { verde: "#EAF6F0", amarillo: "#FCF3DF", rojo: "#FBEAE8", cerrado: "#0A2238" };

  /** Elemento SVG: svg("path", {d: "..."}, [hijos]). */
  function svg(tag, attrs, hijos) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k.slice(0, 2) === "on" && typeof v === "function") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, String(v));
    });
    [].concat(hijos === undefined ? [] : hijos).forEach(function (h) {
      if (h === null || h === undefined || h === false) return;
      n.appendChild(typeof h === "object" ? h : document.createTextNode(String(h)));
    });
    return n;
  }

  /** Estado visual de un acceso: "verde" | "amarillo" | "rojo" | "cerrado". */
  function estadoDe(semaforo, abierto) { return abierto === false ? "cerrado" : (semaforo || "verde"); }

  /** Forma del estado como cadena SVG (para iconos de Leaflet) dentro de una caja de 22×22. */
  function formaSvg(estado, borde) {
    var b = borde ? ' stroke="#FFFFFF" stroke-width="2.5"' : "";
    if (estado === "amarillo") return '<path d="M11 1.5 L20.5 11 L11 20.5 L1.5 11 Z" fill="' + COLOR.amarillo + '"' + b + "/>";
    if (estado === "rojo") return '<path d="M11 2 L21 20 H1 Z" fill="' + COLOR.rojo + '"' + b + "/>";
    if (estado === "cerrado") return '<rect x="2" y="2" width="18" height="18" rx="3" fill="' + COLOR.cerrado + '"' + b + '/><path d="M7 7 L15 15 M15 7 L7 15" stroke="#FFFFFF" stroke-width="2.4"/>';
    return '<circle cx="11" cy="11" r="9" fill="' + COLOR.verde + '"' + b + "/>";
  }

  /** Símbolo del estado como elemento SVG (decorativo: el texto que lo acompaña dice el estado). */
  function simbolo(estado, tam) {
    var n = svg("svg", { width: tam || 18, height: tam || 18, viewBox: "0 0 22 22", "aria-hidden": "true", focusable: "false" });
    n.innerHTML = formaSvg(estado, false); // cadena fija generada aquí, sin datos externos
    return n;
  }

  /** Pastilla "◆ Lento" con color de fondo del estado. */
  function pastilla(estado, extra) {
    return F.el("span", { class: "chip chip--" + (estado === "cerrado" ? "oscuro" : estado) + " chip--simbolo" },
      [simbolo(estado, 14), ETIQUETA[estado] + (extra ? " · " + extra : "")]);
  }

  /** Línea de tendencia compacta. vals: números; opciones: {max, umbral, ancho, alto, area, etiqueta}. */
  function sparkline(vals, op) {
    op = op || {};
    var w = op.ancho || 180, h = op.alto || 48, max = op.max || Math.max.apply(null, vals.concat([1]));
    var n = Math.max(vals.length - 1, 1);
    var pts = vals.map(function (v, i) { return (i / n * w).toFixed(1) + "," + (h - 2 - Math.min(v, max) / max * (h - 4)).toFixed(1); });
    var hijos = [];
    if (op.umbral) { var y = (h - 2 - op.umbral / max * (h - 4)).toFixed(1); hijos.push(svg("line", { x1: 0, y1: y, x2: w, y2: y, stroke: "#C9C0AE", "stroke-dasharray": "3 4" })); }
    if (op.area) hijos.push(svg("polygon", { points: "0," + h + " " + pts.join(" ") + " " + w + "," + h, fill: "#E3EEF6" }));
    hijos.push(svg("polyline", { points: pts.join(" "), fill: "none", stroke: "#0A2238", "stroke-width": 2.5, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    return svg("svg", { class: "sparkline", width: "100%", height: h, viewBox: "0 0 " + w + " " + h, preserveAspectRatio: "none",
      role: op.etiqueta ? "img" : null, "aria-label": op.etiqueta || null, "aria-hidden": op.etiqueta ? null : "true" }, hijos);
  }

  /** Velocímetro semicircular de 0 a `max` min con los tramos del semáforo (30 y 90 min). */
  function velocimetro(valor, max, etiqueta) {
    max = max || 150;
    function punto(t) { var a = t / max * Math.PI; return [(120 - 96 * Math.cos(a)).toFixed(1), (120 - 96 * Math.sin(a)).toFixed(1)]; }
    function arco(a, b, color) { var p = punto(a), q = punto(b); return svg("path", { d: "M" + p[0] + " " + p[1] + " A96 96 0 0 1 " + q[0] + " " + q[1], stroke: color, "stroke-width": 18, fill: "none" }); }
    var ang = Math.min(Math.max(valor, 0), max) / max * 180;
    return svg("svg", { class: "velocimetro", width: 240, height: 140, viewBox: "0 0 240 140", role: "img", "aria-label": etiqueta }, [
      arco(0, 30, COLOR.verde), arco(30, 90, COLOR.amarillo), arco(90, max, COLOR.rojo),
      svg("line", { x1: 120, y1: 120, x2: 44, y2: 120, stroke: "#0A2238", "stroke-width": 5, "stroke-linecap": "round", transform: "rotate(" + ang.toFixed(1) + " 120 120)" }),
      svg("circle", { cx: 120, cy: 120, r: 9, fill: "#0A2238" }),
      svg("text", { x: 22, y: 138, "font-size": 11, fill: "#4A5B6B" }, "0"),
      svg("text", { x: 218, y: 138, "font-size": 11, fill: "#4A5B6B", "text-anchor": "end" }, max + " min")
    ]);
  }

  /** Dona con conic-gradient. partes: [{valor, color}]. */
  function dona(partes, centro, sub, etiqueta) {
    var total = partes.reduce(function (s, p) { return s + p.valor; }, 0), acc = 0;
    var tramos = total ? partes.map(function (p) { var a = acc / total * 360; acc += p.valor; return p.color + " " + a.toFixed(1) + "deg " + (acc / total * 360).toFixed(1) + "deg"; }) : ["#E3E0D8 0deg 360deg"];
    return F.el("div", { class: "dona", role: "img", "aria-label": etiqueta, style: { background: "conic-gradient(" + tramos.join(", ") + ")" } },
      F.el("div", { class: "dona__centro" }, [F.el("span", { class: "cifra" }, centro), F.el("span", { class: "tenue" }, sub)]));
  }

  // ───────────── Mapa del puerto (Leaflet) ─────────────
  // Zona de trabajo: casetas La Antigua, San Julián y Paso del Toro y el recinto portuario. El mapa no deja salir
  // de ella (ni con arrastre ni alejando) para que siempre muestre el entorno del puerto de Veracruz.
  var PUERTO = { lat: 19.2045, lon: -96.1338, nombre: "Puerto de Veracruz" };
  var LIMITES = [[18.98, -96.47], [19.44, -96.05]];

  function mapaPuerto(div, puntos) {
    if (!window.L) { div.appendChild(F.el("p", { style: { padding: "16px" } }, "No se pudo cargar el mapa.")); return null; }
    var lim = L.latLngBounds(LIMITES);
    var mapa = L.map(div, { maxBounds: lim.pad(0.05), maxBoundsViscosity: 1, minZoom: 10, maxZoom: 16, zoomSnap: 0.5 });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 16, minZoom: 10, bounds: lim.pad(0.1),
      attribution: "&copy; colaboradores de OpenStreetMap" }).addTo(mapa);
    var encuadre = L.latLngBounds((puntos || []).concat([[PUERTO.lat, PUERTO.lon]]));
    mapa.fitBounds(encuadre.isValid() ? encuadre : lim, { padding: [24, 24] });
    mapa.setMinZoom(Math.max(10, Math.floor(mapa.getZoom() * 2) / 2 - 0.5));
    L.marker([PUERTO.lat, PUERTO.lon], { keyboard: false, interactive: false, icon: L.divIcon({ className: "", iconSize: null, iconAnchor: [14, 14],
      html: '<span class="marcador-puerto"><svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><rect width="28" height="28" rx="6" fill="#0A2238"/>' +
        '<path d="M14 6 V21 M8 16 C8 22 20 22 20 16 M10 9 H18" stroke="#FFFFFF" stroke-width="2.2" fill="none" stroke-linecap="round"/></svg><b>Puerto</b></span>' }) }).addTo(mapa);
    return mapa;
  }

  /** Icono de caseta: forma del estado + nombre y espera. */
  function iconoCaseta(estado, texto) {
    var t = String(texto).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
    return L.divIcon({ className: "", iconSize: null, iconAnchor: [15, 15],
      html: '<span class="marcador-caseta marcador-caseta--' + estado + '"><svg width="26" height="26" viewBox="0 0 22 22" aria-hidden="true">' + formaSvg(estado, true) + "</svg>" + t + "</span>" });
  }

  /** Estilo de la ruta de acceso: color del estado, más gruesa y punteada cuanto peor está. */
  function estiloRuta(estado) {
    if (estado === "cerrado") return { color: "#0A2238", weight: 5, opacity: 0.8, dashArray: "2 8" };
    if (estado === "rojo") return { color: COLOR.rojo, weight: 8, opacity: 0.9, dashArray: "14 8" };
    if (estado === "amarillo") return { color: COLOR.amarillo, weight: 7, opacity: 0.9 };
    return { color: COLOR.verde, weight: 6, opacity: 0.85 };
  }

  /** Icono de camión. tipo: "ruta" (flecha orientada) | "fila" (cuadro ámbar) | "dentro" (anillo azul). */
  function iconoCamion(tipo, op) {
    op = op || {};
    var forma = tipo === "fila" ? '<rect x="-6" y="-6" width="12" height="12" fill="#E9B03B" stroke="#0A2238" stroke-width="1.6"/>'
      : tipo === "dentro" ? '<circle r="6" fill="#FFFFFF" stroke="#3D6A8F" stroke-width="3.5"/>'
      : '<path d="M-7 -6 L8 0 L-7 6 L-3 0 Z" fill="#0A2238" stroke="#FFFFFF" stroke-width="1" transform="rotate(' + (op.angulo || 0).toFixed(0) + ')"/>';
    var halo = op.cita ? '<circle r="12" fill="#FFFFFF" stroke="#0A2238" stroke-width="1.5" stroke-dasharray="3 2"/>' : "";
    var sel = op.sel ? '<circle r="16" fill="none" stroke="#0A2238" stroke-width="3"/>' : "";
    return L.divIcon({ className: "", iconSize: [36, 36], iconAnchor: [18, 18],
      html: '<svg width="36" height="36" viewBox="-18 -18 36 36" aria-hidden="true">' + sel + halo + forma + "</svg>" });
  }

  /** Rumbo en grados (0 = este) entre dos puntos [lat, lon] para orientar la flecha en pantalla. */
  function rumbo(a, b) { return Math.atan2(-(b[0] - a[0]), (b[1] - a[1]) * Math.cos(a[0] * Math.PI / 180)) * 180 / Math.PI; }

  Object.assign(F, { svg: svg, COLOR: COLOR, ETIQUETA: ETIQUETA, FONDO: FONDO, estadoDe: estadoDe, formaSvg: formaSvg,
    simbolo: simbolo, pastilla: pastilla, sparkline: sparkline, velocimetro: velocimetro, dona: dona,
    PUERTO: PUERTO, LIMITES: LIMITES, mapaPuerto: mapaPuerto, iconoCaseta: iconoCaseta, estiloRuta: estiloRuta,
    iconoCamion: iconoCamion, rumbo: rumbo });
})();
