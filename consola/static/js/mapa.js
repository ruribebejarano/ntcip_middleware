// Mapa en vivo de la mision, en SVG puro (sin teselas: funciona sin internet).
//  - Calles de fondo: grafo vial de OpenStreetMap ya cacheado en data/
//    (/api/mapa/calles, consola/backend/mapa.py) -- el mismo que usa el
//    servidor central para calcular la ruta.
//  - RSU / geocercas / accesos: registro de RSU (/api/mapa).
//  - Ruta (MR) y posicion de la OBU (MP): eventos SSE "mision" y
//    "mision_pos" (consola/backend/mision.py, lo que pasa por el broker).
//  - Cada RSU es un semaforo coloreado por su fase NTCIP 1202 (evento
//    "rsu_fase", consola/backend/snmp_multi.py) con un anillo del color de
//    su estado de prioridad (evento "rsu_prioridad", de ME/M1/M2/M3).
// La proyeccion local (x este, y norte, en metros) es la misma de
// gateway/geometria.py; se duplica aqui solo para dibujar.
window.Consola = window.Consola || {};

(function () {
  const RADIO_TIERRA_M = 6371000.0;
  const NS = "http://www.w3.org/2000/svg";
  const COLOR_PRIORIDAD = {
    pendiente: "#a8a29e", solicitada: "#2563eb", en_cola: "#a16207", concedida: "#15803d",
    en_espera: "#7c3aed", liberada: "#0f766e", cancelada: "#78716c", rechazada: "#b91c1c",
  };
  const COLOR_LUZ = { rojo: "#e63946", ambar: "#e8b339", verde: "#22a35a" };

  let geo = null;
  const instancias = [];
  const estadoRsu = {};      // rsu_id -> {fase, prioridad}
  let ruta = null;
  let estela = [];
  let posicion = null;

  function svgEl(tag, attrs) {
    const e = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
  }

  function proyeccion(lat, lon) {
    const x = RADIO_TIERRA_M * ((lon - geo.lon0) * Math.PI / 180) * Math.cos(geo.lat0 * Math.PI / 180);
    const y = RADIO_TIERRA_M * ((lat - geo.lat0) * Math.PI / 180);
    return { x, y: -y }; // norte arriba: el SVG necesita y invertida
  }

  function inversa(x, ySvg) {
    const lat = geo.lat0 + (-ySvg / RADIO_TIERRA_M) * 180 / Math.PI;
    const lon = geo.lon0 + (x / (RADIO_TIERRA_M * Math.cos(geo.lat0 * Math.PI / 180))) * 180 / Math.PI;
    return { lat, lon };
  }

  // --- una instancia por <svg> (Monitoreo en vivo y Mision multi-RSU) ----

  class MapaVivo {
    constructor(svg) {
      this.svg = svg;
      this.vista = null;        // {x, y, w, h} en metros (viewBox)
      this.cajaCalles = null;   // recuadro lat/lon ya pedido a /api/mapa/calles
      this.capas = {};
      ["calles", "geocercas", "ruta", "estela", "rsu", "obu"].forEach((n) => {
        this.capas[n] = svgEl("g", { class: `capa-${n}` });
        svg.appendChild(this.capas[n]);
      });
      this.configurarZoom();
      new ResizeObserver(() => this.redibujarMarcadores()).observe(svg);
    }

    metrosPorPixel() {
      const w = this.svg.clientWidth || 800, h = this.svg.clientHeight || 480;
      return Math.max(this.vista.w / w, this.vista.h / h);
    }

    aplicarVista() {
      const v = this.vista;
      this.svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
      this.redibujarMarcadores();
    }

    encuadrar(puntos, margen = 120) {
      if (!puntos.length) return;
      const xs = puntos.map((p) => p.x), ys = puntos.map((p) => p.y);
      const x0 = Math.min(...xs) - margen, x1 = Math.max(...xs) + margen;
      const y0 = Math.min(...ys) - margen, y1 = Math.max(...ys) + margen;
      this.vista = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
      this.aplicarVista();
      this.pedirCalles(x0 - 400, y0 - 400, x1 + 400, y1 + 400);
    }

    configurarZoom() {
      const svg = this.svg;
      svg.addEventListener("wheel", (ev) => {
        if (!this.vista) return;
        ev.preventDefault();
        const f = ev.deltaY > 0 ? 1.2 : 1 / 1.2;
        const r = svg.getBoundingClientRect();
        const k = this.metrosPorPixel();
        // punto bajo el cursor en metros (con preserveAspectRatio meet, centrado)
        const cx = this.vista.x + this.vista.w / 2 + (ev.clientX - r.left - r.width / 2) * k;
        const cy = this.vista.y + this.vista.h / 2 + (ev.clientY - r.top - r.height / 2) * k;
        const v = this.vista;
        this.vista = { x: cx - (cx - v.x) * f, y: cy - (cy - v.y) * f, w: v.w * f, h: v.h * f };
        this.aplicarVista();
        this.pedirCalles(this.vista.x, this.vista.y, this.vista.x + this.vista.w, this.vista.y + this.vista.h);
      }, { passive: false });
      let arrastre = null;
      svg.addEventListener("pointerdown", (ev) => { if (this.vista) { arrastre = { x: ev.clientX, y: ev.clientY, v: { ...this.vista } }; svg.setPointerCapture(ev.pointerId); } });
      svg.addEventListener("pointermove", (ev) => {
        if (!arrastre) return;
        const k = this.metrosPorPixel();
        this.vista = { ...arrastre.v, x: arrastre.v.x - (ev.clientX - arrastre.x) * k, y: arrastre.v.y - (ev.clientY - arrastre.y) * k };
        this.svg.setAttribute("viewBox", `${this.vista.x} ${this.vista.y} ${this.vista.w} ${this.vista.h}`);
      });
      svg.addEventListener("pointerup", () => {
        if (!arrastre) return;
        arrastre = null;
        this.pedirCalles(this.vista.x, this.vista.y, this.vista.x + this.vista.w, this.vista.y + this.vista.h);
      });
      svg.addEventListener("dblclick", () => this.encuadrarTodo());
    }

    encuadrarTodo() {
      const puntos = (geo.intersecciones || []).map((i) => ({ x: i.x, y: -i.y }));
      if (ruta) ruta.geometria.forEach(([lat, lon]) => puntos.push(proyeccion(lat, lon)));
      this.encuadrar(puntos);
    }

    async pedirCalles(x0, y0, x1, y1) {
      const a = inversa(x0, y1), b = inversa(x1, y0); // (sur, oeste) y (norte, este)
      const c = this.cajaCalles;
      if (c && a.lat >= c.sur && a.lon >= c.oeste && b.lat <= c.norte && b.lon <= c.este) return;
      // se pide un recuadro algo mayor para no volver a pedir con cada arrastre
      const dLat = (b.lat - a.lat) * 0.5, dLon = (b.lon - a.lon) * 0.5;
      const caja = { sur: a.lat - dLat, oeste: a.lon - dLon, norte: b.lat + dLat, este: b.lon + dLon };
      this.cajaCalles = caja;
      try {
        const r = await Consola.utils.fetchJSON(`/api/mapa/calles?sur=${caja.sur}&oeste=${caja.oeste}&norte=${caja.norte}&este=${caja.este}`);
        this.dibujarCalles(r.lineas || []);
      } catch (e) { console.error("[mapa] calles", e); }
    }

    dibujarCalles(lineas) {
      const g = this.capas.calles;
      g.innerHTML = "";
      lineas.sort((p, q) => p.peso - q.peso).forEach((l) => {
        const d = l.p.map(([x, y], i) => (i ? "L" : "M") + x + " " + (-y)).join(" ");
        const p = svgEl("path", { d, class: "calle", "stroke-width": 1 + l.peso, "vector-effect": "non-scaling-stroke" });
        if (l.nombre) p.appendChild(svgEl("title")).textContent = l.nombre;
        g.appendChild(p);
      });
    }

    dibujarGeocercas() {
      const g = this.capas.geocercas;
      g.innerHTML = "";
      (geo.intersecciones || []).forEach((inter) => {
        g.appendChild(svgEl("circle", { cx: inter.x, cy: -inter.y, r: inter.r_i_m, class: "geocerca-ri", "vector-effect": "non-scaling-stroke" }));
        g.appendChild(svgEl("circle", { cx: inter.x, cy: -inter.y, r: inter.r_g_m, class: "geocerca-rg", "vector-effect": "non-scaling-stroke" }));
      });
    }

    dibujarRuta() {
      const g = this.capas.ruta;
      g.innerHTML = "";
      if (!ruta || !ruta.geometria.length) return;
      const d = ruta.geometria.map(([lat, lon], i) => { const p = proyeccion(lat, lon); return (i ? "L" : "M") + p.x + " " + p.y; }).join(" ");
      g.appendChild(svgEl("path", { d, class: "ruta-mision", "vector-effect": "non-scaling-stroke" }));
      const fin = ruta.geometria[ruta.geometria.length - 1];
      const pf = proyeccion(fin[0], fin[1]);
      g.appendChild(svgEl("circle", { cx: pf.x, cy: pf.y, r: 4, class: "ruta-destino", "data-escala": "1" }));
    }

    dibujarEstela() {
      const g = this.capas.estela;
      g.innerHTML = "";
      if (estela.length > 1) {
        g.appendChild(svgEl("path", { d: estela.map((p, i) => (i ? "L" : "M") + p.x + " " + p.y).join(" "), class: "estela-obu", "vector-effect": "non-scaling-stroke" }));
      }
    }

    // Marcadores de tamano constante en pantalla: se dibujan en pixeles y se
    // escalan con los metros por pixel de la vista actual.
    redibujarMarcadores() {
      if (!this.vista || !geo) return;
      const k = this.metrosPorPixel();
      const g = this.capas.rsu;
      g.innerHTML = "";
      const ordenEnRuta = {};
      if (ruta) ruta.paradas.forEach((p, i) => (ordenEnRuta[String(p.rsu_id)] = i + 1));
      (geo.intersecciones || []).forEach((inter) => {
        const est = estadoRsu[inter.rsu_id] || {};
        const fase = est.fase || {};
        const prio = est.prioridad;
        const sinConexion = !fase.conectado;
        const m = svgEl("g", { transform: `translate(${inter.x} ${-inter.y}) scale(${k})`, class: "marcador-rsu" + (sinConexion ? " sin-conexion" : "") });
        const colorPrio = prio ? (COLOR_PRIORIDAD[prio.estado] || "#78716c") : "none";
        m.appendChild(svgEl("circle", { r: 26, fill: "none", stroke: colorPrio, "stroke-width": prio && prio.estado !== "pendiente" ? 5 : 2, class: prio && prio.estado === "concedida" ? "anillo-concedida" : "" }));
        m.appendChild(svgEl("rect", { x: -9, y: -21, width: 18, height: 42, rx: 4, class: "caja-semaforo" }));
        [["rojo", -12], ["ambar", 0], ["verde", 12]].forEach(([c, dy]) => {
          const on = !sinConexion && fase.fase === c;
          m.appendChild(svgEl("circle", { cx: 0, cy: dy, r: 5, fill: on ? COLOR_LUZ[c] : "#3a3836", class: on ? "luz-on" : "" }));
        });
        const orden = ordenEnRuta[inter.rsu_id];
        const etiqueta = svgEl("text", { x: 32, y: -6, class: "etiqueta-rsu" });
        etiqueta.textContent = `RSU ${inter.rsu_id}` + (orden ? ` · #${orden}` : "");
        m.appendChild(etiqueta);
        const sub = svgEl("text", { x: 32, y: 9, class: "etiqueta-rsu-sub" });
        sub.textContent = sinConexion ? "sin conexión" : (prio ? Consola.mision.textoEstado(prio.estado) : (fase.fase || ""));
        m.appendChild(sub);
        g.appendChild(m);
      });
      this.capas.ruta.querySelectorAll("[data-escala]").forEach((c) => c.setAttribute("r", 6 * k));
      this.dibujarObu(k);
    }

    dibujarObu(k) {
      const g = this.capas.obu;
      g.innerHTML = "";
      if (!posicion) return;
      const p = proyeccion(posicion.lat, posicion.lon);
      const m = svgEl("g", { transform: `translate(${p.x} ${p.y}) scale(${k || this.metrosPorPixel()})` });
      m.appendChild(svgEl("circle", { r: 9, class: "punto-obu" }));
      if (posicion.rumbo_deg != null) {
        m.appendChild(svgEl("path", { d: "M0 -17 L5 -9 L-5 -9 Z", class: "flecha-obu", transform: `rotate(${posicion.rumbo_deg})` }));
      }
      g.appendChild(m);
    }
  }

  // --- API del modulo ----------------------------------------------------

  async function cargar(ids) {
    geo = await Consola.utils.fetchJSON("/api/mapa");
    ids.forEach((id) => {
      const svg = document.getElementById(id);
      if (!svg) return;
      svg.innerHTML = "";
      const m = new MapaVivo(svg);
      instancias.push(m);
      m.dibujarGeocercas();
      m.encuadrarTodo();
    });
  }

  function fijarRuta(r) {
    const nueva = !ruta || !r || ruta.mision_id !== (r && r.mision_id);
    ruta = r && r.geometria ? r : null;
    if (nueva) estela = [];
    instancias.forEach((m) => { m.dibujarRuta(); m.dibujarEstela(); if (nueva && ruta) m.encuadrarTodo(); else m.redibujarMarcadores(); });
  }

  function fijarPosicion(p) {
    posicion = p;
    if (p) {
      estela.push(proyeccion(p.lat, p.lon));
      if (estela.length > 1200) estela.shift();
    }
    instancias.forEach((m) => { m.dibujarEstela(); if (m.vista) m.dibujarObu(); });
  }

  function fijarRsu(rsuId, campo, valor) {
    estadoRsu[rsuId] = estadoRsu[rsuId] || {};
    const previo = JSON.stringify(estadoRsu[rsuId][campo] && { ...estadoRsu[rsuId][campo], ts: 0, rtt_ms: 0 });
    estadoRsu[rsuId][campo] = valor;
    // la fase se sondea a 1 Hz: solo se redibuja si cambio algo visible
    if (previo !== JSON.stringify(valor && { ...valor, ts: 0, rtt_ms: 0 })) instancias.forEach((m) => m.redibujarMarcadores());
  }

  window.Consola.mapa = { cargar, fijarRuta, fijarPosicion, fijarRsu, COLOR_PRIORIDAD };
})();
