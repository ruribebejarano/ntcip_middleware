// Pantalla "Ensayos y metricas": lee resultados/lazo_emulado/<corrida>/ a
// traves de /api/ensayos/*, que a su vez llama a scripts/analisis/
// lazo_emulado.py y scripts/analisis/graficos_campana.py -- las MISMAS
// definiciones que los scripts de linea de comandos, nunca recalculadas
// aqui.
window.Consola = window.Consola || {};

(function () {
  const U = Consola.utils, G = Consola.graficos;
  let corridas = [];

  function fmtResumen(r, unidad) {
    if (!r || !r.n) return "sin datos";
    return `n=${r.n} · mediana ${r.mediana.toFixed(1)}${unidad} · p95 ${r.p95.toFixed(1)}${unidad} · máx ${r.max.toFixed(1)}${unidad}`;
  }

  function tarjeta(etiqueta, valor, nota) {
    const d = U.el("div", { class: "metrica" }, [
      U.el("div", { class: "metrica-etiqueta", texto: etiqueta }),
      U.el("div", { class: "metrica-valor", texto: valor }),
    ]);
    if (nota) d.appendChild(U.el("div", { class: "metrica-nota", texto: nota }));
    return d;
  }

  function renderMetricas(g) {
    const cont = document.getElementById("fila-metricas-ensayos");
    cont.innerHTML = "";
    const l = g.L_ms || {};
    cont.appendChild(tarjeta("L (RNF-01)", l.n ? `${l.mediana.toFixed(0)} ms` : "—",
      l.n ? `p95 ${l.p95.toFixed(0)} ms · ${g.rnf01_cumple_p95 ? "CUMPLE" : "NO CUMPLE"} (≤1000 ms)` : "sin datos"));
    cont.appendChild(tarjeta("RTT M1/M2", g.rtt_m1_m2_ms.n ? `${g.rtt_m1_m2_ms.mediana.toFixed(1)} ms` : "—",
      g.rtt_m1_m2_ms.n ? `p95 ${g.rtt_m1_m2_ms.p95.toFixed(1)} ms (n=${g.rtt_m1_m2_ms.n})` : ""));
    cont.appendChild(tarjeta("T_desp (RF-06)", g.T_desp_ms.n ? `${(g.T_desp_ms.mediana / 1000).toFixed(1)} s` : "sin encolamientos",
      g.T_desp_ms.n ? `n=${g.T_desp_ms.n}` : ""));
    cont.appendChild(tarjeta("PDR", g.pdr != null ? g.pdr.toFixed(3) : "—", `${g.mensajes_recibidos ?? 0}/${g.mensajes_enviados ?? 0} mensajes`));
    cont.appendChild(tarjeta("Acierto de acceso", g.acierto_acceso != null ? g.acierto_acceso.toFixed(3) : "—", ""));
    cont.appendChild(tarjeta("Solicitudes", g.solicitudes, `concedidas ${g.resultados.concedida} · sin verde ${g.resultados.sin_verde} · rechazadas ${g.resultados.rechazada} · sin resp. ${g.resultados.sin_respuesta}`));
  }

  function renderGraficos(m) {
    G.dibujarCDF(document.getElementById("g-cdf"), m.rtt, "RTT M1/M2 (ms)");
    G.dibujarTramos(document.getElementById("g-tramos"), [
      { etiqueta: "t_V2I", valores: m.t_V2I, color: G.COLOR.azul },
      { etiqueta: "t_RSU", valores: m.t_RSU, color: G.COLOR.violeta },
      { etiqueta: "L", valores: m.L, color: G.COLOR.naranja },
    ]);
    G.dibujarDespeje(document.getElementById("g-despeje"), [
      { etiqueta: "Verde/rojo", valores: m.despeje["verde/rojo"], color: G.COLOR.aqua },
      { etiqueta: "Ámbar/todo rojo", valores: m.despeje["ambar/todo rojo"], color: G.COLOR.naranja },
    ]);
    G.dibujarSerie(document.getElementById("g-serie"), m.series);
  }

  function renderTablaSolicitudes(filas) {
    const cols = ["id_solicitud", "interseccion_id", "acceso", "resultado", "L_ms", "rtt_mediana_ms", "t_V2I_ms", "T_desp_ms", "acierto_acceso"];
    const thead = document.querySelector("#tabla-solicitudes thead");
    const tbody = document.querySelector("#tabla-solicitudes tbody");
    thead.innerHTML = `<tr>${cols.map((c) => `<th data-col="${c}">${c}</th>`).join("")}</tr>`;
    function dibujar(datos) {
      tbody.innerHTML = datos.map((f) => `<tr>${cols.map((c) => {
        const v = f[c];
        return `<td>${v == null ? "—" : (typeof v === "number" ? v.toFixed(2) : v)}</td>`;
      }).join("")}</tr>`).join("");
    }
    dibujar(filas);
    thead.querySelectorAll("th").forEach((th) => {
      th.addEventListener("click", () => {
        const col = th.dataset.col;
        const asc = th.dataset.asc !== "1";
        thead.querySelectorAll("th").forEach((t) => delete t.dataset.asc);
        th.dataset.asc = asc ? "1" : "0";
        const ordenado = [...filas].sort((a, b) => {
          const va = a[col], vb = b[col];
          if (va == null) return 1; if (vb == null) return -1;
          return (va > vb ? 1 : va < vb ? -1 : 0) * (asc ? 1 : -1);
        });
        dibujar(ordenado);
      });
    });
  }

  async function mostrarCorrida(nombre) {
    const datos = await U.fetchJSON(`/api/ensayos/corridas/${encodeURIComponent(nombre)}`);
    document.getElementById("config-corrida").textContent = JSON.stringify(datos.config, null, 2);
    renderMetricas(datos.global);
    renderGraficos(datos.graficos);
    renderTablaSolicitudes(datos.por_solicitud);
  }

  function poblarSelectores() {
    const sel = document.getElementById("select-corrida");
    const selCmp = document.getElementById("select-comparar");
    sel.innerHTML = corridas.map((c) => `<option value="${c.nombre}">${c.nombre}</option>`).join("");
    selCmp.innerHTML = corridas.map((c) => `<option value="${c.nombre}">${c.nombre}</option>`).join("");
  }

  async function cargarCorridas() {
    corridas = await U.fetchJSON("/api/ensayos/corridas");
    poblarSelectores();
    if (corridas.length) await mostrarCorrida(corridas[0].nombre);
  }

  function renderEtiquetasComparar() {
    const sel = document.getElementById("select-comparar");
    const cont = document.getElementById("etiquetas-comparar");
    const elegidos = [...sel.selectedOptions].map((o) => o.value);
    cont.innerHTML = "";
    elegidos.forEach((nombre) => {
      const input = U.el("input", { type: "text", "data-corrida": nombre, placeholder: "etiqueta", value: nombre });
      cont.appendChild(input);
    });
  }

  function renderComparacion(datos) {
    const cont = document.getElementById("rejilla-comparar");
    cont.innerHTML = "";
    const svgCdf = U.el("svg", { class: "grafico", viewBox: "0 0 420 260" });
    cont.appendChild(U.el("div", { class: "panel" }, [U.el("div", { class: "panel-titulo", texto: "CDF del RTT por condición (eje log.)" }), svgCdf]));
    G.dibujarCDFComparada(svgCdf, datos.condiciones.map((c) => ({ etiqueta: c.etiqueta, valores: c.graficos.rtt })));

    ["t_V2I", "t_RSU", "L"].forEach((clave, idx) => {
      const svg = U.el("svg", { class: "grafico", viewBox: "0 0 420 260" });
      const paleta = [G.COLOR.azul, G.COLOR.naranja, G.COLOR.aqua, G.COLOR.violeta];
      cont.appendChild(U.el("div", { class: "panel" }, [U.el("div", { class: "panel-titulo", texto: `${clave} por condición` }), svg]));
      G.dibujarTramos(svg, datos.condiciones.map((c, i) => ({ etiqueta: c.etiqueta, valores: c.graficos[clave], color: paleta[i % paleta.length] })));
    });

    const thead = document.querySelector("#tabla-comparar thead");
    const tbody = document.querySelector("#tabla-comparar tbody");
    thead.innerHTML = "<tr><th>Condición</th><th>RTT mediana</th><th>RTT p95</th><th>L mediana</th><th>L p95</th><th>PDR</th><th>PDR IC95% Wilson</th></tr>";
    tbody.innerHTML = datos.condiciones.map((c) => {
      const rtt = c.global.rtt_m1_m2_ms, l = c.global.L_ms, w = c.pdr_wilson;
      return `<tr><td>${c.etiqueta}</td><td>${rtt.n ? rtt.mediana.toFixed(1) + " ms" : "—"}</td>`
        + `<td>${rtt.n ? rtt.p95.toFixed(1) + " ms" : "—"}</td>`
        + `<td>${l.n ? l.mediana.toFixed(0) + " ms" : "—"}</td><td>${l.n ? l.p95.toFixed(0) + " ms" : "—"}</td>`
        + `<td>${c.global.pdr != null ? c.global.pdr.toFixed(3) : "—"}</td>`
        + `<td>${w.p != null ? `[${w.inferior.toFixed(3)}, ${w.superior.toFixed(3)}]` : "—"}</td></tr>`;
    }).join("");
  }

  function init() {
    document.getElementById("select-corrida").addEventListener("change", (ev) => mostrarCorrida(ev.target.value));
    document.getElementById("btn-refrescar-corridas").addEventListener("click", cargarCorridas);
    document.getElementById("select-comparar").addEventListener("change", renderEtiquetasComparar);
    document.getElementById("btn-comparar").addEventListener("click", async () => {
      const inputs = [...document.querySelectorAll("#etiquetas-comparar input")];
      if (inputs.length < 2) { alert("Elegir al menos dos corridas (Ctrl+click) en la lista."); return; }
      const query = inputs.map((i) => `${i.dataset.corrida}:${encodeURIComponent(i.value || i.dataset.corrida)}`).join(",");
      const datos = await U.fetchJSON(`/api/ensayos/comparar?corridas=${query}`);
      renderComparacion(datos);
    });
    document.getElementById("btn-exportar-figuras").addEventListener("click", async () => {
      const nombre = document.getElementById("select-corrida").value;
      const nota = document.getElementById("input-nota-export").value;
      const estado = document.getElementById("exportar-estado");
      estado.textContent = "Generando figuras y tabla LaTeX...";
      try {
        const r = await U.fetchJSON(`/api/ensayos/corridas/${encodeURIComponent(nombre)}/exportar?nota=${encodeURIComponent(nota)}`, { method: "POST" });
        estado.textContent = `Listo: ${r.carpeta}`;
      } catch (e) {
        estado.textContent = `Error: ${e.message}`;
      }
    });
    cargarCorridas().catch((e) => {
      document.getElementById("config-corrida").textContent = `No hay corridas todavia (${e.message}). Correr scripts/campanas/lazo_emulado.py primero.`;
    });
  }

  window.Consola.ensayos = { init };
})();
