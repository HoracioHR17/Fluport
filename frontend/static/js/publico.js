/* Fluport · vista pública: contingencia por entrada (/api/publico/zonas), pronóstico de 12 h y acceso al bot. */
(function () {
  "use strict";
  var F = window.Fluport, el = F.el, $ = function (id) { return document.getElementById(id); };
  var GRAVEDAD = { rojo: 0, amarillo: 1, verde: 2 };
  var COLOR = { verde: "#3FAE7A", amarillo: "#E9B03B", rojo: "#D9574B" };
  var ESTADO = { verde: "● Fluye", amarillo: "● Lento", rojo: "▲ Saturado" };

  function chip(z) {
    if (!z.abierto) return el("span", { class: "chip chip--oscuro" }, "Cerrada");
    return el("span", { class: "chip chip--" + z.semaforo }, ESTADO[z.semaforo]);
  }

  function proximaHora(z, pron) {
    var p = pron[z.acceso_id];
    if (!p || p.franjas.length < 3) return "—";
    var ahora = z.espera_min, luego = p.franjas[2].espera_min;
    if (Math.abs(luego - ahora) < 5) return "se mantiene en " + F.num(luego) + " min";
    return (luego > ahora ? "sube a " : "baja a ") + F.num(luego) + " min";
  }

  function renderAlerta(zonas) {
    var cerradas = zonas.filter(function (z) { return !z.abierto; });
    var saturadas = zonas.filter(function (z) { return z.abierto && z.contingencia === "saturada"; });
    var libres = zonas.filter(function (z) { return z.abierto && z.contingencia !== "saturada"; })
      .map(function (z) { return z.nombre.replace("Caseta ", ""); });
    var titulo = "", texto = "";
    if (cerradas.length) {
      titulo = "Contingencia activa: " + cerradas.map(function (z) { return z.nombre; }).join(", ") + (cerradas.length > 1 ? " cerradas" : " cerrada");
      texto = (libres.length ? "Usa " + libres.join(" o ") + ". " : "") + "Los camiones con cita se desvían automáticamente y reciben aviso en Telegram.";
    } else if (saturadas.length) {
      titulo = "Entrada saturada: " + saturadas.map(function (z) { return z.nombre; }).join(", ");
      texto = libres.length ? "Si puedes, usa " + libres.join(" o ") + "." : "Revisa la mejor hora para pasar.";
    }
    if (zonas.length && zonas[0].norte) {
      titulo = titulo || "Norte activo";
      texto = (texto ? texto + " " : "") + "Hay norte: la revisión es más lenta en todas las entradas.";
    }
    $("alerta").classList.toggle("oculto", !titulo);
    $("alerta-titulo").textContent = titulo;
    $("alerta-texto").textContent = texto;
  }

  function renderZonas(zonas, pron) {
    F.reemplazar($("zonas"), zonas.map(function (z) {
      return el("article", { class: "entrada" }, [
        el("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "12px" } }, [
          el("div", { style: { display: "flex", flexDirection: "column", gap: "4px" } }, [
            el("span", { class: "tenue", style: { fontSize: "13px" } }, z.zona),
            el("h2", {}, z.nombre)
          ]),
          chip(z)
        ]),
        el("div", { class: "entrada__espera" }, z.abierto
          ? [el("span", { class: "cifra" }, F.num(z.espera_min)), el("span", { class: "tenue" }, "min de espera ahora")]
          : [el("span", { class: "cifra" }, "—"), el("span", { class: "tenue" }, "sin paso por ahora")]),
        el("div", { class: "entrada__detalle" }, [
          el("span", {}, [el("b", {}, "Próxima hora: "), proximaHora(z, pron)]),
          el("span", {}, [el("b", {}, "Mejor hora para pasar: "), el("span", { class: "cifra" }, F.hora(z.mejor_hora))])
        ])
      ]);
    }));
  }

  function renderLineas(zonas, pron) {
    var filas = zonas.map(function (z) {
      var p = pron[z.acceso_id];
      var bloques = (p ? p.franjas.slice(0, 24) : []).map(function (f) {
        return el("span", { title: F.hora(f.inicio) + " · " + F.num(f.espera_min) + " min", style: { background: COLOR[f.semaforo] } });
      });
      return el("div", { class: "linea" }, [
        el("span", { style: { fontWeight: "700", fontSize: "15px" } }, z.nombre.replace("Caseta ", "")),
        el("div", { class: "bloques", role: "img", "aria-label": "Pronóstico de " + z.nombre + (z.mejor_hora ? ", mejor hora " + F.hora(z.mejor_hora) : "") }, bloques)
      ]);
    });
    var ref = pron[zonas[0] && zonas[0].acceso_id];
    if (ref && ref.franjas.length) {
      var n = Math.min(24, ref.franjas.length);
      var marcas = [0, 6, 12, 18, n - 1].filter(function (i) { return i < n; }).map(function (i) { return el("span", {}, F.hora(ref.franjas[i].inicio)); });
      filas.push(el("div", { class: "linea" }, [el("span", {}), el("div", { class: "horas" }, marcas)]));
    }
    F.reemplazar($("lineas"), filas);
  }

  async function cargar() {
    try {
      var res = await Promise.all([F.api("/api/publico/zonas"), F.api("/api/pronostico").catch(function () { return []; })]);
      var zonas = res[0], pron = {};
      res[1].forEach(function (p) { pron[p.acceso_id] = p; });
      zonas.sort(function (a, b) { return (a.abierto - b.abierto) || GRAVEDAD[a.semaforo] - GRAVEDAD[b.semaforo] || b.espera_min - a.espera_min; });
      if (zonas[0]) {
        $("actualizado").textContent = "Tiempos estimados en tiempo real · actualizado a las " + F.hora(zonas[0].actualizado_en) + " (hora simulada)";
        $("etiqueta").textContent = zonas[0].etiqueta || "SIMULACIÓN";
      }
      renderAlerta(zonas);
      renderZonas(zonas, pron);
      renderLineas(zonas, pron);
    } catch (e) {
      F.reemplazar($("zonas"), [el("p", { class: "tarjeta", role: "alert" }, "No se pudo cargar la información. Reintentando…")]);
    }
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

  cargar();
  cargarBot();
  setInterval(cargar, 10000);
})();
