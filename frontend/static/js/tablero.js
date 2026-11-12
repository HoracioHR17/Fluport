/* Fluport · tableros. Datos: WS /ws/sim (snapshots) + REST (pronóstico, citas, agencias).
 * <body data-vista="agencia">: la agencia ve casetas, pronóstico, su flota, sus transportistas, citas y avisos.
 * <body data-vista="demo">: panel del presentador con controles de la simulación, mundos A/B e impacto. */
(function () {
  "use strict";
  var F = window.Fluport, el = F.el, $ = function (id) { return document.getElementById(id); };
  var VISTA = document.body.dataset.vista || "demo", AGENCIA = VISTA === "agencia";

  var CARGAS = { contenedor_20: "Contenedor 20'", contenedor_40: "Contenedor 40'", refrigerado: "Refrigerado",
    peligroso: "Peligroso", granel: "Granel", carga_general: "Carga general" };
  var ESTADOS_CITA = { agendada: "Agendada", en_ruta: "En ruta", cumplida: "Cumplida", no_show: "No se presentó",
    reprogramada: "Reprogramada", cancelada: "Cancelada" };
  var EVENTOS = { cierre_acceso: "Caseta cerrada", reapertura: "Caseta reabierta", buque_atraca: "Atracó un buque",
    norte: "Norte", carga_urgente: "Carga urgente", personalizado: "Evento especial" };

  var estado = { accesos: {}, rutas: {}, mundo: "B", pronCaseta: null, snap: null, mapas: {}, avisos: [],
    agencia: null, agencias: [], enlaceBot: null };

  /** Parámetro de consulta opcional para filtrar por la agencia elegida. */
  function filtroAgencia(sep) { return AGENCIA && estado.agencia ? sep + "agencia_id=" + encodeURIComponent(estado.agencia) : ""; }

  // ───────────── Mapas (Leaflet) ─────────────
  function prepararRuta(coords) {
    // coords: [[lat, lon], …] desde el origen hasta la caseta; acumula distancias para interpolar
    var acum = [0];
    for (var i = 1; i < coords.length; i++) {
      var dy = coords[i][0] - coords[i - 1][0], dx = coords[i][1] - coords[i - 1][1];
      acum.push(acum[i - 1] + Math.sqrt(dx * dx + dy * dy));
    }
    return { coords: coords, acum: acum, total: acum[acum.length - 1] || 1 };
  }

  function posicion(ruta, progreso) {
    var d = Math.max(0, Math.min(1, progreso)) * ruta.total, a = ruta.acum, c = ruta.coords;
    for (var i = 1; i < a.length; i++) {
      if (d <= a[i]) {
        var t = (d - a[i - 1]) / ((a[i] - a[i - 1]) || 1);
        return [c[i - 1][0] + t * (c[i][0] - c[i - 1][0]), c[i - 1][1] + t * (c[i][1] - c[i - 1][1])];
      }
    }
    return c[c.length - 1];
  }

  function crearMapa(mundo) {
    var div = $("mapa-" + mundo);
    if (!window.L) { div.appendChild(el("p", { style: { padding: "16px" } }, "No se pudo cargar el mapa.")); return null; }
    var mapa = L.map(div, { zoomControl: true, attributionControl: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: "&copy; colaboradores de OpenStreetMap"
    }).addTo(mapa);
    var limites = [];
    Object.keys(estado.rutas).forEach(function (id) {
      var r = estado.rutas[id];
      L.polyline(r.coords, { color: "#0A2238", opacity: 0.45, weight: 5 }).addTo(mapa);
      limites = limites.concat(r.coords);
    });
    if (limites.length) mapa.fitBounds(limites, { padding: [30, 30] });
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
      if (AGENCIA && c.agencia_id !== estado.agencia && !c.es_demo) return; // solo la flota de la agencia
      var ruta = estado.rutas[c.ruta_id];
      if (!ruta) return;
      var p = c.progreso;
      if (c.estado === "en_fila") { // la fila se dibuja hacia atrás sobre la ruta
        fila[c.acceso_id] = (fila[c.acceso_id] || 0) + 1;
        p = Math.max(0.55, 1 - 0.004 * fila[c.acceso_id]);
      }
      var pos = posicion(ruta, p);
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
    if (!$("selector-mundo")) { // vista de agencia: un solo mapa (operación con Fluport)
      if (!estado.mapas.B) estado.mapas.B = crearMapa("B");
      return;
    }
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

  function renderFlota(s) {
    var f = (s.mundos.B.flota || {})[estado.agencia];
    if (!f || !$("flota")) return;
    var datos = [["En ruta", f.en_ruta], ["En fila", f.en_fila], ["En revisión", f.en_revision],
      ["Dentro del puerto", f.dentro], ["Atendidos", f.atendidos], ["Espera promedio", F.num(f.espera_prom_min) + " min"]];
    F.reemplazar($("flota"), datos.map(function (d) {
      return el("div", {}, [el("b", { class: "cifra" }, typeof d[1] === "number" ? F.num(d[1]) : d[1]), d[0]]);
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
    $("etiqueta").textContent = s.etiqueta || "SIMULACIÓN";
    renderCasetas(s.mundos.B.accesos);
    if (AGENCIA) {
      renderFlota(s);
      dibujarMapa("B", s.mundos.B);
      var propios = s.mundos.B.camiones.filter(function (c) { return c.agencia_id === estado.agencia; }).length;
      $("resumen-mapa").textContent = F.num(propios) + " camiones de tu agencia en el mapa";
      return;
    }
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

  // ───────────── Avisos a transportistas (Telegram o WhatsApp) ─────────────
  var TIPOS_AVISO = { turno_30min: "Recordatorio de turno", saturacion: "Caseta saturada o cerrada" };
  var CANALES = { telegram: "Telegram", whatsapp: "WhatsApp", web: "Web" };

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
    try { estado.avisos = await F.api("/api/avisos?limite=6" + filtroAgencia("&")); renderAvisos(estado.avisos); } catch (e) { /* sin BD */ }
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

  // ───────────── Citas ─────────────
  async function cargarCitas() {
    try {
      if (!$("tabla-citas")) return;
      var r = await F.api("/api/citas/resumen" + filtroAgencia("?"));
      $("cumplimiento").textContent = F.num(r.cumplimiento_pct, 1) + " %";
      F.reemplazar($("estados-cita"), ["agendada", "en_ruta", "cumplida", "no_show", "reprogramada", "cancelada"].map(function (k) {
        return el("div", {}, [el("b", {}, F.num(r.por_estado[k])), ESTADOS_CITA[k]]);
      }));
      var lista = await F.api("/api/citas?limite=50" + filtroAgencia("&"));
      var nombres = {};
      (estado.transportistas || []).forEach(function (t) { nombres[t.id] = t.alias; });
      var activas = lista.filter(function (c) { return c.estado === "agendada" || c.estado === "en_ruta"; });
      var otras = lista.filter(function (c) { return activas.indexOf(c) < 0; }).reverse();
      var filas = activas.concat(otras).slice(0, 12);
      F.reemplazar($("tabla-citas"), filas.length ? filas.map(function (c) {
        var meta = estado.accesos[c.acceso_id] || {};
        return el("tr", {}, [
          el("td", { class: "cifra" }, F.hora(c.ventana_inicio)),
          el("td", {}, c.acceso_id + " · " + (meta.nombre || "").replace("Caseta ", "")),
          el("td", {}, nombres[c.transportista_id] || "Transportista #" + c.transportista_id),
          el("td", {}, CARGAS[c.tipo_carga] || c.tipo_carga),
          el("td", { class: "cifra" }, c.espera_estimada_min === null ? "—" : F.num(c.espera_estimada_min) + " min"),
          el("td", {}, el("span", { class: "pastilla" }, ESTADOS_CITA[c.estado] || c.estado))
        ]);
      }) : [el("tr", {}, el("td", { colspan: "6", class: "tenue" }, "Aún no hay citas."))]);
    } catch (e) {
      $("cumplimiento").textContent = "--";
    }
  }

  function sumarDias(fecha, n) {
    var p = fecha.split("-").map(Number);
    return new Date(Date.UTC(p[0], p[1] - 1, p[2] + n)).toISOString().slice(0, 10);
  }

  /** "HH:MM" en el día del reloj simulado (+ n días), en hora de Veracruz (zona del snapshot). */
  function isoSimulado(horaMin, diaExtra) {
    var ts = estado.snap.ts_sim;
    return sumarDias(F.fecha(ts), diaExtra || 0) + "T" + horaMin + ":00" + F.zonaHoraria(ts);
  }

  async function buscarHorarios(ev) {
    ev.preventDefault();
    if (!estado.snap) return;
    var aviso = $("estado-cita");
    var desde = $("cita-desde").value, hasta = $("cita-hasta").value;
    var desdeIso = isoSimulado(desde, 0);
    var hastaIso = isoSimulado(hasta, hasta <= desde ? 1 : 0);
    if (new Date(desdeIso) < new Date(estado.snap.ts_sim)) { // si la hora ya pasó hoy, se busca mañana
      desdeIso = isoSimulado(desde, 1); hastaIso = isoSimulado(hasta, hasta <= desde ? 2 : 1);
    }
    aviso.textContent = "Buscando horarios…";
    try {
      var cuerpo = { desde: desdeIso, hasta: hastaIso, tipo_carga: $("cita-carga").value };
      if ($("cita-caseta").value) cuerpo.acceso_id = $("cita-caseta").value;
      var sug = await F.api("/api/citas/sugerencias", { method: "POST", json: cuerpo });
      aviso.textContent = sug.length ? "Elige un horario:" : "No hay horarios disponibles en esa ventana.";
      F.reemplazar($("sugerencias"), sug.map(function (s) {
        var meta = estado.accesos[s.acceso_id] || {};
        return el("div", { class: "sugerencia" }, [
          el("div", { class: "cifra", style: { fontSize: "24px" } }, F.hora(s.inicio)),
          el("div", {}, s.acceso_id + " · " + (meta.nombre || "")),
          F.chip(s.semaforo, "~" + F.num(s.espera_min_est) + " min"),
          s.ahorro_vs_pico_min ? el("div", { class: "tenue", style: { fontSize: "13px" } }, "Ahorra " + F.num(s.ahorro_vs_pico_min) + " min frente a la peor hora") : null,
          el("button", { type: "button", class: "boton", onclick: function () { agendar(s); } }, "Agendar " + F.hora(s.inicio))
        ]);
      }));
    } catch (e) {
      aviso.textContent = "No se pudieron obtener horarios: " + e.message;
    }
  }

  async function agendar(s) {
    var aviso = $("estado-cita");
    try {
      var c = await F.api("/api/citas", { method: "POST", json: {
        telefono: $("cita-tel").value, acceso_id: s.acceso_id, ventana_inicio: s.inicio, ventana_fin: s.fin,
        tipo_carga: $("cita-carga").value, origen: "web", agencia_id: estado.agencia || null } });
      aviso.textContent = "Cita #" + c.id + " agendada a las " + F.hora(c.ventana_inicio) + " por " + c.acceso_id + ".";
      F.reemplazar($("sugerencias"), []);
      await cargarTransportistas();
      cargarCitas();
    } catch (e) {
      aviso.textContent = "No se pudo agendar: " + e.message;
    }
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

  // ───────────── Agencia: transportistas e invitación al bot ─────────────
  async function cargarTransportistas() {
    if (!AGENCIA || !estado.agencia) return;
    try {
      estado.transportistas = await F.api("/api/agencias/" + encodeURIComponent(estado.agencia) + "/transportistas");
    } catch (e) { estado.transportistas = []; }
    var lista = estado.transportistas;
    F.reemplazar($("lista-transportistas"), lista.length ? lista.map(function (t) {
      return el("li", { style: { flexDirection: "column", gap: "2px" } }, [
        el("span", {}, [el("b", {}, t.alias), t.telefono_fin ? " · …" + t.telefono_fin : "", t.telegram ? " · Telegram" : ""]),
        el("span", { class: "tenue" }, t.citas_activas
          ? F.num(t.citas_activas) + (t.citas_activas === 1 ? " cita activa" : " citas activas") + " · próxima " + F.hora(t.proxima_cita)
          : "Sin citas activas")
      ]);
    }) : [el("li", { class: "tenue" }, "Aún no hay transportistas. Compárteles el enlace del bot.")]);
  }

  function renderInvitacion() {
    var caja = $("invitacion");
    if (!caja) return;
    if (!estado.enlaceBot) {
      F.reemplazar(caja, [el("p", { class: "tenue", style: { margin: "0" } }, "El bot de Telegram no está configurado en el servidor.")]);
      return;
    }
    var url = estado.enlaceBot.enlace + "?start=" + encodeURIComponent(estado.agencia);
    var hijos = [];
    if (window.qrcode) {
      var qr = window.qrcode(0, "M"); qr.addData(url); qr.make();
      var caja_qr = el("div", { class: "qr", role: "img", "aria-label": "Código QR del enlace de tu agencia" });
      caja_qr.innerHTML = qr.createSvgTag(4, 0); // SVG generado localmente a partir de nuestra propia URL
      hijos.push(caja_qr);
    }
    hijos.push(el("a", { class: "boton", href: url, target: "_blank", rel: "noopener" }, "Abrir " + estado.enlaceBot.usuario));
    hijos.push(el("p", { class: "tenue", style: { margin: "0", fontSize: "13px", wordBreak: "break-all" } }, url));
    F.reemplazar(caja, hijos);
  }

  function elegirAgencia(id) {
    estado.agencia = id;
    try { localStorage.setItem("fluport.agencia", id); } catch (e) { /* sin almacenamiento */ }
    var a = estado.agencias.filter(function (x) { return x.id === id; })[0];
    document.title = "Fluport · " + (a ? a.nombre : "Agencia");
    renderInvitacion();
    Object.keys((estado.mapas.B || {}).camiones || {}).forEach(function (k) {
      estado.mapas.B.mapa.removeLayer(estado.mapas.B.camiones[k]); delete estado.mapas.B.camiones[k];
    });
    if (estado.snap) render(estado.snap);
    cargarTransportistas().then(cargarCitas);
    cargarAvisos();
  }

  async function iniciarAgencia() {
    estado.agencias = await F.api("/api/agencias");
    if (!estado.agencias.length) throw new Error("no hay agencias registradas");
    var pedida = new URLSearchParams(location.search).get("agencia"), guardada = null;
    try { guardada = localStorage.getItem("fluport.agencia"); } catch (e) { /* sin almacenamiento */ }
    var ids = estado.agencias.map(function (a) { return a.id; });
    var inicial = [pedida, guardada].filter(function (x) { return x && ids.indexOf(x) >= 0; })[0] || ids[0];
    F.reemplazar($("agencia"), estado.agencias.map(function (a) { return el("option", { value: a.id }, a.nombre); }));
    $("agencia").value = inicial;
    $("agencia").addEventListener("change", function () { elegirAgencia(this.value); });
    try { estado.enlaceBot = await F.api("/api/telegram/enlace"); } catch (e) { estado.enlaceBot = null; }
    elegirAgencia(inicial);
    setInterval(cargarTransportistas, 15000);
  }

  // ───────────── Inicio ─────────────
  async function iniciar() {
    var accesos = await F.api("/api/accesos");
    accesos.forEach(function (a) { estado.accesos[a.id] = a; });
    var geo = await F.api("/api/accesos/rutas");
    geo.features.filter(function (f) { return f.properties.tipo === "ruta"; }).forEach(function (f) {
      estado.rutas[f.properties.ruta_id] = prepararRuta(f.geometry.coordinates.map(function (c) { return [c[1], c[0]]; }));
    });
    accesos.forEach(function (a) {
      var etiqueta = a.id + " · " + a.nombre;
      ["evento-caseta", "cita-caseta"].forEach(function (id) { if ($(id)) $(id).appendChild(el("option", { value: a.id }, etiqueta)); });
    });
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
    if (AGENCIA) {
      await iniciarAgencia();
      $("form-cita").addEventListener("submit", buscarHorarios);
      $("cita-desde").value = "09:00";
      $("cita-hasta").value = "15:00";
    } else {
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
    }

    F.conectarSimulacion(function (m) {
      if (m.tipo === "snapshot") render(m.data);
      else if (m.tipo === "evento") cargarPronostico();
      else if (m.tipo === "aviso") { if (AGENCIA) cargarAvisos(); else { estado.avisos.unshift(m.data); renderAvisos(estado.avisos); } }
    });
    cargarModelo(); cargarPronostico();
    if (!AGENCIA) cargarAvisos();
    setInterval(cargarPronostico, 15000);
    setInterval(cargarCitas, 10000);
    setInterval(cargarModelo, 60000);
  }

  iniciar().catch(function (e) {
    document.querySelector(".principal").prepend(el("p", { class: "tarjeta", role: "alert" }, "No se pudo conectar con el servidor: " + e.message));
  });
})();
