// Cliente SSE: una sola conexion a /sse, que reenvia cada evento a quien
// se haya suscrito a ese tipo (ver consola/backend/bus.py). El navegador
// reconecta solo (comportamiento nativo de EventSource) si se corta.
window.Consola = window.Consola || {};

(function () {
  const subs = {}; // tipo -> [callback, ...]
  let conectado = false;

  function on(tipo, cb) {
    (subs[tipo] = subs[tipo] || []).push(cb);
  }

  function emitir(tipo, evento) {
    (subs[tipo] || []).forEach((cb) => {
      try { cb(evento); } catch (e) { console.error("[sse]", tipo, e); }
    });
    (subs["*"] || []).forEach((cb) => {
      try { cb(evento); } catch (e) { console.error("[sse]", tipo, e); }
    });
  }

  function conectar() {
    const es = new EventSource("/sse");
    const tipos = ["mqtt", "mqtt_estado", "snmp_semaforo", "snmp_prs", "snmp_tiempos", "obu",
                   "evento_lazo", "eventos_remotos_error", "banco", "comando", "proceso", "proceso_linea"];
    tipos.forEach((tipo) => {
      es.addEventListener(tipo, (ev) => {
        if (!conectado) { conectado = true; emitir("_conexion", { conectado: true }); }
        try { emitir(tipo, JSON.parse(ev.data)); } catch (e) { console.error(e); }
      });
    });
    es.onerror = () => {
      if (conectado) { conectado = false; emitir("_conexion", { conectado: false }); }
    };
    es.onopen = () => { conectado = true; emitir("_conexion", { conectado: true }); };
  }

  window.Consola.sse = { on, conectar };
})();
