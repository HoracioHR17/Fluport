/* Fluport · vista pública: estado de contingencia por entrada (/api/publico/zonas cada 10 s) y acceso al bot. */
(function () {
  "use strict";
  var F = window.Fluport, el = F.el;
  var GRAVEDAD = { rojo: 0, amarillo: 1, verde: 2 };
  var CONTINGENCIA = { normal: "Operación normal", lenta: "Tránsito lento", saturada: "Contingencia: saturada",
    cerrada: "Contingencia: cerrada" };

  function textoPicos(picos) {
    if (!picos.length) return "sin horas pico previstas";
    return picos.slice(0, 2).map(function (p) {
      return F.hora(p.inicio) + " a " + F.hora(p.fin) + " (hasta " + F.num(p.espera_max_min) + " min)";
    }).join(" · ");
  }

  async function cargar() {
    var cont = document.getElementById("zonas");
    try {
      var zonas = await F.api("/api/publico/zonas");
      zonas.sort(function (a, b) { return GRAVEDAD[a.semaforo] - GRAVEDAD[b.semaforo] || b.espera_min - a.espera_min; });
      renderAlerta(zonas);
      if (zonas[0]) {
        document.getElementById("actualizado").textContent = "Actualizado a las " + F.hora(zonas[0].actualizado_en) + " (hora simulada) · en tiempo real";
        document.getElementById("etiqueta").textContent = zonas[0].etiqueta || "SIMULACIÓN";
      }
      F.reemplazar(cont, zonas.map(function (z) {
        return el("article", { class: "tarjeta zona" }, [
          el("div", { class: "caseta__cab" }, [
            el("div", { style: { minWidth: "0" } }, [
              el("h2", { style: { margin: "0", fontSize: "19px" } }, z.nombre),
              el("div", { class: "caseta__zona", style: { marginTop: "2px" } }, z.zona)
            ]),
            F.chip(z.semaforo, z.abierto ? null : "cerrada")
          ]),
          el("div", { class: "contingencia contingencia--" + z.contingencia }, CONTINGENCIA[z.contingencia] || z.contingencia),
          el("div", {}, z.abierto ? [el("span", { class: "zona__espera cifra" }, F.num(z.espera_min)), " min de espera ahora"]
            : [el("b", {}, "Cerrada. "), "Usa otra entrada; los camiones con cita se desvían automáticamente."]),
          el("div", { class: "zona__detalle" }, [
            el("div", {}, [el("b", {}, "Horas pico: "), textoPicos(z.horas_pico)]),
            el("div", {}, [el("b", {}, "Mejor hora para pasar: "), el("span", { class: "cifra" }, F.hora(z.mejor_hora))])
          ])
        ]);
      }));
    } catch (e) {
      F.reemplazar(cont, [el("p", { class: "tarjeta", role: "alert" }, "No se pudo cargar la información. Reintentando…")]);
    }
  }

  function renderAlerta(zonas) {
    var caja = document.getElementById("alerta");
    var cerradas = zonas.filter(function (z) { return !z.abierto; }).map(function (z) { return z.nombre; });
    var saturadas = zonas.filter(function (z) { return z.abierto && z.contingencia === "saturada"; }).map(function (z) { return z.nombre; });
    var partes = [];
    if (zonas.length && zonas[0].norte) partes.push("Norte activo: la revisión es más lenta en todas las entradas.");
    if (cerradas.length) partes.push("Cerrada: " + cerradas.join(", ") + ".");
    if (saturadas.length) partes.push("Saturada: " + saturadas.join(", ") + ".");
    caja.classList.toggle("oculto", !partes.length);
    caja.textContent = partes.length ? "▲ " + partes.join(" ") : "";
  }

  async function cargarBot() {
    var caja = document.getElementById("cta-bot");
    try {
      var bot = await F.api("/api/telegram/enlace");
      document.getElementById("enlace-bot").href = bot.enlace;
      document.getElementById("enlace-bot").textContent = "Agenda tu cita en " + bot.usuario;
      if (window.qrcode) {
        var qr = window.qrcode(0, "M"); qr.addData(bot.enlace); qr.make();
        document.getElementById("qr-bot").innerHTML = qr.createSvgTag(4, 0); // SVG local de nuestra propia URL
      }
    } catch (e) {
      caja.classList.add("oculto"); // sin bot configurado no se muestra la invitación
    }
  }

  cargar();
  cargarBot();
  setInterval(cargar, 10000);
})();
