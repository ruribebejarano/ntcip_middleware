// Pantalla "Monitoreo en vivo". Los indicadores de la fila superior son
// una vista rapida de sesion (aproximada, con el reloj de cada maquina
// segun de donde vino el evento); las cifras con rigor estadistico estan
// en la pantalla "Ensayos y metricas" (scripts/analisis/lazo_emulado.py).
window.Consola = window.Consola || {};

(function () {
  const U = Consola.utils, G = Consola.graficos;
  const rttSesion = [];
  const inicioSolicitud = {}; // id_solicitud -> ts (s) del M1 nueva (reloj OBU)
  let solicitudesActivas = new Set();
  let m1Enviados = 0, m1Recibidos = 0;

  function setIndicador(id, estado, texto) {
    const el = document.getElementById(id);
    el.dataset.estado = estado;
    if (texto) el.querySelector(".texto").textContent = texto;
  }

  function aplicarBanco(banco) {
    if (!banco) return;
    setIndicador("ind-rsu", banco.rsu_ssh && banco.rsu_ssh.ok ? "ok" : "error", "RSU");
    setIndicador("ind-controlador", (banco.servicios && banco.servicios.controller === "active") ? "ok" : "error", "Controlador");
    const reloj = banco.desfase_reloj || {};
    setIndicador("ind-reloj", reloj.ok ? "ok" : "advertencia", "Relojes");
  }

  function aplicarMqttEstado(d) {
    setIndicador("ind-broker", d.conectado ? "ok" : "error", "Broker");
  }

  function aplicarSemaforo(s) {
    const cont = document.getElementById("semaforo");
    ["roja", "amarilla", "verde"].forEach((c) => cont.querySelector(`.luz.${c}`).classList.toggle("on", !!s[{ roja: "red", amarilla: "yellow", verde: "green" }[c]]));
    const nota = document.getElementById("semaforo-nota");
    const fase = s.red ? "rojo" : s.yellow ? "ambar" : s.green ? "verde" : "?";
    nota.textContent = s.error ? `Error SNMP: ${s.error}` : `Fase actual: ${fase} (refresco 0.5 s)`;
    document.getElementById("m-fase").textContent = s.error ? "—" : fase;
    setIndicador("ind-snmp", s.error ? "error" : "ok", "SNMPv3");
  }

  function aplicarTablaPrs(filas) {
    const cuerpo = document.querySelector("#tabla-prs tbody");
    cuerpo.innerHTML = "";
    const activa = filas.find((f) => f.estado_nombre !== "idleNotValid");
    solicitudesActivas = new Set(filas.filter((f) => f.estado_nombre !== "idleNotValid").map((f) => f.priorityRequestID));
    document.getElementById("m-solicitudes-activas").textContent = solicitudesActivas.size;
    const campos = activa
      ? [["ID", activa.priorityRequestID], ["Vehículo", activa.priorityRequestVehicleID], ["Clase", activa.priorityRequestVehicleClassType], ["Estado", activa.estado_nombre], ["T. servicio deseado (s)", activa.priorityRequestTimeOfServiceDesired]]
      : [["Estado", "las 10 filas en idleNotValid (sin solicitudes)"]];
    campos.forEach(([k, v]) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${k}</td><td>${v ?? "?"}</td>`;
      cuerpo.appendChild(tr);
    });
  }

  function aplicarObu(obu) {
    Consola.mapa.actualizarObu(obu);
    if (!obu) return;
    document.getElementById("obu-vel").textContent = U.fmt(obu.velocidad_kmh, 0, " km/h");
    const a = obu.asignacion;
    document.getElementById("obu-dist").textContent = a ? U.fmt(a.distancia_m, 0, " m") : "—";
    document.getElementById("obu-interseccion").textContent = a ? `${a.interseccion_id} / ${a.acceso}` : "ninguna";
    document.getElementById("obu-solicitud").textContent = obu.solicitud || "ninguna";
    document.getElementById("obu-seq").textContent = obu.seq ?? "—";
    const m2 = obu.ultimo_m2 || {};
    document.getElementById("obu-m2").textContent = obu.solicitud ? (m2.estado ? `${m2.estado}${m2.fase ? " · fase " + m2.fase : ""}` : "enviada, sin respuesta") : "—";
    document.getElementById("obu-rtt").textContent = m2.rtt_ms != null ? U.fmt(m2.rtt_ms, 1, " ms") : "—";

    if (m2.rtt_ms != null) {
      rttSesion.push(m2.rtt_ms);
      if (rttSesion.length > 2000) rttSesion.shift();
      document.getElementById("m-rtt-ultimo").textContent = U.fmt(m2.rtt_ms, 1, " ms");
      document.getElementById("m-rtt-p95").textContent = U.fmt(G.percentil(rttSesion, 95), 1, " ms");
    }
    if (obu.solicitud && inicioSolicitud[obu.solicitud] === undefined) inicioSolicitud[obu.solicitud] = obu.ts;
  }

  function aplicarEventoLazo(e) {
    const clases = [e.origen];
    const m = /^(M[123])/.exec(e.frase);
    if (m) clases.push(m[1]);
    const idCorto = e.id_solicitud && e.id_solicitud !== "-" ? e.id_solicitud.slice(-8) : "";
    const html = `<span class="hora">${U.horaDe(e.ts)}</span><span class="origen">${e.origen}</span> `
      + (idCorto ? `<span class="id">[${idCorto}]</span> ` : "") + (m ? `<span class="tipo">${m[1]}</span> ` : "")
      + e.frase.replace(/^M[123]\s*/, "");
    U.agregarLinea(document.getElementById("registro-eventos"), html, clases.join(" "));

    if (/NUEVA SOLICITUD/.test(e.frase)) { m1Enviados++; }
    if (/recibe M1 nueva/.test(e.frase)) { m1Recibidos++; }
    if (m1Enviados) document.getElementById("m-pdr").textContent = U.fmt(Math.min(1, m1Recibidos / m1Enviados), 3);

    if (/NUEVA SOLICITUD/.test(e.frase) && e.id_solicitud) {
      inicioSolicitud[e.id_solicitud] = e.ts;
    }
    // L aproximada = decision de la RSU (reloj Pi) - M1 nueva (reloj OBU):
    // cruza dos relojes, igual que t_V2I en scripts/analisis/lazo_emulado.py
    // (ver docs/MEDICION_LATENCIA.md); esta vista es solo un vistazo rapido,
    // la L con rigor estadistico esta en la pantalla "Ensayos y metricas".
    const esDecision = /escribe la prioridad|ESPERA el fin del despeje/.test(e.frase);
    if (esDecision && e.id_solicitud && inicioSolicitud[e.id_solicitud] !== undefined) {
      const l_ms = (e.ts - inicioSolicitud[e.id_solicitud]) * 1000;
      if (l_ms >= 0) document.getElementById("m-latencia").textContent = U.fmt(l_ms, 0, " ms");
    }
  }

  function aplicarMensajeMqtt(m) {
    const d = m.datos || {};
    const tipo = d.tipo || (m.tema === "rsu/v2i/solicitud_prioridad" ? "legado" : "?");
    const idCorto = d.id_solicitud ? String(d.id_solicitud).slice(-8) : "";
    let detalle = "";
    if (tipo === "M1") detalle = `${d.interseccion_id || ""}/${d.acceso || ""} · ${d.velocidad_kmh ?? ""} km/h · seq ${d.seq}`;
    else if (tipo === "M2") detalle = `${d.estado || ""}${d.fase ? " · fase " + d.fase : ""}`;
    else if (tipo === "M3") detalle = `motivo ${d.motivo || ""}`;
    const html = `<span class="hora">${U.horaDe(m.t)}</span><span class="tipo">${tipo}</span> `
      + `<span class="id">${idCorto}</span> <span>${m.tema}</span> — ${detalle}`;
    U.agregarLinea(document.getElementById("registro-mqtt"), html, tipo);
  }

  function aplicarProcesoLinea(p) {
    const estado = document.getElementById("prueba-estado");
    estado.textContent = `[${p.nombre}] ${p.linea}`;
  }

  function aplicarProceso(p) {
    const estado = document.getElementById("prueba-estado");
    const btnDetener = document.getElementById("btn-detener-prueba");
    if (p.accion === "iniciado") {
      estado.textContent = `Prueba "${p.nombre}" iniciada...`;
      btnDetener.disabled = false;
      btnDetener.dataset.prueba = p.nombre;
      document.querySelectorAll("#botonera-pruebas button[data-prueba]").forEach((b) => (b.disabled = true));
    } else if (p.accion === "terminado" || p.accion === "error") {
      estado.textContent = `Prueba "${p.nombre}" terminada (código ${p.codigo ?? "?"}).`;
      btnDetener.disabled = true;
      document.querySelectorAll("#botonera-pruebas button[data-prueba]").forEach((b) => (b.disabled = false));
    }
  }

  function configurarPausaRegistros() {
    document.querySelectorAll(".registro").forEach((r) => {
      r.addEventListener("mouseenter", () => (r.dataset.pausado = "1"));
      r.addEventListener("mouseleave", () => { r.dataset.pausado = "0"; r.dataset.pendientes = "0"; });
    });
  }

  function configurarBotonera() {
    document.querySelectorAll("#botonera-pruebas button[data-prueba]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try { await U.fetchJSON(`/api/pruebas/${btn.dataset.prueba}/iniciar`, { method: "POST" }); }
        catch (e) { alert(e.message); }
      });
    });
    document.getElementById("btn-detener-prueba").addEventListener("click", async (ev) => {
      const nombre = ev.target.dataset.prueba;
      try { await U.fetchJSON(`/api/pruebas/${nombre}/detener`, { method: "POST" }); } catch (e) { alert(e.message); }
    });
  }

  async function init() {
    await Consola.mapa.cargar();
    configurarPausaRegistros();
    configurarBotonera();

    const foto = await U.fetchJSON("/api/estado");
    aplicarMqttEstado({ conectado: foto.mqtt.conectado });
    aplicarSemaforo(foto.snmp.semaforo);
    aplicarTablaPrs(foto.snmp.tabla_prs);
    aplicarObu(foto.obu);
    aplicarBanco(foto.banco);
    foto.eventos_lazo.slice().reverse().forEach(aplicarEventoLazo);
    foto.mqtt.mensajes.slice().reverse().forEach(aplicarMensajeMqtt);

    Consola.sse.on("mqtt_estado", aplicarMqttEstado);
    Consola.sse.on("mqtt", (ev) => aplicarMensajeMqtt(ev.datos));
    Consola.sse.on("snmp_semaforo", (ev) => aplicarSemaforo(ev.datos));
    Consola.sse.on("snmp_prs", (ev) => aplicarTablaPrs(ev.datos));
    Consola.sse.on("obu", (ev) => aplicarObu(ev.datos));
    Consola.sse.on("evento_lazo", (ev) => aplicarEventoLazo(ev.datos));
    Consola.sse.on("banco", (ev) => aplicarBanco(ev.datos));
    Consola.sse.on("proceso", (ev) => aplicarProceso(ev.datos));
    Consola.sse.on("proceso_linea", (ev) => aplicarProcesoLinea(ev.datos));
  }

  window.Consola.monitoreo = { init };
})();
