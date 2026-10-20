window.Consola = window.Consola || {};

(function () {
  async function fetchJSON(url, opciones) {
    const r = await fetch(url, opciones);
    if (!r.ok) {
      const texto = await r.text().catch(() => "");
      throw new Error(`${url}: ${r.status} ${texto.slice(0, 300)}`);
    }
    return r.json();
  }

  function horaDe(tsEpochSeg) {
    const d = new Date(tsEpochSeg * 1000);
    return d.toLocaleTimeString("es-PE", { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
  }

  function fmt(valor, decimales = 1, sufijo = "") {
    if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
    return Number(valor).toFixed(decimales) + sufijo;
  }

  function el(tag, attrs, hijos) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => {
      if (k === "texto") e.textContent = v; else if (k === "html") e.innerHTML = v; else e.setAttribute(k, v);
    });
    (hijos || []).forEach((h) => e.appendChild(h));
    return e;
  }

  function limitarLineas(contenedor, max) {
    while (contenedor.children.length > max) contenedor.removeChild(contenedor.lastChild);
  }

  function agregarLinea(contenedor, html, clases, alPrincipio = true) {
    const div = document.createElement("div");
    div.className = "linea " + (clases || "");
    div.innerHTML = html;
    const pausado = contenedor.dataset.pausado === "1";
    if (pausado) {
      contenedor.dataset.pendientes = (parseInt(contenedor.dataset.pendientes || "0", 10) + 1).toString();
      return;
    }
    if (alPrincipio) contenedor.insertBefore(div, contenedor.firstChild);
    else contenedor.appendChild(div);
    limitarLineas(contenedor, 400);
  }

  window.Consola.utils = { fetchJSON, horaDe, fmt, el, agregarLinea, limitarLineas };
})();
