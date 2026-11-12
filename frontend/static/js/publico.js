/* Fluport · vista pública para vecinos: /api/publico/zonas cada 30 s. */
(function () {
  "use strict";
  var F = window.Fluport, el = F.el;
  var GRAVEDAD = { rojo: 0, amarillo: 1, verde: 2 };

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
      if (zonas[0]) {
        document.getElementById("actualizado").textContent = "Actualizado a las " + F.hora(zonas[0].actualizado_en) + " · se renueva cada 30 s";
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
          el("div", {}, [el("span", { class: "zona__espera cifra" }, F.num(z.espera_min)), " min de espera ahora"]),
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

  cargar();
  setInterval(cargar, 30000);
})();
