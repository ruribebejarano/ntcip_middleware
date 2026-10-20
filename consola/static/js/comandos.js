// Pantalla "Registro de comandos": lee /api/comandos (memoria + archivo
// resultados/consola/registro_comandos.jsonl, ver consola/backend/
// registro_comandos.py) y se actualiza en vivo con el evento SSE "comando".
window.Consola = window.Consola || {};

(function () {
  const U = Consola.utils;
  let filas = [];

  function resumenDe(f) {
    const c = f.comando;
    if (typeof c === "string") return c;
    if (c && typeof c === "object") {
      if (c.tema) return `${c.tema} ${c.payload && c.payload.tipo ? "(" + c.payload.tipo + ")" : ""}`;
      if (c.oid) return `${c.accion || "SNMP"} ${c.oid}`;
      if (c.oids) return `${c.accion || "SNMP"} ${c.oids.length} OID`;
      if (c.orden) return c.orden;
      if (c.accion && c.prueba) return `${c.accion} ${c.prueba}`;
      return JSON.stringify(c).slice(0, 90);
    }
    return String(c ?? "");
  }

  function render() {
    const tbody = document.querySelector("#tabla-comandos tbody");
    tbody.innerHTML = filas.map((f, i) => `<tr data-i="${i}"><td>${U.horaDe(f.ts)}</td>`
      + `<td>${f.origen} → ${f.destino}</td><td>${f.canal}</td><td>${resumenDe(f)}</td></tr>`).join("");
    tbody.querySelectorAll("tr").forEach((tr) => {
      tr.addEventListener("click", () => {
        tbody.querySelectorAll("tr").forEach((t) => t.classList.remove("fila-seleccionada"));
        tr.classList.add("fila-seleccionada");
        const f = filas[parseInt(tr.dataset.i, 10)];
        document.getElementById("detalle-comando").textContent = JSON.stringify(f, null, 2);
      });
    });
  }

  async function cargar() {
    const canal = document.getElementById("filtro-canal").value;
    const buscar = document.getElementById("filtro-texto").value;
    const qs = new URLSearchParams();
    if (canal) qs.set("canal", canal);
    if (buscar) qs.set("buscar", buscar);
    filas = await U.fetchJSON(`/api/comandos?${qs.toString()}`);
    render();
  }

  function agregarEnVivo(entrada) {
    const canalFiltro = document.getElementById("filtro-canal").value;
    const buscar = document.getElementById("filtro-texto").value.toLowerCase();
    if (canalFiltro && entrada.canal !== canalFiltro) return;
    if (buscar && !JSON.stringify(entrada).toLowerCase().includes(buscar)) return;
    filas.unshift(entrada);
    if (filas.length > 2000) filas.pop();
    render();
  }

  function init() {
    document.getElementById("btn-filtrar-comandos").addEventListener("click", cargar);
    document.getElementById("filtro-texto").addEventListener("keydown", (e) => { if (e.key === "Enter") cargar(); });
    cargar();
    Consola.sse.on("comando", (ev) => agregarEnVivo(ev.datos));
  }

  window.Consola.comandos = { init };
})();
