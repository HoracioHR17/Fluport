/* Fluport · vista pública: estado por caseta (/api/publico/zonas), mapa de accesos, pronóstico de 12 h
 * (/api/pronostico) y acceso al bot. Componentes visuales en graficas.js.
 * Tiempo real: el estado de cada caseta se actualiza con cada snapshot del WebSocket /ws/sim (o sondeo de 1 s si
 * el WebSocket falla); el pronóstico y la mejor hora se recargan por HTTP cada minuto. */
(function () {
  "use strict";
  var F = window.Fluport, el = F.el, $ = function (id) { return document.getElementById(id); };
  var GRAVEDAD = { cerrado: 0, rojo: 1, amarillo: 2, verde: 3 };
  var ESCALA = 150; // min: tope de las barras y del velocímetro
  var estado = { zonas: [], pron: {}, sel: null, accesos: {}, rutas: {}, mapa: null, conexion: "", dibujadoEn: 0, pendiente: null,
    yo: null, vigilancia: null, marcaYo: null };
  // mismos supuestos que el bot (backend/app/modulos/mensajeria/dominio/ubicacion.py)
  var FACTOR_RUTA = 1.3, VELOCIDAD_KMH = 35, ICONO = { verde: "🟢", amarillo: "🟡", rojo: "🔴", cerrado: "⛔" };
  var CONTINGENCIA = { verde: "normal", amarillo: "lenta", rojo: "saturada" };
  var INTERVALO_DIBUJO_MS = 1000; // como máximo un redibujo por segundo aunque lleguen más snapshots

  function corto(nombre) { return nombre.replace("Caseta ", ""); }
  function est(z) { return F.estadoDe(z.semaforo, z.abierto); }
  function tono(min) { return min < 30 ? "verde" : min <= 90 ? "amarillo" : "rojo"; }

  function tendencia(z) {
    var p = estado.pron[z.acceso_id];
    if (!z.abierto || !p || p.franjas.length < 3) return "";
    var luego = p.franjas[2].espera_min, ahora = z.espera_min;
    if (Math.abs(luego - ahora) < 5) return "estable";
    return luego > ahora ? "subiendo" : "bajando";
  }

  // ───────────── Alerta de contingencia ─────────────
  function renderAlerta(zonas) {
    var cerradas = zonas.filter(function (z) { return !z.abierto; });
    var saturadas = zonas.filter(function (z) { return z.abierto && z.contingencia === "saturada"; });
    var libres = zonas.filter(function (z) { return z.abierto && z.contingencia !== "saturada"; }).map(function (z) { return corto(z.nombre); });
    var titulo = "", texto = "";
    if (cerradas.length) {
      titulo = "Contingencia: " + cerradas.map(function (z) { return corto(z.nombre); }).join(", ") + (cerradas.length > 1 ? " cerradas." : " cerrada.");
      texto = (libres.length ? "Usa " + libres.join(" o ") + ". " : "") + "Los camiones con cita se desvían y reciben aviso en Telegram.";
    } else if (saturadas.length) {
      titulo = "Entrada saturada: " + saturadas.map(function (z) { return corto(z.nombre); }).join(", ") + ".";
      texto = libres.length ? "Si puedes, entra por " + libres.join(" o ") + "." : "Revisa abajo la mejor hora para pasar.";
    }
    if (zonas.length && zonas[0].norte) {
      titulo = titulo || "Norte activo.";
      texto = (texto ? texto + " " : "") + "Hay norte: la revisión es más lenta en todas las entradas.";
    }
    $("alerta").classList.toggle("oculto", !titulo);
    $("alerta-titulo").textContent = titulo;
    $("alerta-texto").textContent = texto;
  }

  // ───────────── Resumen y tarjetas ─────────────
  function renderResumen(zonas) {
    var abiertas = zonas.filter(function (z) { return z.abierto; });
    var prom = abiertas.length ? abiertas.reduce(function (s, z) { return s + z.espera_min; }, 0) / abiertas.length : 0;
    $("promedio").textContent = abiertas.length ? F.num(prom) + " min" : "—";
    F.reemplazar($("velocimetro"), [F.velocimetro(prom, ESCALA, "Espera promedio de " + F.num(prom) + " minutos")]);
  }

  function renderZonas(zonas) {
    F.reemplazar($("zonas"), zonas.map(function (z) {
      var e = est(z), p = estado.pron[z.acceso_id], t = tendencia(z);
      var proximas = p ? p.franjas.slice(0, 7).map(function (f) { return f.espera_min; }) : [];
      return el("article", { class: "entrada entrada--" + e }, [
        el("div", { class: "entrada__cab" }, [F.simbolo(e, 22), el("div", {}, [el("h2", {}, corto(z.nombre)), el("span", { class: "tenue", style: { fontSize: "13px" } }, z.zona)])]),
        el("div", { class: "entrada__espera" }, z.abierto
          ? [el("span", { class: "cifra" }, F.num(z.espera_min)), el("span", {}, "min de espera")]
          : [el("span", { class: "cifra" }, "—"), el("span", {}, "sin paso por ahora")]),
        F.pastilla(e, t),
        proximas.length > 1 ? el("div", { class: "entrada__tendencia" }, [
          F.sparkline(proximas, { max: ESCALA, umbral: 30, etiqueta: "Espera prevista en las próximas 3 horas en " + corto(z.nombre) }),
          el("span", { class: "tenue" }, "Próximas 3 h")
        ]) : null,
        el("dl", { class: "entrada__datos" }, [
          el("div", {}, [el("dt", {}, "Camiones en fila"), el("dd", { class: "cifra" }, F.num(z.en_fila))]),
          el("div", {}, [el("dt", {}, "Mejor hora"), el("dd", { class: "cifra" }, F.hora(z.mejor_hora))])
        ])
      ]);
    }));
  }

  // ───────────── Ranking de espera por entrada ─────────────
  function renderRanking(zonas) {
    F.reemplazar($("ranking"), zonas.slice().sort(function (a, b) { return (b.abierto - a.abierto) || a.espera_min - b.espera_min; }).map(function (z) {
      var e = est(z), pct = z.abierto ? Math.min(100, z.espera_min / ESCALA * 100) : 100;
      return el("div", { class: "ranking__fila" }, [
        el("div", { class: "ranking__txt" }, [el("span", {}, corto(z.nombre)), el("b", { class: "cifra" }, z.abierto ? F.num(z.espera_min) + " min" : "Cerrada")]),
        el("div", { class: "ranking__pista", role: "img", "aria-label": corto(z.nombre) + ": " + (z.abierto ? F.num(z.espera_min) + " min" : "cerrada") },
          el("div", { class: "ranking__barra" + (e === "rojo" ? " rayas" : ""), style: { width: pct.toFixed(0) + "%", background: F.COLOR[e] } }))
      ]);
    }));
  }

  // ───────────── Mapa ─────────────
  function crearMapa() {
    var div = $("mapa-pub");
    var puntos = Object.keys(estado.accesos).map(function (id) { return [estado.accesos[id].lat, estado.accesos[id].lon]; });
    Object.keys(estado.rutas).forEach(function (id) { puntos = puntos.concat(estado.rutas[id].coords); });
    var mapa = F.mapaPuerto(div, puntos);
    if (!mapa) return;
    var m = { mapa: mapa, rutas: {}, tramos: {}, casetas: {} };
    Object.keys(estado.rutas).forEach(function (id) {
      var r = estado.rutas[id];
      m.rutas[id] = { acceso: r.acceso, linea: L.polyline(r.coords, F.estiloRuta("verde")).addTo(mapa) };
    });
    Object.keys(estado.accesos).forEach(function (id) {
      var a = estado.accesos[id];
      m.tramos[id] = L.polyline([[a.lat, a.lon], [F.PUERTO.lat, F.PUERTO.lon]], { color: "#0A2238", weight: 2, opacity: 0.45, dashArray: "4 6", interactive: false }).addTo(mapa);
      m.casetas[id] = L.marker([a.lat, a.lon], { keyboard: false, icon: F.iconoCaseta("verde", corto(a.nombre)) }).addTo(mapa);
    });
    estado.mapa = m;
  }

  function actualizarMapa(zonas) {
    var m = estado.mapa;
    if (!m) return;
    zonas.forEach(function (z) {
      var e = est(z);
      if (m.casetas[z.acceso_id]) m.casetas[z.acceso_id].setIcon(F.iconoCaseta(e, corto(z.nombre) + " · " + (z.abierto ? F.num(z.espera_min) + " min" : "cerrada")));
      Object.keys(m.rutas).forEach(function (id) { if (m.rutas[id].acceso === z.acceso_id) m.rutas[id].linea.setStyle(F.estiloRuta(e)); });
    });
  }

  // ───────────── Pronóstico ─────────────
  function renderPildoras(zonas) {
    if (!estado.sel || !zonas.some(function (z) { return z.acceso_id === estado.sel; })) {
      var peor = zonas.filter(function (z) { return z.abierto; }).sort(function (a, b) { return b.espera_min - a.espera_min; })[0] || zonas[0];
      estado.sel = peor ? peor.acceso_id : null;
    }
    F.reemplazar($("pron-casetas"), zonas.slice().sort(function (a, b) { return a.acceso_id < b.acceso_id ? -1 : 1; }).map(function (z) {
      return el("button", { type: "button", "aria-pressed": String(z.acceso_id === estado.sel),
        onclick: function () { estado.sel = z.acceso_id; renderPildoras(estado.zonas); renderPronostico(); } }, corto(z.nombre));
    }));
  }

  function renderPronostico() {
    var p = estado.pron[estado.sel], z = estado.zonas.filter(function (x) { return x.acceso_id === estado.sel; })[0];
    if (!p || !z) { F.reemplazar($("pron-grafica"), [el("p", { class: "vacio" }, "Pronóstico no disponible por ahora.")]); return; }
    var franjas = p.franjas.slice(0, 24);
    $("pron-sub").textContent = "Espera estimada cada 30 minutos en " + corto(z.nombre);
    var mejor = 0, mejorMedia = Infinity;
    for (var i = 0; i + 3 < franjas.length; i++) {
      var media = (franjas[i].espera_min + franjas[i + 1].espera_min + franjas[i + 2].espera_min + franjas[i + 3].espera_min) / 4;
      if (media < mejorMedia) { mejorMedia = media; mejor = i; }
    }
    var hayVentana = franjas.length >= 4;
    $("pron-mejor").classList.toggle("oculto", !hayVentana);
    if (hayVentana) F.reemplazar($("pron-mejor"), [F.simbolo(tono(mejorMedia), 20),
      el("span", {}, [el("b", {}, "Mejor ventana: " + F.hora(franjas[mejor].inicio) + "–" + F.horaMas(franjas[mejor + 3].inicio, 30)), " · espera media de " + F.num(mejorMedia) + " min"])]);
    var barras = franjas.map(function (f, i) {
      var t = tono(f.espera_min), enVentana = hayVentana && i >= mejor && i < mejor + 4;
      return el("div", { class: "grafica-barras__col" + (enVentana ? " grafica-barras__col--ventana" : "") }, [
        i % 2 === 0 || f.espera_min > 90 ? el("span", { class: "grafica-barras__valor" }, F.num(f.espera_min)) : null,
        el("div", { class: "grafica-barras__barra" + (t === "rojo" ? " rayas" : ""), style: { height: Math.min(100, f.espera_min / ESCALA * 100).toFixed(1) + "%", background: F.COLOR[t] } })
      ]);
    });
    var etiquetas = franjas.map(function (f, i) { return el("span", {}, i % 2 === 0 ? F.hora(f.inicio) : ""); });
    var texto = franjas.map(function (f) { return F.hora(f.inicio) + " " + F.num(f.espera_min) + " min"; }).join(", ");
    F.reemplazar($("pron-grafica"), [
      el("div", { class: "grafica-barras__eje", "aria-hidden": "true" }, el("div", { class: "grafica-barras__eje-in" }, [150, 90, 30, 0].map(function (v) {
        return el("span", { style: { bottom: (v / ESCALA * 100) + "%" } }, String(v));
      }))),
      el("div", { class: "grafica-barras__caja" }, el("div", { class: "grafica-barras__in", role: "img", "aria-label": "Pronóstico de " + corto(z.nombre) + ": " + texto }, [
        el("div", { class: "grafica-barras__area" }, [el("div", { class: "grafica-barras__umbral grafica-barras__umbral--90", "aria-hidden": "true" }), el("div", { class: "grafica-barras__umbral grafica-barras__umbral--30", "aria-hidden": "true" })].concat(barras)),
        el("div", { class: "grafica-barras__horas", "aria-hidden": "true" }, etiquetas)
      ]))
    ]);
  }

  // ───────────── Carga ─────────────
  async function cargar() {
    try {
      var res = await Promise.all([F.api("/api/publico/zonas"), F.api("/api/pronostico").catch(function () { return []; })]);
      var zonas = res[0];
      estado.pron = {};
      res[1].forEach(function (p) { estado.pron[p.acceso_id] = p; });
      estado.zonas = zonas;
      dibujar();
      renderPildoras(estado.zonas); renderPronostico();
    } catch (e) {
      F.reemplazar($("zonas"), [el("p", { class: "tarjeta", role: "alert" }, "No se pudo cargar la información. Reintentando…")]);
    }
  }

  // ───────────── Entradas cerca de mí (la ubicación no sale del navegador) ─────────────
  function distanciaKm(lat1, lon1, lat2, lon2) {
    var r = Math.PI / 180, dp = (lat2 - lat1) * r, dl = (lon2 - lon1) * r;
    var a = Math.sin(dp / 2) * Math.sin(dp / 2) + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dl / 2) * Math.sin(dl / 2);
    return 2 * 6371 * Math.asin(Math.sqrt(a));
  }

  function renderCerca() {
    var caja = $("cerca");
    if (!caja || !estado.yo) return;
    var lista = estado.zonas.filter(function (z) { return estado.accesos[z.acceso_id]; }).map(function (z) {
      var a = estado.accesos[z.acceso_id], d = distanciaKm(estado.yo.lat, estado.yo.lon, a.lat, a.lon);
      var manejo = d * FACTOR_RUTA / VELOCIDAD_KMH * 60;
      return { z: z, d: d, total: z.abierto ? manejo + z.espera_min : Infinity };
    }).sort(function (a, b) { return a.d - b.d; });
    if (!lista.length) return;
    var mejor = lista.filter(function (x) { return x.z.abierto; }).sort(function (a, b) { return a.total - b.total; })[0];
    caja.classList.remove("oculto");
    F.reemplazar(caja, [
      el("h2", {}, "Entradas cerca de ti"),
      el("ol", { class: "cerca__lista" }, lista.slice(0, 3).map(function (x) {
        var e = est(x.z);
        return el("li", {}, [el("span", { "aria-hidden": "true" }, ICONO[e] || ""), el("b", {}, corto(x.z.nombre)),
          el("span", { class: "tenue" }, x.d.toFixed(1) + " km · " + (x.z.abierto ? F.num(x.z.espera_min) + " min de espera" : "cerrada"))]);
      })),
      mejor ? el("p", { class: "ventana" }, [F.simbolo(est(mejor.z), 20),
        el("span", {}, [el("b", {}, "Te conviene " + corto(mejor.z.nombre)), " · ~" + F.num(mejor.total) + " min entre manejo y fila"])])
        : el("p", { class: "ventana" }, "Todas las entradas están cerradas por ahora."),
      el("p", { class: "tenue cerca__nota" }, "Distancia en línea recta. Tu ubicación se usa solo en este navegador; no se envía a Fluport.")
    ]);
    if (estado.mapa && window.L) {
      if (!estado.marcaYo) estado.marcaYo = L.circleMarker([estado.yo.lat, estado.yo.lon], { radius: 8, color: "#FFFFFF", weight: 3, fillColor: "#2F6FDE", fillOpacity: 1 }).addTo(estado.mapa.mapa).bindTooltip("Estás aquí");
      else estado.marcaYo.setLatLng([estado.yo.lat, estado.yo.lon]);
    }
  }

  function activarUbicacion() {
    var boton = $("btn-ubicacion"), aviso = $("ubicacion-estado");
    if (!navigator.geolocation) { aviso.textContent = "Tu navegador no permite compartir la ubicación."; return; }
    if (estado.vigilancia !== null) { // segundo toque: dejar de compartir
      navigator.geolocation.clearWatch(estado.vigilancia);
      estado.vigilancia = null; estado.yo = null;
      $("cerca").classList.add("oculto");
      if (estado.marcaYo) { estado.marcaYo.remove(); estado.marcaYo = null; }
      boton.textContent = "📍 Ver entradas cerca de mí"; aviso.textContent = "";
      return;
    }
    aviso.textContent = "Buscando tu ubicación…";
    estado.vigilancia = navigator.geolocation.watchPosition(function (p) {
      estado.yo = { lat: p.coords.latitude, lon: p.coords.longitude };
      boton.textContent = "Dejar de usar mi ubicación"; aviso.textContent = "";
      renderCerca();
    }, function (err) {
      aviso.textContent = err.code === 1 ? "No diste permiso para usar tu ubicación." : "No pudimos obtener tu ubicación. Intenta de nuevo.";
      if (estado.vigilancia !== null) navigator.geolocation.clearWatch(estado.vigilancia);
      estado.vigilancia = null;
    }, { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 });
  }

  // ───────────── Tiempo real ─────────────
  function dibujar() {
    var zonas = estado.zonas;
    estado.dibujadoEn = Date.now();
    zonas.sort(function (a, b) { return GRAVEDAD[est(a)] - GRAVEDAD[est(b)] || b.espera_min - a.espera_min; });
    if (zonas[0]) {
      var vivo = estado.conexion === "en-vivo" ? "En vivo" : estado.conexion === "sondeo" ? "Actualizando cada segundo" : "Actualizado";
      $("actualizado").textContent = vivo + " · " + F.hora(zonas[0].actualizado_en) + " (hora simulada)";
    }
    renderAlerta(zonas); renderResumen(zonas); renderZonas(zonas); renderRanking(zonas); actualizarMapa(zonas);
    renderCerca();
  }

  /** Copia a cada caseta el estado instantáneo del Mundo B (con Fluport) que trae el snapshot. */
  function aplicarSnapshot(s) {
    if (!estado.zonas.length || !s || !s.mundos || !s.mundos.B) return;
    var porId = {};
    s.mundos.B.accesos.forEach(function (a) { porId[a.acceso_id] = a; });
    estado.zonas.forEach(function (z) {
      var a = porId[z.acceso_id];
      if (!a) return;
      z.abierto = a.estado === "abierto";
      z.espera_min = a.espera_min; z.semaforo = a.semaforo; z.en_fila = a.en_fila;
      z.contingencia = z.abierto ? CONTINGENCIA[a.semaforo] : "cerrada";
      z.norte = s.clima === "norte";
      z.actualizado_en = s.ts_sim;
    });
    var falta = INTERVALO_DIBUJO_MS - (Date.now() - estado.dibujadoEn);
    if (falta <= 0) { dibujar(); return; }
    if (!estado.pendiente) estado.pendiente = setTimeout(function () { estado.pendiente = null; dibujar(); }, falta);
  }

  async function cargarMapa() {
    try {
      var res = await Promise.all([F.api("/api/accesos"), F.api("/api/accesos/rutas")]);
      res[0].forEach(function (a) { estado.accesos[a.id] = a; });
      res[1].features.filter(function (f) { return f.properties.tipo === "ruta"; }).forEach(function (f) {
        estado.rutas[f.properties.ruta_id] = { acceso: f.properties.acceso_id, coords: f.geometry.coordinates.map(function (c) { return [c[1], c[0]]; }) };
      });
      crearMapa();
      actualizarMapa(estado.zonas);
    } catch (e) { $("mapa-pub").appendChild(el("p", { style: { padding: "16px" } }, "No se pudo cargar el mapa.")); }
  }

  async function cargarBot() {
    try {
      var bot = await F.api("/api/telegram/enlace");
      $("enlace-bot").href = bot.enlace;
      $("usuario-bot").textContent = bot.usuario;
      if (window.qrcode) {
        var qr = window.qrcode(0, "M"); qr.addData(bot.enlace); qr.make();
        $("qr-bot").innerHTML = qr.createSvgTag(4, 0); // SVG generado localmente a partir de la URL del propio bot
      }
    } catch (e) {
      $("transportistas").classList.add("oculto"); // sin bot configurado no se muestra la invitación
    }
  }

  [].forEach.call(document.querySelectorAll("[data-simbolo]"), function (n) { n.appendChild(F.simbolo(n.dataset.simbolo, 20)); });
  if ($("btn-ubicacion")) $("btn-ubicacion").addEventListener("click", activarUbicacion);
  cargar().then(cargarMapa).then(function () {
    F.conectarSimulacion(function (m) { if (m.tipo === "snapshot") aplicarSnapshot(m.data); },
      function (e) { estado.conexion = e; });
  });
  cargarBot();
  setInterval(cargar, 60000); // pronóstico, mejor hora y nombres: cambian más lento que la fila
})();
