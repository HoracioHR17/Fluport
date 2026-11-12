/* Fluport · panel de agencia por pantallas (<body data-pantalla="resumen|flota|citas|transportistas|avisos">).
 * Comparte menú, agencia elegida (localStorage o ?agencia=) y datos: WS /ws/sim (snapshots) + REST
 * (/api/agencias, /api/citas, /api/avisos, /api/citas/sugerencias). Cada pantalla dibuja solo lo suyo. */
(function () {
  "use strict";
  var F = window.Fluport, el = F.el, $ = function (id) { return document.getElementById(id); };
  var PANTALLA = document.body.dataset.pantalla || "resumen";

  var CARGAS = { contenedor_20: "Contenedor 20'", contenedor_40: "Contenedor 40'", refrigerado: "Refrigerado",
    peligroso: "Peligroso", granel: "Granel", carga_general: "Carga general" };
  var ESTADO_CAMION = { en_ruta: { t: "En ruta", tono: "azul" }, en_fila: { t: "En fila", tono: "amarillo" },
    en_revision: { t: "En revisión", tono: "verde" }, dentro: { t: "Dentro", tono: "verde" }, saliendo: { t: "Saliendo", tono: "azul" } };
  var TIPOS_AVISO = { turno_30min: "Recordatorio", saturacion: "Contingencia", cita_asignada: "Cita asignada", cita_rechazada: "Respuesta del chofer",
    cita_cancelada: "Cancelación avisada", cita_reasignada: "Cambio avisado", cambio_chofer: "Cambio del chofer", cancelacion_chofer: "Cancelación del chofer",
    solicitud_cancelacion: "Pide cancelar" };
  var TONO_AVISO = { turno_30min: "verde", saturacion: "oscuro", cita_asignada: "azul", cita_rechazada: "rojo",
    cita_cancelada: "oscuro", cita_reasignada: "azul", cambio_chofer: "azul", cancelacion_chofer: "rojo", solicitud_cancelacion: "rojo" };
  // tipos que agrupa cada filtro de avisos (el resto filtra por su propio tipo)
  var GRUPO_AVISOS = { cita_rechazada: ["cita_rechazada", "cambio_chofer", "cancelacion_chofer", "solicitud_cancelacion"], cita_asignada: ["cita_asignada", "cita_reasignada", "cita_cancelada"] };
  var REASIGNAR = ["cita_rechazada", "cancelacion_chofer", "solicitud_cancelacion"];
  var ACTIVAS = { agendada: true, en_ruta: true };

  var estado = { agencia: null, agencias: [], accesos: {}, rutas: {}, snap: null, mapa: null, bot: null,
    transportistas: [], solicitudes: [], citas: [], avisos: [], filtroCitas: "activas", filtroFlota: "todos", filtroTrans: "todos",
    filtroAvisos: "todos", busqueda: "", seleccion: null, historia: [] };

  // ───────────── Utilidades ─────────────
  function nombreCaseta(id) { return ((estado.accesos[id] || {}).nombre || id || "").replace("Caseta ", ""); }
  function porId(lista) { var m = {}; lista.forEach(function (x) { m[x.id] = x; }); return m; }
  function q(sep) { return sep + "agencia_id=" + encodeURIComponent(estado.agencia); }
  function chip(tono, texto) { return el("span", { class: "chip chip--" + tono }, texto); }
  function plural(n, uno, varios) { return F.num(n) + " " + (n === 1 ? uno : varios); }

  function estadoCita(c) {
    if (c.estado === "agendada") {
      if (c.origen !== "web") return { texto: "Pedida por el chofer", tono: "azul" };
      return { texto: "Asignada", tono: "verde" }; // las citas de la agencia son obligatorias: no se confirman
    }
    return ({ en_ruta: { texto: "En ruta", tono: "azul" }, cumplida: { texto: "Cumplida", tono: "verde" },
      no_show: { texto: "No se presentó", tono: "rojo" }, reprogramada: { texto: "Reprogramada", tono: "amarillo" },
      cancelada: { texto: "Cancelada", tono: "oscuro" } })[c.estado] || { texto: c.estado, tono: "azul" };
  }

  function camionesAgencia() {
    if (!estado.snap) return [];
    return estado.snap.mundos.B.camiones.filter(function (c) { return c.agencia_id === estado.agencia; });
  }

  // ───────────── Menú, contadores y reloj (todas las pantallas) ─────────────
  function contadores() {
    var rech = estado.avisos.filter(function (a) { return REASIGNAR.indexOf(a.tipo) >= 0; }).length;
    var sinBot = estado.transportistas.filter(function (t) { return !t.telegram; }).length;
    [["avisos", rech], ["transportistas", sinBot + estado.solicitudes.length]].forEach(function (p) {
      var n = document.querySelector('[data-contador="' + p[0] + '"]');
      if (n) { n.textContent = p[1]; n.classList.toggle("oculto", !p[1]); }
    });
  }

  function reloj(s) {
    $("reloj").textContent = F.fecha(s.ts_sim) + " · " + F.hora(s.ts_sim) + " (hora simulada)" + (s.clima === "norte" ? " · norte activo" : "");
    if ($("sim-pausa")) { // panel de simulación (pantalla principal)
      var pausada = s.estado !== "corriendo";
      $("sim-pausa").textContent = pausada ? "Reanudar" : "Pausar";
      if (document.activeElement !== $("sim-velocidad")) $("sim-velocidad").value = String(Math.round(s.velocidad));
      var cerradas = s.mundos.B.accesos.filter(function (a) { return a.estado === "cerrado"; }).map(function (a) { return nombreCaseta(a.acceso_id); });
      $("sim-estado").textContent = (pausada ? "En pausa" : "Corriendo") + (cerradas.length ? " · cerrada: " + cerradas.join(", ") : "");
    }
  }

  // ───────────── Panel de simulación (antes /demo) ─────────────
  var EVENTOS_SIM = { cierre_acceso: "Entrada cerrada", reapertura: "Entrada reabierta", buque_atraca: "Atracó un buque", norte: "Norte activo" };
  function iniciarPanelSimulacion() {
    if (!$("sim-pausa")) return;
    Object.keys(estado.accesos).sort().forEach(function (id) { $("sim-acceso").appendChild(el("option", { value: id }, nombreCaseta(id))); });
    $("sim-pausa").addEventListener("click", function () {
      var accion = estado.snap && estado.snap.estado === "corriendo" ? "pause" : "play";
      F.api("/api/sim/control", { method: "POST", json: { accion: accion } }).catch(function (e) { $("sim-msg").textContent = "No se pudo: " + e.message; });
    });
    $("sim-velocidad").addEventListener("change", function () {
      F.api("/api/sim/control", { method: "POST", json: { accion: "velocidad", velocidad: Number(this.value) } }).catch(function () {});
    });
    [].forEach.call(document.querySelectorAll("[data-evento]"), function (b) {
      b.addEventListener("click", async function () {
        var tipo = b.dataset.evento, cuerpo = { tipo: tipo, payload: {} };
        if (tipo === "cierre_acceso" || tipo === "reapertura") cuerpo.acceso_id = $("sim-acceso").value;
        if (tipo === "buque_atraca") cuerpo.payload = { contenedores: 2000 };
        b.disabled = true;
        try {
          await F.api("/api/sim/eventos", { method: "POST", json: cuerpo });
          $("sim-msg").textContent = EVENTOS_SIM[tipo] + (cuerpo.acceso_id ? ": " + nombreCaseta(cuerpo.acceso_id) : "") + ".";
        } catch (e) { $("sim-msg").textContent = "No se aplicó: " + e.message; }
        finally { b.disabled = false; }
      });
    });
  }

  // ───────────── Resumen ─────────────
  // Historial corto en el navegador para las líneas de tendencia de los indicadores (una muestra cada 5 s).
  var HISTORIA_MAX = 36;
  function registrarHistoria() {
    var s = estado.snap;
    if (!s) return;
    var ahora = Date.now(), h = estado.historia;
    if (h.length && ahora - h[h.length - 1].t < 5000) return;
    var f = (s.mundos.B.flota || {})[estado.agencia] || {};
    h.push({ t: ahora, en_ruta: f.en_ruta || 0, en_fila: f.en_fila || 0, espera: f.espera_prom_min || 0,
      activas: estado.citas.filter(function (c) { return ACTIVAS[c.estado]; }).length });
    if (h.length > HISTORIA_MAX) h.shift();
  }
  function serie(clave, actual) {
    var v = estado.historia.map(function (x) { return x[clave]; });
    return v.length > 1 ? v : [actual, actual];
  }

  function renderResumen() {
    if (!$("kpis")) return;
    registrarHistoria();
    var s = estado.snap, f = s ? ((s.mundos.B.flota || {})[estado.agencia] || {}) : {};
    var activas = estado.citas.filter(function (c) { return ACTIVAS[c.estado]; });
    var asignadas = activas.filter(function (c) { return c.origen === "web"; }).length;
    var espA = s ? s.mundos.A.kpis.espera_prom_min : 0;
    var kpis = [
      ["Camiones en ruta", F.num(f.en_ruta), "", "hacia las casetas", "en_ruta", f.en_ruta || 0, "/agencia/flota/"],
      ["En fila en casetas", F.num(f.en_fila), "", "esperando turno", "en_fila", f.en_fila || 0, "/agencia/flota/"],
      ["Citas activas", F.num(activas.length), "", F.num(asignadas) + " asignadas · " + F.num(activas.length - asignadas) + " pedidas por choferes", "activas", activas.length, "/agencia/citas/"],
      ["Espera promedio de mi flota", F.num(f.espera_prom_min), "min", espA >= 5 ? F.num(Math.max(0, espA - (f.espera_prom_min || 0))) + " min menos que sin Fluport" : "acumulada del día", "espera", f.espera_prom_min || 0, "/agencia/flota/"]
    ];
    F.reemplazar($("kpis"), kpis.map(function (k) {
      return el("a", { class: "kpi kpi--grafica", href: k[6] }, [
        el("span", {}, k[0]),
        el("span", { class: "kpi__valor" }, [el("span", { class: "cifra" }, k[1]), k[2] ? el("span", { class: "kpi__unidad" }, k[2]) : null]),
        F.sparkline(serie(k[4], k[5]), { ancho: 120, alto: 34, area: true }),
        el("span", {}, k[3])
      ]);
    }));
    renderCitasHora(activas);
    renderDona(f);
    renderAhorro(s, f);
    if (s) renderCasetas(s.mundos.B);
    renderAtencion();
  }

  /** Barras apiladas de las citas activas por hora de llegada: asignadas por la agencia y pedidas por el chofer. */
  function renderCitasHora(activas) {
    var caja = $("citas-hora");
    if (!caja) return;
    $("total-horas").textContent = plural(activas.length, "cita activa", "citas activas");
    if (!activas.length) { F.reemplazar(caja, [el("p", { class: "vacio" }, "Sin citas activas. Asigna una desde Citas.")]); return; }
    var porHora = {};
    activas.forEach(function (c) {
      var h = F.hora(c.ventana_inicio).slice(0, 2) + ":00";
      var g = porHora[h] = porHora[h] || { conf: 0, chofer: 0, sin: 0 };
      if (c.origen !== "web") g.chofer++; else g.conf++;
    });
    var horas = Object.keys(porHora).sort(), max = 1;
    horas.forEach(function (h) { var g = porHora[h]; max = Math.max(max, g.conf + g.chofer + g.sin); });
    var techo = Math.max(4, max);
    F.reemplazar(caja, [el("div", { class: "apiladas__caja" }, el("div", { class: "apiladas__in", role: "img",
      "aria-label": horas.map(function (h) { var g = porHora[h]; return h + ": " + g.conf + " asignadas, " + g.chofer + " pedidas por chofer"; }).join("; ") }, [
      el("div", { class: "apiladas__area" }, horas.map(function (h) {
        var g = porHora[h], tot = g.conf + g.chofer + g.sin;
        return el("div", { class: "apiladas__col" }, [
          el("span", { class: "apiladas__total" }, String(tot)),
          g.sin ? el("div", { class: "apiladas__tramo apiladas__tramo--sin", style: { height: (g.sin / techo * 100) + "%" } }) : null,
          g.chofer ? el("div", { class: "apiladas__tramo", style: { height: (g.chofer / techo * 100) + "%", background: "#3D6A8F" } }) : null,
          g.conf ? el("div", { class: "apiladas__tramo", style: { height: (g.conf / techo * 100) + "%", background: "#0A2238" } }) : null
        ]);
      })),
      el("div", { class: "apiladas__horas", "aria-hidden": "true" }, horas.map(function (h) { return el("span", {}, h); }))
    ]))]);
  }

  var PARTES_FLOTA = [["en_ruta", "En ruta", "#0A2238", "ruta"], ["en_fila", "En fila", "#E9B03B", "fila"],
    ["en_revision", "En revisión", "#3FAE7A", "revision"], ["dentro", "Dentro del puerto", "#8FB3D1", "dentro"]];
  function iconoParte(tipo, color) {
    var forma = tipo === "ruta" ? F.svg("path", { d: "M2 3 L14 8 L2 13 L5 8 Z", fill: color })
      : tipo === "fila" ? F.svg("rect", { x: 2, y: 2, width: 12, height: 12, fill: color, stroke: "#0A2238", "stroke-width": 1.2 })
      : tipo === "dentro" ? F.svg("circle", { cx: 8, cy: 8, r: 5, fill: "#FFFFFF", stroke: "#3D6A8F", "stroke-width": 3 })
      : F.svg("circle", { cx: 8, cy: 8, r: 6, fill: color });
    return F.svg("svg", { width: 16, height: 16, viewBox: "0 0 16 16", "aria-hidden": "true" }, forma);
  }
  function renderDona(f) {
    if (!$("flota-dona")) return;
    var total = PARTES_FLOTA.reduce(function (s, p) { return s + (f[p[0]] || 0); }, 0);
    var etiqueta = PARTES_FLOTA.map(function (p) { return F.num(f[p[0]] || 0) + " " + p[1].toLowerCase(); }).join(", ");
    F.reemplazar($("flota-dona"), [
      F.dona(PARTES_FLOTA.map(function (p) { return { valor: f[p[0]] || 0, color: p[2] }; }), F.num(total), total === 1 ? "camión" : "camiones", "Mi flota: " + etiqueta),
      el("ul", { class: "flota-dona__lista" }, PARTES_FLOTA.map(function (p) {
        return el("li", {}, [iconoParte(p[3], p[2]), el("span", {}, p[1]), el("b", { class: "cifra" }, F.num(f[p[0]] || 0))]);
      }))
    ]);
  }

  function renderAhorro(s, f) {
    if (!$("ahorro")) return;
    if (!s) { F.reemplazar($("ahorro"), [el("p", { class: "vacio" }, "Esperando datos de la simulación…")]); return; }
    var a = s.mundos.A.kpis.espera_prom_min, b = f.espera_prom_min || 0, c = s.comparacion, max = Math.max(a, b, 1);
    function barra(texto, v, color) {
      return el("div", { class: "ahorro__fila" }, [
        el("div", { class: "ranking__txt" }, [el("span", {}, texto), el("b", { class: "cifra" }, F.num(v) + " min")]),
        el("div", { class: "ranking__pista" }, el("div", { class: "ranking__barra", style: { width: (v / max * 100).toFixed(0) + "%", background: color } }))
      ]);
    }
    F.reemplazar($("ahorro"), [
      el("div", { role: "img", "aria-label": "Espera promedio: tu flota " + F.num(b) + " min, sin Fluport " + F.num(a) + " min", class: "ahorro__barras" }, [
        barra("Mi flota con Fluport", b, "#0A2238"), barra("Sin Fluport (llegada libre)", a, "#A9C3DA")]),
      el("dl", { class: "ahorro__datos" }, [
        el("div", {}, [el("dt", {}, "Horas de espera"), el("dd", { class: "cifra" }, F.num(c.horas_ahorradas) + " h")]),
        el("div", {}, [el("dt", {}, "Diésel"), el("dd", { class: "cifra" }, F.num(c.diesel_l_evitado) + " L")]),
        el("div", {}, [el("dt", {}, "CO₂"), el("dd", { class: "cifra" }, F.num(c.co2_kg_evitado) + " kg")])
      ]),
      el("p", { class: "tenue", style: { margin: 0, fontSize: "12px" } }, "Ahorro de todo el puerto en la simulación de hoy, comparado con la llegada sin citas.")
    ]);
  }

  function renderCasetas(mb) {
    var enFila = {};
    camionesAgencia().forEach(function (c) { if (c.estado === "en_fila") enFila[c.acceso_id] = (enFila[c.acceso_id] || 0) + 1; });
    F.reemplazar($("casetas"), mb.accesos.map(function (a) {
      var e = F.estadoDe(a.semaforo, a.estado !== "cerrado"), n = enFila[a.acceso_id] || 0;
      return el("div", { class: "caseta caseta--" + e }, [
        F.simbolo(e, 24),
        el("div", { style: { display: "flex", flexDirection: "column", gap: "2px", flex: "1" } }, [
          el("strong", {}, nombreCaseta(a.acceso_id)),
          el("span", { class: "tenue", style: { fontSize: "13px" } }, F.ETIQUETA[e] + (e === "cerrado" ? "" : " · " + F.num(a.espera_min) + " min"))
        ]),
        el("div", { class: "caseta__der" }, [el("span", { class: "cifra" }, F.num(n)), el("span", { class: "tenue", style: { fontSize: "12px" } }, n === 1 ? "mío en fila" : "míos en fila")])
      ]);
    }));
  }

  function renderAtencion() {
    if (!$("atencion")) return;
    var items = [], cerradas = {};
    if (estado.snap) estado.snap.mundos.B.accesos.forEach(function (a) { if (a.estado === "cerrado") cerradas[a.acceso_id] = true; });
    var enCerrada = estado.citas.filter(function (c) { return c.estado === "agendada" && cerradas[c.acceso_id]; });
    if (enCerrada.length) items.push(["▲", "#FBEAE8", plural(enCerrada.length, "cita en caseta cerrada", "citas en caseta cerrada"), "Fluport avisó a los transportistas con una alternativa.", "Revisar citas", "/agencia/citas/"]);
    estado.avisos.filter(function (a) { return REASIGNAR.indexOf(a.tipo) >= 0; }).slice(0, 2).forEach(function (r) {
      items.push(["!", "#FBEAE8", r.tipo === "cancelacion_chofer" ? "Un transportista canceló su cita" : r.tipo === "solicitud_cancelacion" ? "Un transportista pide cancelar" : "Un transportista no puede asistir", r.mensaje.replace(/\*/g, ""), "Reasignar", "/agencia/citas/#asignar"]);
    });
    var sol = estado.solicitudes.length;
    if (sol) items.push(["+", "#E6F4EA", plural(sol, "solicitud de alta", "solicitudes de alta"), "Transportistas que pidieron unirse a tu agencia desde Telegram.", "Revisar", "/agencia/transportistas/"]);
    var ped = estado.citas.filter(function (c) { return c.estado === "agendada" && c.origen !== "web"; }).length;
    if (ped) items.push(["●", "#E3EEF6", plural(ped, "cita pedida por un chofer", "citas pedidas por choferes"), "Agendadas desde el bot.", "Ver cuáles", "/agencia/citas/"]);
    var sinBot = estado.transportistas.filter(function (t) { return !t.telegram; }).length;
    if (sinBot) items.push(["●", "#E3EEF6", plural(sinBot, "transportista sin Telegram", "transportistas sin Telegram"), "No recibirán sus citas hasta abrir la invitación.", "Ver invitación", "/agencia/transportistas/"]);
    $("total-atencion").textContent = items.length ? plural(items.length, "pendiente", "pendientes") : "";
    F.reemplazar($("atencion"), items.length ? items.map(function (it) {
      return el("li", {}, [
        el("div", { class: "atencion__fila" }, [
          el("span", { class: "atencion__icono", "aria-hidden": "true", style: { background: it[1] } }, it[0]),
          el("div", {}, [el("strong", {}, it[2]), el("span", { class: "tenue" }, it[3])])
        ]),
        el("a", { class: "btn btn--suave btn--chico", href: it[5], style: { alignSelf: "flex-start" } }, it[4])
      ]);
    }) : [el("li", { class: "vacio", style: { border: "0" } }, "Todo en orden por ahora.")]);
  }

  // ───────────── Flota ─────────────
  // Simbología del mapa (graficas.js): casetas con la forma de su estado y rutas teñidas; camiones con forma por
  // estado (flecha en ruta, cuadro en fila, anillo dentro), halo punteado si traen cita y aro si están elegidos.
  function crearMapa() {
    if (!$("mapa")) return;
    var puntos = Object.keys(estado.accesos).map(function (id) { return [estado.accesos[id].lat, estado.accesos[id].lon]; });
    Object.keys(estado.rutas).forEach(function (id) { puntos = puntos.concat(estado.rutas[id].coords); });
    var mapa = F.mapaPuerto($("mapa"), puntos);
    if (!mapa) return;
    var rutas = {}, casetas = {};
    Object.keys(estado.rutas).forEach(function (id) { rutas[id] = L.polyline(estado.rutas[id].coords, F.estiloRuta("verde")).addTo(mapa); });
    Object.keys(estado.accesos).forEach(function (id) {
      var a = estado.accesos[id];
      L.polyline([[a.lat, a.lon], [F.PUERTO.lat, F.PUERTO.lon]], { color: "#0A2238", weight: 2, opacity: 0.45, dashArray: "4 6", interactive: false }).addTo(mapa);
      casetas[id] = L.marker([a.lat, a.lon], { icon: F.iconoCaseta("verde", nombreCaseta(id)), keyboard: false, zIndexOffset: 500 }).addTo(mapa);
    });
    estado.mapa = { mapa: mapa, camiones: {}, casetas: casetas, rutas: rutas };
  }

  /** Posición, forma y orientación de un camión en el mapa. */
  function ubicarCamion(c, fila) {
    var r = estado.rutas[c.ruta_id], a = estado.accesos[c.acceso_id];
    if (c.estado === "dentro" || c.estado === "saliendo") {
      var k = parseInt(String(c.id).replace(/\D/g, ""), 10) || 0; // reparto estable alrededor del puerto
      return { pos: [F.PUERTO.lat - 0.006 - (k % 6) * 0.0035, F.PUERTO.lon - 0.006 - (Math.floor(k / 6) % 4) * 0.0035], tipo: "dentro" };
    }
    if (!r) return null;
    if (c.estado === "en_revision" && a) return { pos: [a.lat, a.lon], tipo: "dentro" };
    if (c.estado === "en_fila") {
      fila[c.acceso_id] = (fila[c.acceso_id] || 0) + 1;
      return { pos: F.posicion(r, Math.max(0.6, 1 - 0.012 * fila[c.acceso_id])), tipo: "fila" };
    }
    var p = F.posicion(r, c.progreso), q = F.posicion(r, Math.min(1, c.progreso + 0.02));
    return { pos: p, tipo: "ruta", angulo: F.rumbo(p, q) };
  }

  /** Datos de presentación de un camión: transportista y placas si es de una cita registrada. */
  function datosCamion(c) {
    var cita = c.cita_id ? estado.citas.filter(function (x) { return x.id === c.cita_id; })[0] : null;
    var t = cita ? porId(estado.transportistas)[cita.transportista_id] : null;
    return { cita: cita, t: t, nombre: t && t.placas ? t.placas : "Camión " + c.id, chofer: t ? t.alias : "—" };
  }

  function filtrarFlota(lista) {
    var b = estado.busqueda.toLowerCase();
    return lista.filter(function (c) {
      var f = estado.filtroFlota;
      if (f === "con_cita" && !c.cita_id) return false;
      if (f === "dentro" && c.estado !== "dentro" && c.estado !== "en_revision" && c.estado !== "saliendo") return false;
      if ((f === "en_ruta" || f === "en_fila") && c.estado !== f) return false;
      if (!b) return true;
      var d = datosCamion(c);
      return (d.nombre + " " + d.chofer + " " + c.id).toLowerCase().indexOf(b) >= 0;
    });
  }

  function renderFlota() {
    if (!$("tabla-camiones") || !estado.snap) return;
    var mb = estado.snap.mundos.B, todos = camionesAgencia();
    var cuenta = { todos: todos.length, en_ruta: 0, en_fila: 0, dentro: 0, con_cita: 0 };
    todos.forEach(function (c) {
      if (c.estado === "en_ruta") cuenta.en_ruta++; else if (c.estado === "en_fila") cuenta.en_fila++; else cuenta.dentro++;
      if (c.cita_id) cuenta.con_cita++;
    });
    [].forEach.call($("filtro-flota").children, function (b) { b.textContent = b.dataset.texto + " · " + F.num(cuenta[b.dataset.id] || 0); });
    var lista = filtrarFlota(todos);
    var orden = { en_fila: 0, en_ruta: 1, en_revision: 2, dentro: 3, saliendo: 4 };
    lista.sort(function (a, b) { return (orden[a.estado] - orden[b.estado]) || (b.cita_id ? 1 : 0) - (a.cita_id ? 1 : 0); });
    // mapa
    var m = estado.mapa;
    if (m) {
      var vistos = {}, fila = {};
      lista.forEach(function (c) {
        var u = ubicarCamion(c, fila);
        if (!u) return;
        var sel = c.id === estado.seleccion, clave = u.tipo + (c.cita_id ? "c" : "") + (sel ? "s" : "") + (u.tipo === "ruta" ? Math.round(u.angulo / 15) : "");
        vistos[c.id] = true;
        var mk = m.camiones[c.id];
        if (!mk) {
          mk = m.camiones[c.id] = L.marker(u.pos, { keyboard: false, zIndexOffset: sel ? 1000 : 0, title: datosCamion(c).nombre }).addTo(m.mapa);
          mk.on("click", function () { seleccionar(c.id); });
        } else mk.setLatLng(u.pos);
        if (mk._clave !== clave) { mk.setIcon(F.iconoCamion(u.tipo, { cita: !!c.cita_id, sel: sel, angulo: u.angulo })); mk.setZIndexOffset(sel ? 1000 : 0); mk._clave = clave; }
      });
      Object.keys(m.camiones).forEach(function (id) { if (!vistos[id]) { m.mapa.removeLayer(m.camiones[id]); delete m.camiones[id]; } });
      mb.accesos.forEach(function (a) {
        var e = F.estadoDe(a.semaforo, a.estado !== "cerrado");
        if (m.casetas[a.acceso_id]) m.casetas[a.acceso_id].setIcon(F.iconoCaseta(e, nombreCaseta(a.acceso_id) + " · " + (e === "cerrado" ? "cerrada" : F.num(a.espera_min) + " min")));
        Object.keys(m.rutas).forEach(function (id) { if (estado.rutas[id].acceso === a.acceso_id) m.rutas[id].setStyle(F.estiloRuta(e)); });
      });
    }
    renderColas(todos);
    $("resumen-mapa").textContent = plural(lista.length, "camión en el mapa", "camiones en el mapa");
    // tabla (las primeras 60 filas para que siga siendo ágil)
    F.reemplazar($("tabla-camiones"), lista.length ? lista.slice(0, 60).map(function (c) {
      var d = datosCamion(c), e = ESTADO_CAMION[c.estado] || { t: c.estado, tono: "azul" };
      return el("tr", { class: "clicable", tabindex: "0", "aria-selected": String(c.id === estado.seleccion),
        onclick: function () { seleccionar(c.id); }, onkeydown: function (ev) { if (ev.key === "Enter") seleccionar(c.id); } }, [
        el("td", { class: "cifra" }, d.nombre), el("td", {}, d.chofer), el("td", {}, chip(e.tono, e.t)),
        el("td", {}, nombreCaseta(c.acceso_id)), el("td", {}, CARGAS[c.tipo_carga] || c.tipo_carga),
        el("td", {}, d.cita ? F.hora(d.cita.ventana_inicio) + " · " + estadoCita(d.cita).texto : "—")
      ]);
    }) : [el("tr", {}, el("td", { colspan: "6", class: "vacio" }, "No hay camiones con este filtro."))]);
    renderFicha();
  }

  /** Barras apiladas por caseta: mis camiones en fila y en camino. */
  function renderColas(todos) {
    if (!$("colas")) return;
    var ids = Object.keys(estado.accesos).sort(), cuenta = {}, max = 1;
    ids.forEach(function (id) { cuenta[id] = { fila: 0, ruta: 0 }; });
    todos.forEach(function (c) { var k = cuenta[c.acceso_id]; if (!k) return; if (c.estado === "en_fila") k.fila++; else if (c.estado === "en_ruta") k.ruta++; });
    ids.forEach(function (id) { max = Math.max(max, cuenta[id].fila + cuenta[id].ruta); });
    F.reemplazar($("colas"), ids.map(function (id) {
      var k = cuenta[id];
      return el("div", { class: "ranking__fila" }, [
        el("div", { class: "ranking__txt" }, [el("span", {}, nombreCaseta(id)), el("span", {}, [el("b", {}, F.num(k.fila)), " en fila · " + F.num(k.ruta) + " en camino"])]),
        el("div", { class: "colas__pista", role: "img", "aria-label": nombreCaseta(id) + ": " + k.fila + " en fila, " + k.ruta + " en camino" }, [
          el("div", { class: "colas__fila", style: { width: (k.fila / max * 100) + "%" } }),
          el("div", { class: "colas__ruta", style: { width: (k.ruta / max * 100) + "%" } })
        ])
      ]);
    }));
  }

  function seleccionar(id) { estado.seleccion = id; renderFlota(); }

  function renderFicha() {
    var c = camionesAgencia().filter(function (x) { return x.id === estado.seleccion; })[0];
    if (!c) { F.reemplazar($("ficha"), [el("p", { class: "vacio" }, "Elige un camión de la lista para ver su ficha.")]); return; }
    var d = datosCamion(c), e = ESTADO_CAMION[c.estado] || { t: c.estado, tono: "azul" };
    var a = estado.snap.mundos.B.accesos.filter(function (x) { return x.acceso_id === c.acceso_id; })[0];
    var filas = [["Caseta", nombreCaseta(c.acceso_id)], ["Carga", CARGAS[c.tipo_carga] || c.tipo_carga],
      ["Espera en caseta", a ? F.num(a.espera_min) + " min" : "—"]];
    if (d.cita) filas.push(["Cita", F.hora(d.cita.ventana_inicio) + " · " + estadoCita(d.cita).texto]);
    var dl = el("dl", {});
    filas.forEach(function (f) { dl.appendChild(el("dt", {}, f[0])); dl.appendChild(el("dd", {}, f[1])); });
    F.reemplazar($("ficha"), [el("div", { class: "ficha" }, [
      el("div", {}, [el("strong", { class: "cifra", style: { fontSize: "22px", display: "block" } }, d.nombre), el("span", { class: "tenue" }, d.chofer !== "—" ? d.chofer : "Camión simulado de la agencia")]),
      chip(e.tono, e.t), dl,
      d.cita ? el("a", { class: "btn btn--suave btn--chico", href: "/agencia/citas/", style: { alignSelf: "flex-start" } }, "Ver su cita") : null
    ])]);
  }

  // ───────────── Citas ─────────────
  var FILTROS_CITAS = [["activas", "Activas"], ["choferes", "Pedidas por choferes"], ["historial", "Historial"]];

  function renderCitas() {
    if (!$("tabla-citas")) return;
    var t = porId(estado.transportistas);
    var pasa = {
      activas: function (c) { return ACTIVAS[c.estado]; },
      choferes: function (c) { return c.origen !== "web"; }, historial: function (c) { return !ACTIVAS[c.estado]; }
    };
    [].forEach.call($("filtros").children, function (b) { b.textContent = b.dataset.texto + " · " + F.num(estado.citas.filter(pasa[b.dataset.id]).length); });
    var lista = estado.citas.filter(pasa[estado.filtroCitas]);
    var activas = estado.citas.filter(pasa.activas);
    $("resumen-citas").textContent = plural(activas.length, "cita activa", "citas activas") + " · " + F.num(activas.filter(function (c) { return c.origen === "web"; }).length) + " asignadas por la agencia";
    renderLineaTiempo();
    // mientras la agencia edita una cita no se redibuja la tabla (perdería lo que está escribiendo)
    if (estado.edicion && $("edicion-cita") && estado.citas.some(function (c) { return c.id === estado.edicion.id && c.estado === "agendada"; })) return;
    if (estado.edicion && !estado.citas.some(function (c) { return c.id === estado.edicion.id && c.estado === "agendada"; })) estado.edicion = null;
    var filas = [];
    lista.forEach(function (c) {
      filas.push(filaCita(c, t));
      if (estado.edicion && estado.edicion.id === c.id) filas.push(filaEdicion(c));
    });
    F.reemplazar($("tabla-citas"), filas.length ? filas : [el("tr", {}, el("td", { colspan: "7", class: "vacio" }, "No hay citas con este filtro."))]);
  }

  function filaCita(c, t) {
      var e = estadoCita(c), tr = t[c.transportista_id] || {};
      return el("tr", { class: (c.id === estado.citaResaltada ? "elegida" : ""), "data-cita": c.id, tabindex: "-1" }, [
        el("td", { class: "cifra" }, F.hora(c.ventana_inicio)),
        el("td", {}, tr.alias || "Transportista #" + c.transportista_id),
        el("td", { class: "cifra" }, tr.placas || "—"),
        el("td", {}, nombreCaseta(c.acceso_id)),
        el("td", {}, c.espera_estimada_min === null ? "—" : "~" + F.num(c.espera_estimada_min) + " min"),
        el("td", {}, chip(e.tono, e.texto)),
        el("td", { style: { textAlign: "right", whiteSpace: "nowrap" } }, c.estado === "agendada" ? [
          el("button", { type: "button", class: "btn btn--suave btn--chico", "aria-expanded": String(!!(estado.edicion && estado.edicion.id === c.id)),
            onclick: function () { abrirEdicion(c); } }, "Cambiar"), " ",
          el("button", { type: "button", class: "btn btn--sec btn--chico", onclick: function () { cancelar(c); } }, "Cancelar")
        ] : null)
      ]);
  }

  // ───────────── Cambiar una cita (entrada y hora); el transportista recibe el aviso por Telegram ─────────────
  function abrirEdicion(c) {
    estado.edicion = estado.edicion && estado.edicion.id === c.id ? null
      : { id: c.id, acceso: c.acceso_id, hora: F.hora(c.ventana_inicio), msg: "" };
    renderCitasForzado();
  }

  function renderCitasForzado() {
    var e = estado.edicion; estado.edicion = null; renderCitas(); estado.edicion = e;
    if (e) { renderCitas(); var s = $("edicion-acceso"); if (s) s.focus(); }
  }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  /** fecha AAAA-MM-DD + hora HH:MM + minutos → ISO con la zona horaria dada (cruza la medianoche si hace falta). */
  function isoMas(fecha, hm, zona, minutos) {
    var p = hm.split(":").map(Number), t = p[0] * 60 + p[1] + (minutos || 0), dias = Math.floor(t / 1440);
    t = ((t % 1440) + 1440) % 1440;
    return sumarDias(fecha, dias) + "T" + pad2(Math.floor(t / 60)) + ":" + pad2(t % 60) + ":00" + zona;
  }

  function filaEdicion(c) {
    var ed = estado.edicion;
    var opciones = Object.keys(estado.accesos).sort().map(function (id) {
      return el("option", { value: id, selected: id === ed.acceso ? "selected" : null }, nombreCaseta(id));
    });
    return el("tr", { class: "edicion-cita" }, el("td", { colspan: "7" },
      el("form", { class: "form form--fila", id: "edicion-cita", onsubmit: function (ev) { ev.preventDefault(); guardarEdicion(c); } }, [
        el("label", { class: "campo" }, ["Entrada", el("select", { id: "edicion-acceso", onchange: function () { ed.acceso = this.value; } }, opciones)]),
        el("label", { class: "campo" }, ["Hora", el("input", { id: "edicion-hora", type: "time", required: "required", value: ed.hora,
          oninput: function () { ed.hora = this.value; } })]),
        el("button", { type: "submit", class: "btn btn--chico" }, "Guardar y avisar al chofer"),
        el("button", { type: "button", class: "btn btn--sec btn--chico", onclick: function () { estado.edicion = null; renderCitasForzado(); } }, "Cerrar"),
        el("p", { class: "estado-msg", role: "status" }, ed.msg)
      ])));
  }

  async function guardarEdicion(c) {
    var ed = estado.edicion;
    if (!ed || !ed.hora) return;
    var zona = F.zonaHoraria(c.ventana_inicio), fecha = F.fecha(c.ventana_inicio);
    var duracion = Math.round((new Date(c.ventana_fin) - new Date(c.ventana_inicio)) / 60000) || 30;
    if (ed.acceso === c.acceso_id && ed.hora === F.hora(c.ventana_inicio)) { ed.msg = "No hay cambios que guardar."; renderCitasForzado(); return; }
    try {
      var nueva = await F.api("/api/citas/" + c.id, { method: "PATCH", json: {
        acceso_id: ed.acceso, ventana_inicio: isoMas(fecha, ed.hora, zona, 0), ventana_fin: isoMas(fecha, ed.hora, zona, duracion) } });
      estado.edicion = null; estado.citaResaltada = nueva.id;
      $("estado-cita").textContent = "Cita cambiada: ahora es la #" + nueva.id + ". Se le avisó al transportista por Telegram.";
      await cargarCitas();
    } catch (e) { ed.msg = "No se pudo cambiar: " + e.message; renderCitasForzado(); }
  }

  /** Línea de tiempo: una fila por caseta, de 1 h antes a 11 h después de la hora simulada. */
  function renderLineaTiempo() {
    var caja = $("linea-tiempo");
    if (!caja || !estado.snap) return;
    var ahora = new Date(estado.snap.ts_sim).getTime(), H = 3600000;
    var ini = Math.floor(ahora / H) * H - H, fin = ini + 12 * H;
    var pct = function (t) { return ((t - ini) / (fin - ini) * 100); };
    var t = porId(estado.transportistas);
    var activas = estado.citas.filter(function (c) { return ACTIVAS[c.estado]; });
    var horas = []; for (var h = 0; h < 12; h++) horas.push(el("span", {}, F.hora(new Date(ini + h * H).toISOString())));
    var ids = Object.keys(estado.accesos).sort();
    var mb = estado.snap.mundos.B;
    var filas = ids.map(function (id) {
      var a = mb.accesos.filter(function (x) { return x.acceso_id === id; })[0] || {};
      var e = F.estadoDe(a.semaforo, a.estado !== "cerrado");
      var p = (estado.pron || {})[id];
      var calor = p ? p.franjas.filter(function (f) { var x = new Date(f.inicio).getTime(); return x >= ini && x < fin; }).map(function (f) {
        var x = new Date(f.inicio).getTime(), v = f.espera_min;
        return el("span", { title: F.hora(f.inicio) + " · " + F.num(v) + " min", style: { left: pct(x) + "%", width: (30 * 60000 / (fin - ini) * 100) + "%", background: v < 30 ? "#3FAE7A" : v <= 90 ? "#E9B03B" : "#D9574B" } });
      }) : [];
      var mias = activas.filter(function (c) { return c.acceso_id === id; }).sort(function (x, y) { return x.ventana_inicio < y.ventana_inicio ? -1 : 1; });
      var carriles = [];
      var bloques = mias.map(function (c) {
        var x0 = new Date(c.ventana_inicio).getTime(), x1 = new Date(c.ventana_fin).getTime();
        if (x1 < ini || x0 > fin) return null;
        var carril = 0; while (carriles[carril] && carriles[carril] > x0) carril++;
        carriles[carril] = Math.max(x1, x0 + 50 * 60000); // el bloque mide al menos ~1 h en pantalla
        var ec = estadoCita(c), tr = t[c.transportista_id] || {};
        var tipo = c.estado === "en_ruta" ? "ruta" : c.origen !== "web" ? "chofer" : "conf";
        return el("button", { type: "button", class: "bloque-cita bloque-cita--" + tipo,
          style: { left: Math.max(0, pct(x0)) + "%", width: Math.max(8, pct(x1) - pct(x0)) + "%", top: (carril * 34 + 4) + "px" },
          "aria-label": F.hora(c.ventana_inicio) + ", " + (tr.alias || "Transportista") + ", " + ec.texto,
          title: F.hora(c.ventana_inicio) + " · " + (tr.alias || "") + " · " + ec.texto,
          onclick: function () { resaltarCita(c.id); } }, F.hora(c.ventana_inicio));
      });
      var alto = Math.max(1, carriles.length) * 34 + 8;
      return el("div", { class: "linea-tiempo__fila" }, [
        el("div", { class: "linea-tiempo__nombre" }, [F.simbolo(e, 18), el("span", {}, nombreCaseta(id))]),
        el("div", { class: "linea-tiempo__pista" }, [
          el("div", { class: "linea-tiempo__calor", role: "img", "aria-label": "Espera pronosticada en " + nombreCaseta(id) }, calor),
          el("div", { class: "linea-tiempo__citas", style: { height: alto + "px" } }, [el("div", { class: "linea-tiempo__ahora", style: { left: pct(ahora) + "%" }, "aria-hidden": "true" })].concat(bloques))
        ])
      ]);
    });
    F.reemplazar(caja, [el("div", { class: "linea-tiempo__in" }, [el("div", { class: "linea-tiempo__horas", "aria-hidden": "true" }, horas)].concat(filas))]);
  }

  function resaltarCita(id) {
    estado.citaResaltada = id;
    if (estado.filtroCitas !== "activas") { estado.filtroCitas = "activas"; [].forEach.call($("filtros").children, function (b) { b.setAttribute("aria-pressed", String(b.dataset.id === "activas")); }); }
    renderCitas();
    var fila = document.querySelector('[data-cita="' + id + '"]');
    if (fila) { fila.scrollIntoView({ behavior: "smooth", block: "center" }); fila.focus({ preventScroll: true }); }
  }

  async function cargarPronostico() {
    try { var lista = await F.api("/api/pronostico"); estado.pron = {}; lista.forEach(function (p) { estado.pron[p.acceso_id] = p; }); }
    catch (e) { estado.pron = {}; }
    renderLineaTiempo();
  }

  async function cancelar(c) {
    try { await F.api("/api/citas/" + c.id, { method: "DELETE" }); await cargarCitas(); }
    catch (e) { $("estado-cita").textContent = "No se pudo cancelar: " + e.message; }
  }

  function selectorTransportistas() {
    var sel = $("cita-transportista");
    if (!sel) return;
    var previo = sel.value, lista = estado.transportistas;
    F.reemplazar(sel, lista.length ? lista.map(function (t) {
      return el("option", { value: String(t.id) }, t.alias + (t.placas ? " · " + t.placas : "") + (t.telegram ? "" : " (sin Telegram)"));
    }) : [el("option", { value: "" }, "Sin transportistas registrados")]);
    if (previo && lista.some(function (t) { return String(t.id) === previo; })) sel.value = previo;
  }

  function sumarDias(fecha, n) { var p = fecha.split("-").map(Number); return new Date(Date.UTC(p[0], p[1] - 1, p[2] + n)).toISOString().slice(0, 10); }
  function isoSimulado(hm, dias) { var ts = estado.snap.ts_sim; return sumarDias(F.fecha(ts), dias || 0) + "T" + hm + ":00" + F.zonaHoraria(ts); }

  async function buscarHorarios(ev) {
    ev.preventDefault();
    if (!estado.snap) { $("estado-cita").textContent = "Esperando la simulación…"; return; }
    if (!$("cita-transportista").value) { $("estado-cita").textContent = "Primero da de alta a un transportista."; return; }
    var desde = $("cita-desde").value, hasta = $("cita-hasta").value;
    var d = isoSimulado(desde, 0), h = isoSimulado(hasta, hasta <= desde ? 1 : 0);
    if (new Date(d) < new Date(estado.snap.ts_sim)) { d = isoSimulado(desde, 1); h = isoSimulado(hasta, hasta <= desde ? 2 : 1); }
    $("estado-cita").textContent = "Buscando horarios…";
    try {
      var cuerpo = { desde: d, hasta: h, tipo_carga: $("cita-carga").value };
      if ($("cita-caseta").value) cuerpo.acceso_id = $("cita-caseta").value;
      var sug = await F.api("/api/citas/sugerencias", { method: "POST", json: cuerpo });
      $("estado-cita").textContent = sug.length ? "" : "No hay horarios disponibles en esa ventana.";
      F.reemplazar($("sugerencias"), sug.map(function (s) {
        return el("div", { class: "sugerencia" }, [
          el("div", { style: { display: "flex", flexDirection: "column", gap: "4px" } }, [
            el("span", { class: "cifra", style: { fontSize: "22px" } }, F.hora(s.inicio)),
            el("span", { class: "tenue", style: { fontSize: "13px" } }, nombreCaseta(s.acceso_id)),
            chip(s.semaforo, "~" + F.num(s.espera_min_est) + " min")
          ]),
          el("button", { type: "button", class: "btn", onclick: function () { asignar(s); } }, "Asignar")
        ]);
      }));
    } catch (e) { $("estado-cita").textContent = "No se pudieron obtener horarios: " + e.message; }
  }

  async function asignar(s) {
    var tid = Number($("cita-transportista").value), t = porId(estado.transportistas)[tid] || {};
    try {
      var c = await F.api("/api/citas", { method: "POST", json: { transportista_id: tid, acceso_id: s.acceso_id,
        ventana_inicio: s.inicio, ventana_fin: s.fin, tipo_carga: $("cita-carga").value, origen: "web" } });
      $("estado-cita").textContent = "Cita asignada a " + (t.alias || "el transportista") + " a las " + F.hora(c.ventana_inicio) + " en " + nombreCaseta(c.acceso_id) +
        (t.telegram ? ". Se le avisó por Telegram." : ". Aún no está conectado a Telegram: compártele la invitación.");
      F.reemplazar($("sugerencias"), []);
      await cargarTransportistas(); await cargarCitas(); cargarAvisos();
    } catch (e) { $("estado-cita").textContent = "No se pudo asignar: " + e.message; }
  }

  // ───────────── Transportistas ─────────────
  function renderTransportistas() {
    if (!$("tabla-trans")) return;
    var lista = estado.transportistas, sinBot = lista.filter(function (t) { return !t.telegram; });
    var botones = $("filtro-trans").children;
    if (botones.length) { botones[0].textContent = "Todos · " + F.num(lista.length); botones[1].textContent = "Sin Telegram · " + F.num(sinBot.length); }
    var vista = estado.filtroTrans === "sin_bot" ? sinBot : lista;
    F.reemplazar($("tabla-trans"), vista.length ? vista.map(function (t) {
      return el("tr", {}, [
        el("td", { style: { fontWeight: "700" } }, t.alias), el("td", { class: "cifra" }, t.placas || "—"),
        el("td", {}, t.telefono_fin ? "…" + t.telefono_fin : "—"),
        el("td", {}, t.telegram ? chip("verde", "Conectado") : chip("amarillo", "Invitación pendiente")),
        el("td", {}, F.num(t.citas_activas)), el("td", {}, t.proxima_cita ? F.hora(t.proxima_cita) : "—"),
        el("td", { style: { textAlign: "right" } }, el("a", { class: "btn btn--sec btn--chico", href: "/agencia/citas/#asignar" }, "Asignar cita"))
      ]);
    }) : [el("tr", {}, el("td", { colspan: "7", class: "vacio" }, lista.length ? "Todos están conectados a Telegram." : "Aún no hay transportistas. Da de alta al primero."))]);
  }

  function renderSolicitudes() {
    if (!$("tabla-solicitudes")) return;
    var lista = estado.solicitudes;
    $("caja-solicitudes").classList.toggle("oculto", !lista.length && !$("estado-solicitudes").textContent);
    F.reemplazar($("tabla-solicitudes"), lista.length ? lista.map(function (s) {
      var placas = el("input", { "aria-label": "Placas de " + s.nombre, placeholder: "XKL-45-21", autocomplete: "off", style: { maxWidth: "130px" } });
      return el("tr", {}, [
        el("td", { style: { fontWeight: "700" } }, s.nombre), el("td", {}, "…" + s.telefono_fin),
        el("td", {}, F.hora(s.creada_en)), el("td", {}, placas),
        el("td", { style: { textAlign: "right", whiteSpace: "nowrap" } }, [
          el("button", { type: "button", class: "btn btn--chico", onclick: function () { resolverSolicitud(s, "aprobar", placas.value); } }, "Aprobar"),
          " ",
          el("button", { type: "button", class: "btn btn--sec btn--chico", onclick: function () { resolverSolicitud(s, "rechazar"); } }, "Rechazar")
        ])
      ]);
    }) : [el("tr", {}, el("td", { colspan: "5", class: "vacio" }, "Sin solicitudes pendientes."))]);
  }

  async function resolverSolicitud(s, accion, placas) {
    var ruta = "/api/agencias/" + encodeURIComponent(estado.agencia) + "/solicitudes/" + s.id + "/" + accion;
    try {
      await F.api(ruta, { method: "POST", json: accion === "aprobar" ? { placas: (placas || "").trim() || null } : {} });
      $("estado-solicitudes").textContent = accion === "aprobar"
        ? s.nombre + " quedó dado de alta y ya está conectado al bot; le avisamos por Telegram."
        : "Solicitud de " + s.nombre + " rechazada; le avisamos por Telegram.";
      await cargarTransportistas();
    } catch (e) { $("estado-solicitudes").textContent = "No se pudo " + accion + ": " + e.message; }
  }

  async function darDeAlta(ev) {
    ev.preventDefault();
    try {
      var t = await F.api("/api/agencias/" + encodeURIComponent(estado.agencia) + "/transportistas", { method: "POST",
        json: { alias: $("alta-nombre").value.trim(), telefono: $("alta-tel").value, placas: $("alta-placas").value || null } });
      $("estado-alta").textContent = t.alias + " quedó dado de alta. Compártele la invitación para que se conecte a Telegram.";
      $("form-alta").reset();
      await cargarTransportistas();
    } catch (e) { $("estado-alta").textContent = "No se pudo dar de alta: " + e.message; }
  }

  function renderInvitacion() {
    if (!$("invitacion")) return;
    if (!estado.bot) { F.reemplazar($("invitacion"), [el("p", { class: "tenue", style: { margin: "0" } }, "El bot de Telegram no está configurado en el servidor.")]); return; }
    var url = estado.bot.enlace + "?start=" + encodeURIComponent(estado.agencia), hijos = [];
    if (window.qrcode) {
      var qr = window.qrcode(0, "M"); qr.addData(url); qr.make();
      var caja = el("div", { class: "qr", role: "img", "aria-label": "Código QR de la invitación al bot" });
      caja.innerHTML = qr.createSvgTag(4, 0); // SVG generado localmente a partir de la URL del propio bot
      hijos.push(caja);
    }
    var copiar = el("button", { type: "button", class: "btn btn--suave btn--chico", style: { alignSelf: "flex-start" }, onclick: function () {
      try { navigator.clipboard.writeText(url).then(function () { copiar.textContent = "Enlace copiado"; }); } catch (e) { copiar.textContent = "Copia el enlace manualmente"; }
    } }, "Copiar enlace");
    hijos.push(el("div", { style: { display: "flex", flexDirection: "column", gap: "8px", minWidth: "0" } }, [
      el("span", { class: "tenue", style: { fontSize: "13px", wordBreak: "break-all" } }, url), copiar,
      el("a", { href: url, target: "_blank", rel: "noopener", style: { fontSize: "14px", fontWeight: "700" } }, "Abrir " + estado.bot.usuario)
    ]));
    F.reemplazar($("invitacion"), hijos);
  }

  // ───────────── Avisos ─────────────
  var FILTROS_AVISOS = [["todos", "Todos"], ["cita_rechazada", "Respuestas de choferes"], ["saturacion", "Contingencias"], ["cita_asignada", "Citas enviadas"], ["turno_30min", "Recordatorios"]];

  function renderAvisos() {
    if (!$("lista-avisos")) return;
    var t = porId(estado.transportistas);
    var grupo = GRUPO_AVISOS[estado.filtroAvisos] || [estado.filtroAvisos];
    var lista = estado.avisos.filter(function (a) { return estado.filtroAvisos === "todos" || grupo.indexOf(a.tipo) >= 0; });
    F.reemplazar($("lista-avisos"), lista.length ? lista.map(function (a) {
      var quien = (t[a.transportista_id] || {}).alias || "Transportista #" + a.transportista_id;
      var accion = REASIGNAR.indexOf(a.tipo) >= 0 ? ["Reasignar", "/agencia/citas/#asignar"] : ["Ver citas", "/agencia/citas/"];
      return el("li", {}, [
        el("span", { class: "avisos__hora" }, F.hora(a.creado_en)),
        el("div", { class: "avisos__texto" }, [
          el("div", { style: { display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "center" } }, [el("strong", {}, quien), chip(TONO_AVISO[a.tipo] || "azul", TIPOS_AVISO[a.tipo] || a.tipo)]),
          el("span", { style: { fontSize: "14px", whiteSpace: "pre-line", lineHeight: "1.45" } }, a.mensaje.replace(/\*/g, ""))
        ]),
        el("div", { class: "avisos__accion" }, [
          el("span", { class: "tenue", style: { fontSize: "13px" } }, a.cita_id ? "Cita #" + a.cita_id : ""),
          el("a", { class: "btn btn--suave btn--chico", href: accion[1] }, accion[0])
        ])
      ]);
    }) : [el("li", { class: "vacio" }, "Sin avisos con este filtro.")]);
  }

  // ───────────── Carga de datos ─────────────
  async function cargarTransportistas() {
    var base = "/api/agencias/" + encodeURIComponent(estado.agencia);
    var res = await Promise.all([F.api(base + "/transportistas").catch(function () { return []; }),
      F.api(base + "/solicitudes").catch(function () { return []; })]);
    estado.transportistas = res[0]; estado.solicitudes = res[1];
    selectorTransportistas(); renderSolicitudes(); renderTodo();
  }
  async function cargarCitas() {
    try { estado.citas = await F.api("/api/citas?limite=300" + q("&")); } catch (e) { estado.citas = []; }
    renderTodo();
  }
  async function cargarAvisos() {
    try { estado.avisos = await F.api("/api/avisos?limite=50" + q("&")); } catch (e) { estado.avisos = []; }
    renderTodo();
  }
  function renderTodo() { contadores(); renderResumen(); renderCitas(); renderAvisos(); renderTransportistas(); renderFlota(); }

  function botonesFiltro(id, opciones, actual, alElegir) {
    var cont = $(id);
    if (!cont) return;
    F.reemplazar(cont, opciones.map(function (o) {
      return el("button", { type: "button", "data-id": o[0], "data-texto": o[1], "aria-pressed": String(o[0] === actual), onclick: function () {
        [].forEach.call(cont.children, function (b) { b.setAttribute("aria-pressed", String(b.dataset.id === o[0])); });
        alElegir(o[0]);
      } }, o[1]);
    }));
  }

  function elegirAgencia(id) {
    estado.agencia = id; estado.seleccion = null; estado.historia = [];
    if ($("estado-solicitudes")) $("estado-solicitudes").textContent = "";
    try { localStorage.setItem("fluport.agencia", id); } catch (e) { /* sin almacenamiento */ }
    if (estado.mapa) { Object.keys(estado.mapa.camiones).forEach(function (k) { estado.mapa.mapa.removeLayer(estado.mapa.camiones[k]); }); estado.mapa.camiones = {}; }
    renderInvitacion();
    cargarTransportistas().then(function () { cargarCitas(); cargarAvisos(); });
  }

  async function iniciar() {
    var res = await Promise.all([F.api("/api/accesos"), F.api("/api/agencias"),
      $("mapa") ? F.api("/api/accesos/rutas") : Promise.resolve({ features: [] })]);
    res[0].forEach(function (a) { estado.accesos[a.id] = a; if ($("cita-caseta")) $("cita-caseta").appendChild(el("option", { value: a.id }, a.nombre)); });
    res[2].features.filter(function (f) { return f.properties.tipo === "ruta"; }).forEach(function (f) {
      var r = F.prepararRuta(f.geometry.coordinates.map(function (c) { return [c[1], c[0]]; }));
      r.acceso = f.properties.acceso_id;
      estado.rutas[f.properties.ruta_id] = r;
    });
    estado.agencias = res[1];
    if (!estado.agencias.length) throw new Error("no hay agencias registradas");
    var pedida = new URLSearchParams(location.search).get("agencia"), guardada = null;
    try { guardada = localStorage.getItem("fluport.agencia"); } catch (e) { /* sin almacenamiento */ }
    var ids = estado.agencias.map(function (a) { return a.id; });
    var inicial = [pedida, guardada].filter(function (x) { return x && ids.indexOf(x) >= 0; })[0] || ids[0];
    F.reemplazar($("agencia"), estado.agencias.map(function (a) { return el("option", { value: a.id }, a.nombre); }));
    $("agencia").value = inicial;
    if (estado.agencias.length === 1) { // una sola agencia: se muestra su nombre en lugar del selector
      $("agencia").classList.add("oculto");
      $("agencia").parentNode.appendChild(el("strong", { class: "ag-menu__nombre" }, estado.agencias[0].nombre));
    }
    $("agencia").addEventListener("change", function () { elegirAgencia(this.value); });
    $("btn-menu").addEventListener("click", function () {
      var menu = document.querySelector(".ag-menu"), abierto = !menu.classList.contains("ag-menu--abierto");
      menu.classList.toggle("ag-menu--abierto", abierto);
      this.setAttribute("aria-expanded", String(abierto));
      this.setAttribute("aria-label", abierto ? "Cerrar menú" : "Abrir menú");
    });
    botonesFiltro("filtros", FILTROS_CITAS, estado.filtroCitas, function (v) { estado.filtroCitas = v; renderCitas(); });
    botonesFiltro("filtro-flota", [["todos", "Todos"], ["en_ruta", "En ruta"], ["en_fila", "En fila"], ["dentro", "Dentro"], ["con_cita", "Con cita"]], estado.filtroFlota, function (v) { estado.filtroFlota = v; renderFlota(); });
    botonesFiltro("filtro-trans", [["todos", "Todos"], ["sin_bot", "Sin Telegram"]], estado.filtroTrans, function (v) { estado.filtroTrans = v; renderTransportistas(); });
    botonesFiltro("filtro-avisos", FILTROS_AVISOS, estado.filtroAvisos, function (v) { estado.filtroAvisos = v; renderAvisos(); });
    if ($("buscar-camion")) $("buscar-camion").addEventListener("input", function () { estado.busqueda = this.value.trim(); renderFlota(); });
    if ($("form-cita")) { $("form-cita").addEventListener("submit", buscarHorarios); $("cita-desde").value = "09:00"; $("cita-hasta").value = "15:00"; }
    if ($("form-alta")) $("form-alta").addEventListener("submit", darDeAlta);
    if ($("invitacion")) { try { estado.bot = await F.api("/api/telegram/enlace"); } catch (e) { estado.bot = null; } }
    [].forEach.call(document.querySelectorAll("[data-simbolo]"), function (n) { n.appendChild(F.simbolo(n.dataset.simbolo, 18)); });
    iniciarPanelSimulacion();
    crearMapa();
    elegirAgencia(inicial);
    if ($("linea-tiempo")) { cargarPronostico(); setInterval(cargarPronostico, 60000); }
    F.conectarSimulacion(function (m) {
      if (m.tipo === "snapshot") {
        estado.snap = m.data; reloj(m.data); renderResumen(); renderFlota();
        if ($("linea-tiempo") && Date.now() - (estado.lineaEn || 0) > 5000) { estado.lineaEn = Date.now(); renderLineaTiempo(); }
      }
      else if (m.tipo === "aviso") { cargarAvisos(); cargarCitas(); }
    });
    setInterval(cargarCitas, 10000);
    setInterval(cargarTransportistas, 15000);
    setInterval(cargarAvisos, 15000);
  }

  iniciar().catch(function (e) {
    document.querySelector(".ag-main").prepend(el("p", { class: "tarjeta", role: "alert" }, "No se pudo conectar con el servidor: " + e.message));
  });
})();
