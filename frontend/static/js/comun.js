/* Fluport · utilidades compartidas por las pantallas (sin dependencias). */
(function () {
  "use strict";

  var SEMAFORO = {
    verde: { simbolo: "●", etiqueta: "Fluye", color: "#3FAE7A" },
    amarillo: { simbolo: "●", etiqueta: "Lento", color: "#E9B03B" },
    rojo: { simbolo: "▲", etiqueta: "Saturado", color: "#D9574B" }
  };

  /** Crea un elemento: el("div", {class: "x", onclick: fn}, [hijos o texto]). El texto nunca se interpreta como HTML. */
  function el(tag, attrs, hijos) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k.slice(0, 2) === "on" && typeof v === "function") n.addEventListener(k.slice(2), v);
      else if (k === "style" && typeof v === "object") Object.assign(n.style, v);
      else n.setAttribute(k, v === true ? "" : String(v));
    });
    [].concat(hijos === undefined ? [] : hijos).forEach(function (h) {
      if (h === null || h === undefined || h === false) return;
      n.appendChild(typeof h === "object" ? h : document.createTextNode(String(h)));
    });
    return n;
  }

  function reemplazar(nodo, hijos) {
    while (nodo.firstChild) nodo.removeChild(nodo.firstChild);
    [].concat(hijos).forEach(function (h) { if (h) nodo.appendChild(h); });
  }

  function chip(semaforo, extra) {
    var s = SEMAFORO[semaforo] || SEMAFORO.verde;
    return el("span", { class: "chip chip--" + semaforo }, s.simbolo + " " + s.etiqueta + (extra ? " · " + extra : ""));
  }

  // Todas las horas se muestran en hora de Veracruz, sin importar la zona del navegador ni la del servidor.
  var ZONA = "America/Mexico_City";
  var fmtHora = new Intl.DateTimeFormat("es-MX", { timeZone: ZONA, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  var fmtFecha = new Intl.DateTimeFormat("en-CA", { timeZone: ZONA, year: "numeric", month: "2-digit", day: "2-digit" });
  /** ISO 8601 con zona → "HH:MM" en hora de Veracruz. */
  function hora(iso) { return iso ? fmtHora.format(new Date(iso)) : "--:--"; }
  /** ISO 8601 con zona → "AAAA-MM-DD" en hora de Veracruz. */
  function fecha(iso) { return iso ? fmtFecha.format(new Date(iso)) : ""; }
  function zonaHoraria(iso) { var m = /([+-]\d\d:\d\d|Z)$/.exec(String(iso)); return m ? m[1] : "-06:00"; }

  var nf0 = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 0 });
  var nf1 = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 1 });
  function num(x, dec) { return (dec ? nf1 : nf0).format(x || 0); }

  async function api(ruta, opciones) {
    var o = Object.assign({ headers: {} }, opciones || {});
    if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers["Content-Type"] = "application/json"; delete o.json; }
    var r = await fetch(ruta, o);
    var cuerpo = null;
    try { cuerpo = await r.json(); } catch (e) { cuerpo = null; }
    if (!r.ok) {
      var d = cuerpo && cuerpo.detail;
      var msg = typeof d === "string" ? d : (Array.isArray(d) && d[0] && d[0].msg) || ("Error " + r.status);
      throw new Error(msg);
    }
    return cuerpo;
  }

  /**
   * Conecta al WebSocket del simulador; si falla, consulta /api/sim/snapshot cada segundo
   * y reintenta el WebSocket cada 5 s. `alMensaje` recibe {tipo, data}.
   */
  function conectarSimulacion(alMensaje, alEstado) {
    var ws = null, sondeo = null;
    function iniciarSondeo() {
      if (sondeo) return;
      alEstado && alEstado("sondeo");
      sondeo = setInterval(function () {
        api("/api/sim/snapshot").then(function (s) { alMensaje({ tipo: "snapshot", data: s }); }).catch(function () {});
      }, 1000);
    }
    function abrir() {
      var url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/sim";
      try { ws = new WebSocket(url); } catch (e) { iniciarSondeo(); setTimeout(abrir, 5000); return; }
      ws.onopen = function () {
        if (sondeo) { clearInterval(sondeo); sondeo = null; }
        alEstado && alEstado("en-vivo");
      };
      ws.onmessage = function (ev) { try { alMensaje(JSON.parse(ev.data)); } catch (e) { /* mensaje inválido */ } };
      ws.onclose = function () { iniciarSondeo(); setTimeout(abrir, 5000); };
      ws.onerror = function () { try { ws.close(); } catch (e) { /* ya cerrado */ } };
    }
    abrir();
  }

  /** Une franjas consecutivas Lento/Saturado en intervalos {inicio, fin, semaforo, max}. */
  function horasPico(franjas, franjaMin) {
    var picos = [], actual = null, grav = { verde: 0, amarillo: 1, rojo: 2 };
    franjas.forEach(function (f) {
      var fin = new Date(new Date(f.inicio).getTime() + franjaMin * 60000);
      if (f.semaforo === "verde") { actual = null; return; }
      if (actual && actual.finMs === new Date(f.inicio).getTime()) {
        actual.finMs = fin.getTime(); actual.finHora = horaMas(f.inicio, franjaMin);
        actual.max = Math.max(actual.max, f.espera_min);
        if (grav[f.semaforo] > grav[actual.semaforo]) actual.semaforo = f.semaforo;
      } else {
        actual = { inicio: hora(f.inicio), finHora: horaMas(f.inicio, franjaMin), finMs: fin.getTime(), semaforo: f.semaforo, max: f.espera_min };
        picos.push(actual);
      }
    });
    return picos;
  }
  /** Prepara una ruta [[lat, lon], …] para ubicar camiones por su progreso 0–1 (distancias acumuladas). */
  function prepararRuta(coords) {
    var acum = [0];
    for (var i = 1; i < coords.length; i++) {
      var dy = coords[i][0] - coords[i - 1][0], dx = coords[i][1] - coords[i - 1][1];
      acum.push(acum[i - 1] + Math.sqrt(dx * dx + dy * dy));
    }
    return { coords: coords, acum: acum, total: acum[acum.length - 1] || 1 };
  }

  /** Punto [lat, lon] a una fracción `progreso` (0–1) del recorrido de la ruta. */
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

  function horaMas(iso, minutos) { return hora(new Date(new Date(iso).getTime() + minutos * 60000)); }

  window.Fluport = {
    SEMAFORO: SEMAFORO, el: el, reemplazar: reemplazar, chip: chip, hora: hora, fecha: fecha,
    zonaHoraria: zonaHoraria, num: num, api: api, conectarSimulacion: conectarSimulacion,
    horasPico: horasPico, prepararRuta: prepararRuta, posicion: posicion
  };
})();
