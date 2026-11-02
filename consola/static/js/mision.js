// Pantalla "Mision (varias RSU)": mapa en vivo (mapa.js), una tarjeta por
// RSU (fase NTCIP 1202 por SNMPv3 + estado de la solicitud de prioridad y
// cuanto lleva en el) y la linea de tiempo de la mision (MI, MR, M1 por
// RSU, M2, M3 con motivo, MF). Todo sale de consola/backend/mision.py y
// consola/backend/snmp_multi.py; aqui solo se dibuja.
window.Consola = window.Consola || {};

(function () {
  const U = Consola.utils;
  const TEXTO_ESTADO = {
    pendiente: "pendiente", solicitada: "solicitada", en_cola: "en cola", concedida: "concedida",
    liberada: "liberada", en_espera: "en espera por otra unidad", cancelada: "cancelada", rechazada: "rechazada",
  };
  const rsus = {};          // rsu_id -> {info, fase, prioridad, el}
  let mision = null;
  let desfaseReloj = 0;     // (reloj del servidor de la consola) - (reloj del navegador), s

  function textoEstado(e) { return TEXTO_ESTADO[e] || e || "—"; }
  function ahora() { return Date.now() / 1000 + desfaseReloj; }

  function duracion(s) {
    if (s == null || s < 0) return "—";
    if (s < 60) return `${s.toFixed(0)} s`;
    return `${Math.floor(s / 60)} min ${String(Math.floor(s % 60)).padStart(2, "0")} s`;
  }

  function crearTarjeta(info) {
    const el = U.el("div", { class: "tarjeta-rsu", "data-rsu": info.rsu_id });
    el.innerHTML = `
      <div class="tarjeta-cabecera">
        <div class="mini-semaforo"><span data-luz="rojo"></span><span data-luz="ambar"></span><span data-luz="verde"></span></div>
        <div class="tarjeta-titulo"><strong>RSU ${info.rsu_id}</strong> <span class="orden"></span><br><span class="nota-chica">${info.interseccion_id}</span></div>
        <div class="insignia-estado" data-estado="pendiente">—</div>
      </div>
      <dl class="ficha">
        <div><dt>Fase (NTCIP 1202)</dt><dd class="v-fase">—</dd></div>
        <div><dt>En este estado</dt><dd class="v-desde">—</dd></div>
        <div><dt>Acceso · ETA</dt><dd class="v-acceso">—</dd></div>
        <div><dt>Último M2</dt><dd class="v-m2">—</dd></div>
        <div><dt>Motivo de cancelación</dt><dd class="v-motivo">—</dd></div>
        <div><dt>SNMPv3</dt><dd class="v-snmp">${info.snmp_port ? `${info.snmp_host}:${info.snmp_port}` : info.fuente_snmp}</dd></div>
      </dl>`;
    return el;
  }

  function pintarFase(r) {
    const f = r.fase || {};
    const el = r.el;
    el.classList.toggle("sin-conexion", !f.conectado);
    el.querySelectorAll("[data-luz]").forEach((l) => l.classList.toggle("on", !!f.conectado && f.fase === l.dataset.luz));
    el.querySelector(".v-fase").textContent = f.conectado ? f.fase : "sin conexión";
    el.querySelector(".v-snmp").textContent = r.info.snmp_port
      ? `${r.info.snmp_host}:${r.info.snmp_port}` + (f.conectado ? ` · ${U.fmt(f.rtt_ms, 0, " ms")}` : ` · ${f.error || "sin respuesta"}`)
      : r.info.fuente_snmp;
  }

  function pintarPrioridad(r) {
    const p = r.prioridad;
    const el = r.el;
    const ins = el.querySelector(".insignia-estado");
    ins.dataset.estado = p ? p.estado : "fuera";
    ins.textContent = p ? textoEstado(p.estado) : (mision && mision.ruta ? "fuera de la ruta" : "sin misión");
    ins.style.background = p ? Consola.mapa.COLOR_PRIORIDAD[p.estado] || "" : "";
    el.querySelector(".orden").textContent = p ? `· parada #${p.orden}` : "";
    el.querySelector(".v-acceso").textContent = p ? `${p.acceso_id || "?"} · ${p.eta_s != null ? U.fmt(p.eta_s, 1, " s") : "—"}` : "—";
    const m2 = p && p.ultimo_m2;
    el.querySelector(".v-m2").textContent = m2 ? `${m2.estado} (fase ${m2.fase})` + (p.renovaciones ? ` · ${p.renovaciones} renov.` : "") : "—";
    el.querySelector(".v-motivo").textContent = (p && p.motivo) || "—";
    el.classList.toggle("en-ruta", !!p);
  }

  function relojTarjetas() {
    // Terminada la mision, los contadores se congelan en el instante del MF.
    const t = mision && mision.mision && mision.mision.t_fin ? mision.mision.t_fin : ahora();
    Object.values(rsus).forEach((r) => {
      r.el.querySelector(".v-desde").textContent = r.prioridad ? duracion(Math.max(0, t - r.prioridad.desde)) : "—";
    });
    if (mision && mision.mision) {
      const m = mision.mision;
      const fin = m.t_fin || ahora();
      document.getElementById("mision-duracion").textContent = duracion(fin - m.t_inicio);
    }
  }

  function ordenarTarjetas() {
    const cont = document.getElementById("tarjetas-rsu");
    const lista = Object.values(rsus).sort((a, b) => {
      const oa = a.prioridad ? a.prioridad.orden : 999, ob = b.prioridad ? b.prioridad.orden : 999;
      return oa - ob || String(a.info.rsu_id).localeCompare(String(b.info.rsu_id), "es", { numeric: true });
    });
    lista.forEach((r) => cont.appendChild(r.el));
  }

  function aplicarMision(d) {
    mision = d;
    const m = d.mision, r = d.ruta;
    const set = (id, v) => (document.getElementById(id).textContent = v);
    set("mision-obu", m ? m.obu_id : "—");
    set("mision-id", (m && m.mision_id) || "—");
    set("mision-estado", m ? (m.activa ? "activa" : `terminada (${m.motivo_fin || "?"})`) : "sin misión");
    set("mision-ruta", r ? `${U.fmt(r.longitud_total_m, 0, " m")} · ${r.paradas.length} RSU en la ruta` : "—");
    Consola.mapa.fijarRuta(r);
    if (m && !m.activa) Object.values(rsus).forEach(pintarPrioridad);
    if (r) {
      const enRuta = new Set(r.paradas.map((p) => String(p.rsu_id)));
      Object.entries(rsus).forEach(([id, x]) => { if (!enRuta.has(id)) { x.prioridad = null; pintarPrioridad(x); Consola.mapa.fijarRsu(id, "prioridad", null); } });
    }
    if (m && m.activa && !r) {
      Object.entries(rsus).forEach(([id, x]) => { x.prioridad = null; pintarPrioridad(x); Consola.mapa.fijarRsu(id, "prioridad", null); });
      document.getElementById("linea-tiempo").innerHTML = "";
    }
    ordenarTarjetas();
  }

  function aplicarFase(f) {
    const r = rsus[f.rsu_id];
    if (r) { r.fase = f; pintarFase(r); }
    Consola.mapa.fijarRsu(f.rsu_id, "fase", f);
    // Indicador SNMPv3 de la barra superior: en modo multi-RSU resume todas.
    const todas = Object.values(rsus);
    const ok = todas.filter((x) => x.fase && x.fase.conectado).length;
    const ind = document.getElementById("ind-snmp");
    ind.dataset.estado = ok === todas.length ? "ok" : ok ? "advertencia" : "error";
    ind.querySelector(".texto").textContent = `SNMPv3 ${ok}/${todas.length} RSU`;
  }

  function aplicarPrioridad(p) {
    const r = rsus[p.rsu_id];
    if (r) { r.prioridad = p; pintarPrioridad(r); }
    Consola.mapa.fijarRsu(p.rsu_id, "prioridad", p);
    ordenarTarjetas();
  }

  function aplicarEvento(e) {
    const cont = document.getElementById("linea-tiempo");
    const t0 = mision && mision.mision ? mision.mision.t_inicio : e.t;
    const fila = U.el("div", { class: `evento-mision tipo-${e.tipo}` });
    fila.innerHTML = `<span class="hora">${U.horaDe(e.t)}</span><span class="rel">+${(e.t - t0).toFixed(1)} s</span>`
      + `<span class="tipo">${e.tipo}</span>` + (e.rsu_id ? `<span class="rsu">RSU ${e.rsu_id}</span>` : `<span class="rsu"></span>`)
      + `<span class="texto"></span>`;
    fila.querySelector(".texto").textContent = e.texto;
    cont.appendChild(fila);
    if (cont.dataset.pausado !== "1") cont.scrollTop = cont.scrollHeight;
  }

  async function init() {
    const demo = await U.fetchJSON("/api/demo");
    const cont = document.getElementById("tarjetas-rsu");
    const lista = demo.rsus.length ? demo.rsus : [];
    document.getElementById("mision-registro").textContent = demo.modo_multi_rsu
      ? `${demo.registro}` + (demo.demo_dir ? ` · logs en ${demo.demo_dir}` : "")
      : "modo de una sola RSU (arrancar con --estado-demo o --registro para ver varias, ver docs/CONSOLA.md)";
    lista.forEach((info) => {
      rsus[info.rsu_id] = { info, fase: null, prioridad: null, el: crearTarjeta(info) };
      cont.appendChild(rsus[info.rsu_id].el);
      pintarFase(rsus[info.rsu_id]);
      pintarPrioridad(rsus[info.rsu_id]);
    });

    const lt = document.getElementById("linea-tiempo");
    lt.addEventListener("mouseenter", () => (lt.dataset.pausado = "1"));
    lt.addEventListener("mouseleave", () => (lt.dataset.pausado = "0"));

    const foto = await U.fetchJSON("/api/mision");
    desfaseReloj = foto.ahora - Date.now() / 1000;
    const estado = await U.fetchJSON("/api/estado");
    Object.values(estado.rsu_fase || {}).forEach(aplicarFase);
    aplicarMision(foto);
    Object.values(foto.prioridad).forEach(aplicarPrioridad);
    foto.linea_tiempo.forEach(aplicarEvento);
    if (foto.posicion) Consola.mapa.fijarPosicion(foto.posicion);

    Consola.sse.on("rsu_fase", (ev) => aplicarFase(ev.datos));
    Consola.sse.on("rsu_prioridad", (ev) => aplicarPrioridad(ev.datos));
    Consola.sse.on("mision", (ev) => aplicarMision(ev.datos));
    Consola.sse.on("mision_evento", (ev) => aplicarEvento(ev.datos));
    Consola.sse.on("mision_pos", (ev) => Consola.mapa.fijarPosicion(ev.datos));
    setInterval(relojTarjetas, 500);
    return demo;
  }

  window.Consola.mision = { init, textoEstado };
})();

// Leyenda de colores del anillo de cada RSU en el mapa.
window.addEventListener("DOMContentLoaded", () => {
  const ley = document.getElementById("leyenda-prioridad");
  if (!ley) return;
  Object.entries(Consola.mapa.COLOR_PRIORIDAD).forEach(([estado, color]) => {
    const s = document.createElement("span");
    s.style.setProperty("--c", color);
    s.textContent = Consola.mision.textoEstado(estado);
    ley.appendChild(s);
  });
});
