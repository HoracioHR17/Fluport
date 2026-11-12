/* Fluport · panel de demostración: controles de la simulación, mundos sin y con Fluport, eventos, avisos,
 * pronóstico e impacto. Datos: WS /ws/sim (snapshots) + REST (/api/pronostico, /api/avisos, /api/sim/*). */
(function () {
  "use strict";
  var F = window.Fluport, el = F.el, $ = function (id) { return document.getElementById(id); };

  var EVENTOS = { cierre_acceso: "Caseta cerrada", reapertura: "Caseta reabierta", buque_atraca: "Atracó un buque",
    norte: "Norte", carga_urgente: "Carga urgente", personalizado: "Evento especial" };

  var estado = { accesos: {}, rutas: {}, mundo: "B", pronCaseta: null, snap: null, mapas: {}, avisos: [] };

  // ───────────── Mapas (Leaflet) ─────────────
  function crearMapa(mundo) {
    var div = $("mapa-" + mundo);
    var limites = [];
    Object.keys(estado.rutas).forEach(function (id) { limites = limites.concat(estado.rutas[id].coords); });
    var mapa = F.mapaPuerto(div, limites); // limitado a la zona del puerto de Veracruz (graficas.js)
    if (!mapa) return null;
    Object.keys(estado.rutas).forEach(function (id) {
      L.polyline(estado.rutas[id].coords, { color: "#0A2238", opacity: 0.45, weight: 5 }).addTo(mapa);
    });
    var m = { mapa: mapa, camiones: {}, casetas: {} };
    Object.keys(estado.accesos).forEach(function (id) {
      var a = estado.accesos[id];
      m.casetas[id] = L.marker([a.lat, a.lon], { icon: iconoCaseta(id, "verde", 0), keyboard: false }).addTo(mapa);
    });
    return m;
  }

  function iconoCaseta(id, semaforo, espera) {
    var rojo = semaforo === "rojo";
    var punto = rojo ? "marcador-caseta__punto marcador-caseta__punto--rojo" : "marcador-caseta__punto";
    var cont = el("div", { class: "marcador-caseta" }, [
      el("span", { class: punto, style: rojo ? null : { background: F.SEMAFORO[semaforo].color } }),
      id + " · " + Math.round(espera) + " min"
    ]);
    return L.divIcon({ html: cont.outerHTML, className: "", iconSize: null, iconAnchor: [12, 12] });
  }

  function estiloCamion(c) {
    if (c.es_demo) return { radius: 8, color: "#3FAE7A", weight: 4, fillColor: "#FFFFFF", fillOpacity: 1 };
    if (c.estado === "en_fila") return { radius: 4, color: "#9A6B0B", weight: 1, fillColor: "#E9B03B", fillOpacity: 1 };
    if (c.estado === "en_revision") return { radius: 5, color: "#1E6B47", weight: 1, fillColor: "#3FAE7A", fillOpacity: 1 };
    if (c.estado === "saliendo") return { radius: 3, color: "#4A5B6B", weight: 1, fillColor: "#A9B8C6", fillOpacity: 0.9 };
    return { radius: 4, color: "#0A2238", weight: 1, fillColor: "#0A2238", fillOpacity: 0.9 };
  }

  function dibujarMapa(mundo, datos) {
    var m = estado.mapas[mundo];
    if (!m) return;
    var vistos = {}, fila = {};
    datos.camiones.forEach(function (c) {
      var ruta = estado.rutas[c.ruta_id];
      if (!ruta) return;
      var p = c.progreso;
      if (c.estado === "en_fila") { // la fila se dibuja hacia atrás sobre la ruta
        fila[c.acceso_id] = (fila[c.acceso_id] || 0) + 1;
        p = Math.max(0.55, 1 - 0.004 * fila[c.acceso_id]);
      }
      var pos = F.posicion(ruta, p);
      vistos[c.id] = true;
      var marcador = m.camiones[c.id];
      if (marcador) { marcador.setLatLng(pos); marcador.setStyle(estiloCamion(c)); }
      else m.camiones[c.id] = L.circleMarker(pos, Object.assign({ interactive: false }, estiloCamion(c))).addTo(m.mapa);
    });
    Object.keys(m.camiones).forEach(function (id) {
      if (!vistos[id]) { m.mapa.removeLayer(m.camiones[id]); delete m.camiones[id]; }
    });
    datos.accesos.forEach(function (a) {
      var mk = m.casetas[a.acceso_id];
      if (mk) mk.setIcon(iconoCaseta(a.acceso_id, a.semaforo, a.espera_min));
    });
  }

  function elegirMundo(valor) {
    estado.mundo = valor;
    [].forEach.call($("selector-mundo").querySelectorAll("button"), function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.mundo === valor));
    });
    $("mapa-A").classList.toggle("oculto", valor === "B");
    $("mapa-B").classList.toggle("oculto", valor === "A");
    ["A", "B"].forEach(function (k) {
      var visible = valor === k || valor === "AB";
      if (visible && !estado.mapas[k]) estado.mapas[k] = crearMapa(k);
      if (estado.mapas[k]) setTimeout(function () { estado.mapas[k].mapa.invalidateSize(); }, 50);
    });
    if (estado.snap) render(estado.snap);
  }

  // ───────────── Casetas, KPIs y eventos ─────────────
  function renderCasetas(accesos) {
    F.reemplazar($("lista-casetas"), accesos.map(function (a) {
      var meta = estado.accesos[a.acceso_id] || {};
      return el("article", { class: "tarjeta caseta" }, [
        el("div", { class: "caseta__cab" }, [
          el("div", {}, [
            el("div", { class: "caseta__zona" }, a.acceso_id + " · " + (meta.zona || "")),
            el("h3", { class: "caseta__nombre" }, meta.nombre || a.acceso_id)
          ]),
          F.chip(a.semaforo, a.estado === "cerrado" ? "cerrada" : null)
        ]),
        el("div", {}, [el("span", { class: "caseta__espera cifra" }, F.num(a.espera_min)), " min de espera"]),
        el("div", { class: "metricas" }, [
          el("div", {}, [el("b", {}, F.num(a.en_fila)), "en fila"]),
          el("div", {}, [el("b", {}, F.num(a.atendidos_hora)), "atendidos / h"]),
          el("div", {}, [el("b", {}, F.num(meta.carriles)), "carriles"])
        ])
      ]);
    }));
  }

  function renderImpacto(s) {
    var c = s.comparacion, a = s.mundos.A.kpis, b = s.mundos.B.kpis;
    $("espera-A").textContent = F.num(a.espera_prom_min) + " min";
    $("espera-B").textContent = F.num(b.espera_prom_min) + " min";
    var kpis = [
      ["Horas-camión ahorradas", F.num(c.horas_ahorradas) + " h"],
      ["Costo evitado", "$" + F.num(c.costo_mxn_evitado)],
      ["Diésel evitado", F.num(c.diesel_l_evitado) + " L"],
      ["CO₂ evitado", F.num(c.co2_kg_evitado / 1000, 1) + " t"],
      // con esperas mínimas al arrancar el porcentaje no es significativo
      ["Menos espera", a.espera_prom_min >= 5 ? F.num(c.reduccion_espera_pct, 1) + " %" : "—"],
      ["Pico de fila menor", a.pico_fila >= 10 ? F.num(c.reduccion_pico_fila_pct, 1) + " %" : "—"]
    ];
    F.reemplazar($("kpis"), kpis.map(function (k) {
      return el("div", {}, [el("dt", { class: "claro" }, k[0]), el("dd", { class: "cifra" }, k[1])]);
    }));
  }

  function renderEventos(eventos) {
    F.reemplazar($("lista-eventos"), eventos.length ? eventos.slice(0, 8).map(function (e) {
      var detalle = EVENTOS[e.tipo] || e.tipo;
      if (e.acceso_id) detalle += " · " + e.acceso_id;
      if (e.payload && e.payload.contenedores) detalle += " · " + F.num(e.payload.contenedores) + " contenedores";
      if (e.payload && e.payload.duracion_h) detalle += " · " + F.num(e.payload.duracion_h, 1) + " h";
      return el("li", {}, [el("span", { class: "cifra" }, F.hora(e.ts_sim)), detalle]);
    }) : [el("li", { class: "tenue" }, "Sin eventos todavía.")]);
  }

  function render(s) {
    estado.snap = s;
    $("reloj").textContent = F.hora(s.ts_sim);
    $("reloj-dia").textContent = "Reloj simulado · " + F.fecha(s.ts_sim) + (s.clima === "norte" ? " · norte" : "");
    renderCasetas(s.mundos.B.accesos);
    var pausada = s.estado !== "corriendo";
    $("btn-pausa").setAttribute("aria-label", pausada ? "Reanudar simulación" : "Pausar simulación");
    $("icono-pausa").setAttribute("d", pausada ? "M8 5l11 7-11 7z" : "M8 5v14M16 5v14");
    if (document.activeElement !== $("velocidad")) $("velocidad").value = String(Math.round(s.velocidad));
    renderImpacto(s);
    renderEventos(s.eventos_recientes || []);
    if (estado.mundo !== "B") dibujarMapa("A", s.mundos.A);
    if (estado.mundo !== "A") dibujarMapa("B", s.mundos.B);
    var vis = s.mundos[estado.mundo === "A" ? "A" : "B"];
    $("resumen-mapa").textContent = F.num(vis.camiones.length) + " camiones en el mapa" +
      (vis.camiones_ocultos ? " · " + F.num(vis.camiones_ocultos) + " más no se dibujan" : "");
  }

  // ───────────── Avisos a transportistas (Telegram) ─────────────
  var TIPOS_AVISO = { turno_30min: "Recordatorio de turno", saturacion: "Caseta saturada o cerrada" };
  var CANALES = { telegram: "Telegram", web: "Web" };

  function renderAvisos(lista) {
    F.reemplazar($("lista-avisos"), lista.length ? lista.slice(0, 6).map(function (a) {
      return el("li", { style: { flexDirection: "column", gap: "4px" } }, [
        el("span", {}, [el("b", {}, (TIPOS_AVISO[a.tipo] || a.tipo) + " · cita #" + a.cita_id),
          " · " + (CANALES[a.canal] || a.canal) + " · " + F.hora(a.creado_en)]),
        el("span", { class: "tenue", style: { whiteSpace: "pre-line" } }, a.mensaje.replace(/\*/g, ""))
      ]);
    }) : [el("li", { class: "tenue" }, "Sin avisos todavía.")]);
  }

  async function cargarAvisos() {
    try { estado.avisos = await F.api("/api/avisos?limite=6"); renderAvisos(estado.avisos); } catch (e) { /* sin BD */ }
  }

  // ───────────── Pronóstico ─────────────
  async function cargarPronostico() {
    if (!estado.pronCaseta) return;
    try {
      var p = (await F.api("/api/pronostico?acceso_id=" + encodeURIComponent(estado.pronCaseta)))[0];
      var maxEje = Math.max(120, Math.ceil(Math.max.apply(null, p.franjas.map(function (f) { return f.espera_min; })) / 30) * 30);
      F.reemplazar($("eje"), [4, 3, 2, 1, 0].map(function (i) { return el("span", {}, F.num(maxEje * i / 4)); }));
      var barras = p.franjas.map(function (f) {
        return el("div", { class: "grafica__barra", title: F.hora(f.inicio) + " · " + F.num(f.espera_min) + " min",
          style: { height: Math.max(2, Math.round(f.espera_min / maxEje * 220)) + "px", background: F.SEMAFORO[f.semaforo].color } });
      });
      barras.push(el("div", { class: "grafica__umbral", style: { bottom: Math.round(30 / maxEje * 220) + "px", borderColor: "#E9B03B" } }));
      barras.push(el("div", { class: "grafica__umbral", style: { bottom: Math.round(90 / maxEje * 220) + "px", borderColor: "#D9574B" } }));
      F.reemplazar($("barras"), barras);
      var n = p.franjas.length;
      F.reemplazar($("horas"), [0, 6, 12, 18, n - 1].filter(function (i) { return i < n; })
        .map(function (i) { return el("span", {}, F.hora(p.franjas[i].inicio)); }));
      var picos = F.horasPico(p.franjas, p.franja_min);
      var mejor = p.franjas.reduce(function (m, f) { return !m || f.espera_min < m.espera_min ? f : m; }, null);
      var etiquetas = picos.slice(0, 3).map(function (k) {
        return el("span", { class: "e-" + k.semaforo }, [el("b", {}, F.SEMAFORO[k.semaforo].simbolo + " " + F.SEMAFORO[k.semaforo].etiqueta),
          " " + k.inicio + "–" + k.finHora + " · hasta " + F.num(k.max) + " min"]);
      });
      if (mejor) etiquetas.push(el("span", { class: "e-verde" }, [el("b", {}, "● Mejor hora"), " " + F.hora(mejor.inicio) + " · " + F.num(mejor.espera_min) + " min"]));
      if (!picos.length) etiquetas.unshift(el("span", { class: "e-verde" }, "Sin horas pico previstas"));
      F.reemplazar($("etiquetas-pronostico"), etiquetas);
      var maxima = Math.max.apply(null, p.franjas.map(function (f) { return f.espera_min; }));
      $("barras").setAttribute("aria-label", "Pronóstico de " + estado.pronCaseta + ": espera máxima prevista " + F.num(maxima) + " min" +
        (mejor ? ", mejor hora " + F.hora(mejor.inicio) : ""));
    } catch (e) { /* se reintenta en el siguiente ciclo */ }
  }

  async function cargarModelo() {
    try {
      var m = await F.api("/api/pronostico/modelo");
      $("modelo-info").textContent = "Franjas de 30 min · " + (m.metricas
        ? "modelo " + m.version + " · error medio " + F.num(m.metricas.mae_modelo_min, 1) + " min en días no vistos"
        : "balance de flujo (modelo en entrenamiento)");
    } catch (e) { /* sin datos del modelo */ }
  }

  // ───────────── Controles ─────────────
  async function control(cuerpo) {
    try { await F.api("/api/sim/control", { method: "POST", json: cuerpo }); } catch (e) { /* se refleja en el próximo snapshot */ }
  }

  async function inyectarEvento(boton) {
    var tipo = boton.dataset.evento, aviso = $("estado-evento");
    var cuerpo = { tipo: tipo, payload: {} };
    if (tipo === "cierre_acceso" || tipo === "reapertura" || tipo === "carga_urgente") cuerpo.acceso_id = $("evento-caseta").value;
    if (tipo === "buque_atraca") cuerpo.payload = { contenedores: 2000 };
    if (tipo === "carga_urgente") cuerpo.payload = { camiones: 10, tipo_carga: "refrigerado" };
    boton.disabled = true;
    try {
      await F.api("/api/sim/eventos", { method: "POST", json: cuerpo });
      aviso.textContent = (EVENTOS[tipo] || tipo) + (cuerpo.acceso_id ? " · " + cuerpo.acceso_id : "") + ": aplicado.";
      setTimeout(cargarPronostico, 1200);
    } catch (e) {
      aviso.textContent = "No se aplicó: " + e.message;
    } finally {
      boton.disabled = false;
    }
  }

  // ───────────── Inicio ─────────────
  async function iniciar() {
    var accesos = await F.api("/api/accesos");
    accesos.forEach(function (a) { estado.accesos[a.id] = a; });
    var geo = await F.api("/api/accesos/rutas");
    geo.features.filter(function (f) { return f.properties.tipo === "ruta"; }).forEach(function (f) {
      estado.rutas[f.properties.ruta_id] = F.prepararRuta(f.geometry.coordinates.map(function (c) { return [c[1], c[0]]; }));
    });
    accesos.forEach(function (a) { $("evento-caseta").appendChild(el("option", { value: a.id }, a.id + " · " + a.nombre)); });
    estado.pronCaseta = accesos.length > 1 ? accesos[1].id : accesos[0].id;
    F.reemplazar($("selector-pronostico"), accesos.map(function (a) {
      return el("button", { type: "button", "aria-pressed": String(a.id === estado.pronCaseta), "data-id": a.id,
        onclick: function () {
          estado.pronCaseta = a.id;
          [].forEach.call($("selector-pronostico").children, function (b) { b.setAttribute("aria-pressed", String(b.dataset.id === a.id)); });
          cargarPronostico();
        } }, a.id);
    }));
    elegirMundo("B");
    [].forEach.call($("selector-mundo").querySelectorAll("button"), function (b) {
      b.addEventListener("click", function () { elegirMundo(b.dataset.mundo); });
    });
    [].forEach.call(document.querySelectorAll("[data-evento]"), function (b) {
      b.addEventListener("click", function () { inyectarEvento(b); });
    });
    $("btn-pausa").addEventListener("click", function () {
      control({ accion: estado.snap && estado.snap.estado === "corriendo" ? "pause" : "play" });
    });
    $("velocidad").addEventListener("change", function () { control({ accion: "velocidad", velocidad: Number(this.value) }); });
    F.conectarSimulacion(function (m) {
      if (m.tipo === "snapshot") render(m.data);
      else if (m.tipo === "evento") cargarPronostico();
      else if (m.tipo === "aviso") { estado.avisos.unshift(m.data); renderAvisos(estado.avisos); }
    });
    cargarModelo(); cargarPronostico(); cargarAvisos();
    setInterval(cargarPronostico, 15000);
    setInterval(cargarModelo, 60000);
  }

  iniciar().catch(function (e) {
    document.querySelector(".principal").prepend(el("p", { class: "tarjeta", role: "alert" }, "No se pudo conectar con el servidor: " + e.message));
  });
})();
