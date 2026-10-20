// Mapa del corredor en SVG puro (sin teselas: funciona sin internet). La
// geometria (intersecciones, R_i, R_g, accesos) sale de /api/mapa
// (consola/backend/mapa.py, que reutiliza gateway/geometria.py). La
// posicion del vehiculo se recibe por el evento SSE "obu" (archivo local
// de la OBU, nunca por MQTT: ssec:minimizacion) y se proyecta aqui con la
// misma formula de proyeccion local (duplicada solo para dibujar, no para
// ninguna decision del lazo).
window.Consola = window.Consola || {};

(function () {
  const RADIO_TIERRA_M = 6371000.0;
  let geo = null;
  let svg = null;
  let estela = [];

  function proyeccion(lat, lon) {
    const x = RADIO_TIERRA_M * ((lon - geo.lon0) * Math.PI / 180) * Math.cos(geo.lat0 * Math.PI / 180);
    const y = RADIO_TIERRA_M * ((lat - geo.lat0) * Math.PI / 180);
    return { x, y };
  }

  function svgEl(tag, attrs) {
    const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
  }

  // Norte arriba: en el plano (x=este, y=norte), el SVG necesita y invertida.
  function xy(p) { return { x: p.x, y: -p.y }; }

  const COLOR_ESTADO = {
    null: "#78716c", recibida: "#eb6834", concedida: "#15803d", rechazada: "#b91c1c", cancelada: "#78716c",
  };

  async function cargar() {
    svg = document.getElementById("svg-mapa");
    geo = await Consola.utils.fetchJSON("/api/mapa");
    dibujarEstatico();
  }

  function dibujarEstatico() {
    svg.innerHTML = "";
    const g = svgEl("g", { id: "capa-estatica" });
    (geo.intersecciones || []).forEach((inter) => {
      const c = xy(inter);
      g.appendChild(svgEl("circle", { cx: c.x, cy: c.y, r: inter.r_i_m, fill: "none", stroke: "#52514e", "stroke-opacity": .35, "stroke-width": 1 }));
      g.appendChild(svgEl("circle", { cx: c.x, cy: c.y, r: inter.r_g_m, fill: "#2a78d61a", stroke: "#2a78d6", "stroke-width": 1.4 }));
      inter.accesos.forEach((a) => {
        const ini = xy({ x: a.x_ini, y: a.y_ini }), fin = xy({ x: a.x_fin, y: a.y_fin });
        g.appendChild(svgEl("line", { x1: ini.x, y1: ini.y, x2: fin.x, y2: fin.y, stroke: "#52514e", "stroke-width": 2, "data-acceso": `${inter.interseccion_id}/${a.acceso_id}` }));
        const mid = { x: ini.x + (fin.x - ini.x) * 0.15, y: ini.y + (fin.y - ini.y) * 0.15 };
        const t = svgEl("text", { x: mid.x, y: mid.y, "font-size": "11", fill: "#57534e" });
        t.textContent = a.acceso_id;
        g.appendChild(t);
      });
      g.appendChild(svgEl("circle", { cx: c.x, cy: c.y, r: 5, fill: "#1c1917" }));
      const t = svgEl("text", { x: c.x, y: c.y - 12, "text-anchor": "middle", "font-size": "11.5", fill: "#1c1917" });
      t.textContent = `RSU ${inter.rsu_id} · ${inter.interseccion_id}`;
      g.appendChild(t);
    });
    svg.appendChild(g);
    svg.appendChild(svgEl("path", { id: "estela-obu", fill: "none", stroke: "#78716c", "stroke-width": 2, opacity: .6 }));
    svg.appendChild(svgEl("circle", { id: "punto-obu", r: 0, "stroke-width": 2, stroke: "#fcfcfb" }));
  }

  function resaltarAcceso(interseccionId, accesoId) {
    svg.querySelectorAll("line[data-acceso]").forEach((l) => {
      const activo = l.getAttribute("data-acceso") === `${interseccionId}/${accesoId}`;
      l.setAttribute("stroke", activo ? "#eb6834" : "#52514e");
      l.setAttribute("stroke-width", activo ? 4 : 2);
    });
  }

  function actualizarObu(obu) {
    if (!svg || !geo) return;
    const punto = svg.querySelector("#punto-obu");
    if (!obu) { punto.setAttribute("r", 0); return; }
    const p = xy(proyeccion(obu.lat, obu.lon));
    estela.push(p);
    if (estela.length > 200) estela.shift();
    const d = estela.map((q, i) => (i === 0 ? "M" : "L") + ` ${q.x} ${q.y}`).join(" ");
    svg.querySelector("#estela-obu").setAttribute("d", d);

    const a = obu.asignacion;
    if (a) resaltarAcceso(a.interseccion_id, a.acceso);
    const estadoM2 = (a && obu.solicitud) ? (obu.ultimo_m2 || {}).estado : null;
    punto.setAttribute("cx", p.x);
    punto.setAttribute("cy", p.y);
    punto.setAttribute("r", 7);
    punto.setAttribute("fill", COLOR_ESTADO[estadoM2] || COLOR_ESTADO[null]);
  }

  window.Consola.mapa = { cargar, actualizarObu };
})();
