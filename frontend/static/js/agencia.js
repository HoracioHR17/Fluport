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
  var TIPOS_AVISO = { turno_30min: "Recordatorio", saturacion: "Contingencia", cita_asignada: "Cita asignada", cita_rechazada: "Respuesta del chofer" };
  var TONO_AVISO = { turno_30min: "verde", saturacion: "oscuro", cita_asignada: "azul", cita_rechazada: "rojo" };
  var ACTIVAS = { agendada: true, en_ruta: true };

  var estado = { agencia: null, agencias: [], accesos: {}, rutas: {}, snap: null, mapa: null, bot: null,
    transportistas: [], citas: [], avisos: [], filtroCitas: "activas", filtroFlota: "todos", filtroTrans: "todos",
    filtroAvisos: "todos", busqueda: "", seleccion: null };

  // ───────────── Utilidades ─────────────
  function nombreCaseta(id) { return ((estado.accesos[id] || {}).nombre || id || "").replace("Caseta ", ""); }
  function porId(lista) { var m = {}; lista.forEach(function (x) { m[x.id] = x; }); return m; }
  function q(sep) { return sep + "agencia_id=" + encodeURIComponent(estado.agencia); }
  function chip(tono, texto) { return el("span", { class: "chip chip--" + tono }, texto); }
  function sinConfirmar(c) { return c.estado === "agendada" && c.origen === "web" && !c.confirmada_en; }
  function plural(n, uno, varios) { return F.num(n) + " " + (n === 1 ? uno : varios); }

  function estadoCita(c) {
    if (c.estado === "agendada") {
      if (c.origen !== "web") return { texto: "Pedida por el chofer", tono: "azul" };
      return c.confirmada_en ? { texto: "Confirmada", tono: "verde" } : { texto: "Sin confirmar", tono: "amarillo" };
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
    var pend = estado.citas.filter(sinConfirmar).length;
    var rech = estado.avisos.filter(function (a) { return a.tipo === "cita_rechazada"; }).length;
    var sinBot = estado.transportistas.filter(function (t) { return !t.telegram; }).length;
    [["citas", pend], ["avisos", rech], ["transportistas", sinBot]].forEach(function (p) {
      var n = document.querySelector('[data-contador="' + p[0] + '"]');
      if (n) { n.textContent = p[1]; n.classList.toggle("oculto", !p[1]); }
    });
  }

  function reloj(s) {
    $("reloj").textContent = F.fecha(s.ts_sim) + " · " + F.hora(s.ts_sim) + " (hora simulada)" + (s.clima === "norte" ? " · norte activo" : "");
    $("etiqueta").textContent = s.etiqueta || "SIMULACIÓN";
  }

  // ───────────── Resumen ─────────────
  function renderResumen() {
    if (!$("kpis")) return;
    var s = estado.snap, f = s ? ((s.mundos.B.flota || {})[estado.agencia] || {}) : {};
    var activas = estado.citas.filter(function (c) { return ACTIVAS[c.estado]; });
    var conf = activas.filter(function (c) { return c.confirmada_en; }).length;
    var conectados = estado.transportistas.filter(function (t) { return t.telegram; }).length;
    var kpis = [
      ["En ruta", F.num(f.en_ruta), "camiones hacia el puerto", "/agencia/flota/"],
      ["En fila", F.num(f.en_fila), "esperando en caseta", "/agencia/flota/"],
      ["Citas activas", F.num(activas.length), F.num(conf) + " confirmadas", "/agencia/citas/"],
      ["Sin confirmar", F.num(estado.citas.filter(sinConfirmar).length), "esperan el SÍ del chofer", "/agencia/citas/"],
      ["Espera promedio", F.num(f.espera_prom_min) + " min", "de tu flota", "/agencia/flota/"],
      ["Conectados a Telegram", F.num(conectados) + " / " + F.num(estado.transportistas.length), "transportistas", "/agencia/transportistas/"]
    ];
    F.reemplazar($("kpis"), kpis.map(function (k) {
      return el("a", { class: "kpi", href: k[3] }, [el("span", {}, k[0]), el("span", { class: "cifra" }, k[1]), el("span", {}, k[2])]);
    }));
    if (s) renderCasetas(s.mundos.B);
    var rech = estado.avisos.filter(function (a) { return a.tipo === "cita_rechazada"; }).length;
    var sinBot = estado.transportistas.length - conectados;
    var mods = [
      ["Flota en vivo", "Mapa y lista de tus camiones: en ruta, en fila, en revisión o dentro.", plural((f.en_ruta || 0) + (f.en_fila || 0) + (f.en_revision || 0) + (f.dentro || 0), "camión activo", "camiones activos"), "azul", "/agencia/flota/"],
      ["Citas", "Asigna citas con el pronóstico de espera y sigue su confirmación.", plural(estado.citas.filter(sinConfirmar).length, "sin confirmar", "sin confirmar"), estado.citas.filter(sinConfirmar).length ? "amarillo" : "verde", "/agencia/citas/"],
      ["Transportistas", "Alta de choferes, placas e invitación al bot de Telegram.", sinBot ? plural(sinBot, "sin conectar", "sin conectar") : "Todos conectados", sinBot ? "amarillo" : "verde", "/agencia/transportistas/"],
      ["Avisos", "Mensajes enviados a tus choferes y sus respuestas.", rech ? plural(rech, "rechazo", "rechazos") : plural(estado.avisos.length, "aviso", "avisos"), rech ? "rojo" : "azul", "/agencia/avisos/"]
    ];
    F.reemplazar($("modulos"), mods.map(function (m) {
      return el("a", { class: "modulo", href: m[4] }, [
        el("span", { class: "modulo__cab" }, [m[0], el("span", { "aria-hidden": "true" }, "→")]),
        el("p", {}, m[1]), chip(m[3], m[2])
      ]);
    }));
    renderAtencion();
  }

  function renderCasetas(mb) {
    var enFila = {};
    camionesAgencia().forEach(function (c) { if (c.estado === "en_fila") enFila[c.acceso_id] = (enFila[c.acceso_id] || 0) + 1; });
    F.reemplazar($("casetas"), mb.accesos.map(function (a) {
      var cerrada = a.estado === "cerrado", n = enFila[a.acceso_id] || 0;
      return el("div", { class: "caseta" }, [
        el("div", { style: { display: "flex", flexDirection: "column", gap: "2px" } }, [
          el("strong", {}, nombreCaseta(a.acceso_id)),
          el("span", { class: "tenue", style: { fontSize: "13px" } }, n ? plural(n, "camión tuyo en fila", "camiones tuyos en fila") : "Ninguno de tus camiones en fila")
        ]),
        el("div", { class: "caseta__der" }, [
          el("span", { class: "cifra" }, cerrada ? "—" : F.num(a.espera_min) + " min"),
          cerrada ? chip("oscuro", "Cerrada") : chip(a.semaforo, F.SEMAFORO[a.semaforo].simbolo + " " + F.SEMAFORO[a.semaforo].etiqueta)
        ])
      ]);
    }));
  }

  function renderAtencion() {
    if (!$("atencion")) return;
    var items = [], cerradas = {};
    if (estado.snap) estado.snap.mundos.B.accesos.forEach(function (a) { if (a.estado === "cerrado") cerradas[a.acceso_id] = true; });
    var enCerrada = estado.citas.filter(function (c) { return c.estado === "agendada" && cerradas[c.acceso_id]; });
    if (enCerrada.length) items.push(["▲", "#FBEAE8", plural(enCerrada.length, "cita en caseta cerrada", "citas en caseta cerrada"), "Fluport avisó a los transportistas con una alternativa.", "Revisar citas", "/agencia/citas/"]);
    estado.avisos.filter(function (a) { return a.tipo === "cita_rechazada"; }).slice(0, 2).forEach(function (r) {
      items.push(["!", "#FBEAE8", "Un transportista no puede asistir", r.mensaje, "Reasignar", "/agencia/citas/#asignar"]);
    });
    var sc = estado.citas.filter(sinConfirmar).length;
    if (sc) items.push(["?", "#FCF3DF", plural(sc, "cita sin confirmar", "citas sin confirmar"), "El transportista aún no responde SÍ en Telegram.", "Ver cuáles", "/agencia/citas/"]);
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
  function prepararRuta(coords) {
    var acum = [0];
    for (var i = 1; i < coords.length; i++) {
      var dy = coords[i][0] - coords[i - 1][0], dx = coords[i][1] - coords[i - 1][1];
      acum.push(acum[i - 1] + Math.sqrt(dx * dx + dy * dy));
    }
    return { coords: coords, acum: acum, total: acum[acum.length - 1] || 1 };
  }
  function posicion(r, p) {
    var d = Math.max(0, Math.min(1, p)) * r.total;
    for (var i = 1; i < r.acum.length; i++) {
      if (d <= r.acum[i]) {
        var t = (d - r.acum[i - 1]) / ((r.acum[i] - r.acum[i - 1]) || 1), a = r.coords[i - 1], b = r.coords[i];
        return [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
      }
    }
    return r.coords[r.coords.length - 1];
  }
  function iconoCaseta(id, a) {
    var cerrada = a && a.estado === "cerrado";
    var texto = (cerrada ? "" : (a && a.semaforo === "rojo" ? "▲ " : "● ")) + nombreCaseta(id) + " · " + (cerrada ? "cerrada" : F.num(a ? a.espera_min : 0) + " min");
    return L.divIcon({ html: el("span", { class: "marcador-caseta" + (cerrada ? " marcador-caseta--cerrada" : "") }, texto).outerHTML, className: "", iconSize: null, iconAnchor: [14, 14] });
  }
  function crearMapa() {
    if (!$("mapa")) return;
    if (!window.L) { $("mapa").appendChild(el("p", { style: { padding: "16px" } }, "No se pudo cargar el mapa.")); return; }
    var mapa = L.map($("mapa"));
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; colaboradores de OpenStreetMap" }).addTo(mapa);
    var lim = [];
    Object.keys(estado.rutas).forEach(function (id) { L.polyline(estado.rutas[id].coords, { color: "#0A2238", opacity: 0.35, weight: 5 }).addTo(mapa); lim = lim.concat(estado.rutas[id].coords); });
    if (lim.length) mapa.fitBounds(lim, { padding: [30, 30] });
    var casetas = {};
    Object.keys(estado.accesos).forEach(function (id) { var a = estado.accesos[id]; casetas[id] = L.marker([a.lat, a.lon], { icon: iconoCaseta(id, null), keyboard: false }).addTo(mapa); });
    estado.mapa = { mapa: mapa, camiones: {}, casetas: casetas };
  }
  function estiloCamion(c, sel) {
    if (sel) return { radius: 10, color: "#0A2238", weight: 4, fillColor: "#E9B03B", fillOpacity: 1 };
    if (c.cita_id) return { radius: 8, color: "#3FAE7A", weight: 4, fillColor: "#FFFFFF", fillOpacity: 1 };
    if (c.estado === "en_fila") return { radius: 5, color: "#9A6B0B", weight: 1, fillColor: "#E9B03B", fillOpacity: 1 };
    if (c.estado === "en_revision") return { radius: 5, color: "#1E6B47", weight: 1, fillColor: "#3FAE7A", fillOpacity: 1 };
    if (c.estado === "saliendo") return { radius: 3, color: "#4A5B6B", weight: 1, fillColor: "#A9B8C6", fillOpacity: 0.9 };
    return { radius: 4, color: "#0A2238", weight: 1, fillColor: "#0A2238", fillOpacity: 0.9 };
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
        var r = estado.rutas[c.ruta_id];
        if (!r) return;
        var p = c.progreso;
        if (c.estado === "en_fila") { fila[c.acceso_id] = (fila[c.acceso_id] || 0) + 1; p = Math.max(0.55, 1 - 0.006 * fila[c.acceso_id]); }
        var pos = posicion(r, p), st = estiloCamion(c, c.id === estado.seleccion);
        vistos[c.id] = true;
        if (m.camiones[c.id]) { m.camiones[c.id].setLatLng(pos); m.camiones[c.id].setStyle(st); }
        else m.camiones[c.id] = L.circleMarker(pos, Object.assign({ interactive: false }, st)).addTo(m.mapa);
      });
      Object.keys(m.camiones).forEach(function (id) { if (!vistos[id]) { m.mapa.removeLayer(m.camiones[id]); delete m.camiones[id]; } });
      mb.accesos.forEach(function (a) { if (m.casetas[a.acceso_id]) m.casetas[a.acceso_id].setIcon(iconoCaseta(a.acceso_id, a)); });
    }
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
  var FILTROS_CITAS = [["activas", "Activas"], ["sin_confirmar", "Sin confirmar"], ["choferes", "Pedidas por choferes"], ["historial", "Historial"]];

  function renderCitas() {
    if (!$("tabla-citas")) return;
    var t = porId(estado.transportistas);
    var pasa = {
      activas: function (c) { return ACTIVAS[c.estado]; }, sin_confirmar: sinConfirmar,
      choferes: function (c) { return c.origen !== "web"; }, historial: function (c) { return !ACTIVAS[c.estado]; }
    };
    [].forEach.call($("filtros").children, function (b) { b.textContent = b.dataset.texto + " · " + F.num(estado.citas.filter(pasa[b.dataset.id]).length); });
    var lista = estado.citas.filter(pasa[estado.filtroCitas]);
    var activas = estado.citas.filter(pasa.activas);
    $("resumen-citas").textContent = plural(activas.length, "cita activa", "citas activas") + " · " + F.num(activas.filter(function (c) { return c.confirmada_en; }).length) + " confirmadas";
    F.reemplazar($("tabla-citas"), lista.length ? lista.map(function (c) {
      var e = estadoCita(c), tr = t[c.transportista_id] || {};
      return el("tr", { class: sinConfirmar(c) ? "resaltada" : "" }, [
        el("td", { class: "cifra" }, F.hora(c.ventana_inicio)),
        el("td", {}, tr.alias || "Transportista #" + c.transportista_id),
        el("td", { class: "cifra" }, tr.placas || "—"),
        el("td", {}, nombreCaseta(c.acceso_id)),
        el("td", {}, c.espera_estimada_min === null ? "—" : "~" + F.num(c.espera_estimada_min) + " min"),
        el("td", {}, chip(e.tono, e.texto)),
        el("td", { style: { textAlign: "right" } }, c.estado === "agendada"
          ? el("button", { type: "button", class: "btn btn--sec btn--chico", onclick: function () { cancelar(c); } }, "Cancelar") : null)
      ]);
    }) : [el("tr", {}, el("td", { colspan: "7", class: "vacio" }, "No hay citas con este filtro."))]);
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
        (t.telegram ? ". Se le envió por Telegram para que la confirme." : ". Aún no está conectado a Telegram: compártele la invitación.");
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
  var FILTROS_AVISOS = [["todos", "Todos"], ["cita_rechazada", "Respuestas de choferes"], ["saturacion", "Contingencias"], ["cita_asignada", "Citas asignadas"], ["turno_30min", "Recordatorios"]];

  function renderAvisos() {
    if (!$("lista-avisos")) return;
    var t = porId(estado.transportistas);
    var lista = estado.avisos.filter(function (a) { return estado.filtroAvisos === "todos" || a.tipo === estado.filtroAvisos; });
    F.reemplazar($("lista-avisos"), lista.length ? lista.map(function (a) {
      var quien = (t[a.transportista_id] || {}).alias || "Transportista #" + a.transportista_id;
      var accion = a.tipo === "cita_rechazada" ? ["Reasignar", "/agencia/citas/#asignar"] : ["Ver citas", "/agencia/citas/"];
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
    try { estado.transportistas = await F.api("/api/agencias/" + encodeURIComponent(estado.agencia) + "/transportistas"); }
    catch (e) { estado.transportistas = []; }
    selectorTransportistas(); renderTransportistas(); renderTodo();
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
    estado.agencia = id; estado.seleccion = null;
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
      estado.rutas[f.properties.ruta_id] = prepararRuta(f.geometry.coordinates.map(function (c) { return [c[1], c[0]]; }));
    });
    estado.agencias = res[1];
    if (!estado.agencias.length) throw new Error("no hay agencias registradas");
    var pedida = new URLSearchParams(location.search).get("agencia"), guardada = null;
    try { guardada = localStorage.getItem("fluport.agencia"); } catch (e) { /* sin almacenamiento */ }
    var ids = estado.agencias.map(function (a) { return a.id; });
    var inicial = [pedida, guardada].filter(function (x) { return x && ids.indexOf(x) >= 0; })[0] || ids[0];
    F.reemplazar($("agencia"), estado.agencias.map(function (a) { return el("option", { value: a.id }, a.nombre); }));
    $("agencia").value = inicial;
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
    crearMapa();
    elegirAgencia(inicial);
    F.conectarSimulacion(function (m) {
      if (m.tipo === "snapshot") { estado.snap = m.data; reloj(m.data); renderResumen(); renderFlota(); }
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
