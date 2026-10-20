// Graficos nativos en SVG (sin libreria externa: la consola debe funcionar
// sin internet, ver docs/CONSOLA.md). Mismas definiciones y paleta que
// scripts/analisis/graficos_campana.py: AZUL/NARANJA/AQUA/VIOLETA/INK2.
window.Consola = window.Consola || {};

(function () {
  const COLOR = { azul: "#2a78d6", naranja: "#eb6834", aqua: "#1baf7a", violeta: "#6250d6", tinta: "#52514e" };
  const W = 420, H = 260, M = { top: 18, right: 16, bottom: 34, left: 42 };

  // Percentil por rango mas cercano (q en 0..100) -- igual que
  // scripts/analisis/lazo_emulado.py:percentil, para que coincidan los
  // valores mostrados aqui con los que calcula ese script.
  function percentil(valores, q) {
    if (!valores || !valores.length) return null;
    const v = [...valores].sort((a, b) => a - b);
    const k = Math.max(0, Math.min(v.length - 1, Math.ceil((q / 100) * v.length) - 1));
    return v[k];
  }

  function limpiar(svg) {
    svg.innerHTML = "";
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  }

  function svgEl(tag, attrs) {
    const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
  }

  function ejes(svg, xMin, xMax, yMin, yMax, xLabel, yLabel) {
    const g = svgEl("g", {});
    g.appendChild(svgEl("line", { x1: M.left, y1: H - M.bottom, x2: W - M.right, y2: H - M.bottom, stroke: "#d6d3d1" }));
    g.appendChild(svgEl("line", { x1: M.left, y1: M.top, x2: M.left, y2: H - M.bottom, stroke: "#d6d3d1" }));
    const txtX = svgEl("text", { x: (M.left + W - M.right) / 2, y: H - 6, "text-anchor": "middle", fill: "#57534e", "font-size": "10" });
    txtX.textContent = xLabel || "";
    const txtY = svgEl("text", { x: 12, y: (M.top + H - M.bottom) / 2, "text-anchor": "middle", fill: "#57534e", "font-size": "10", transform: `rotate(-90 12 ${(M.top + H - M.bottom) / 2})` });
    txtY.textContent = yLabel || "";
    g.appendChild(txtX); g.appendChild(txtY);
    svg.appendChild(g);
  }

  function escalaLineal(dominioMin, dominioMax, rangoMin, rangoMax) {
    const d = dominioMax - dominioMin || 1;
    return (v) => rangoMin + ((v - dominioMin) / d) * (rangoMax - rangoMin);
  }

  function sinDatos(svg, mensaje) {
    limpiar(svg);
    svg.appendChild(svgEl("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: "#57534e", "font-size": "12" })).textContent = mensaje || "sin datos";
  }

  function dibujarCDF(svg, valores, etiquetaX) {
    if (!valores || !valores.length) return sinDatos(svg);
    limpiar(svg);
    const v = [...valores].sort((a, b) => a - b);
    const n = v.length;
    const x = escalaLineal(v[0], v[n - 1], M.left, W - M.right);
    const y = escalaLineal(0, 1, H - M.bottom, M.top);
    ejes(svg, v[0], v[n - 1], 0, 1, etiquetaX || "valor (ms)", "Prob. acumulada");
    let d = `M ${x(v[0])} ${y(0)}`;
    v.forEach((val, i) => { d += ` L ${x(val)} ${y((i + 1) / n)}`; });
    svg.appendChild(svgEl("path", { d, fill: "none", stroke: COLOR.azul, "stroke-width": 1.6 }));
    [50, 95].forEach((q, idx) => {
      const p = percentil(v, q);
      svg.appendChild(svgEl("line", { x1: x(p), y1: M.top, x2: x(p), y2: H - M.bottom, stroke: "#52514e", "stroke-width": .7, "stroke-dasharray": idx ? "2,2" : "5,3" }));
      const t = svgEl("text", { x: x(p) + 3, y: M.top + 10 + idx * 12, "font-size": "9.5", fill: "#1c1917" });
      t.textContent = `p${q}=${p.toFixed(1)}`;
      svg.appendChild(t);
    });
    const leyenda = svgEl("text", { x: W - M.right, y: M.top - 4, "text-anchor": "end", "font-size": "9.5", fill: "#57534e" });
    leyenda.textContent = `n=${n}`;
    svg.appendChild(leyenda);
  }

  function caja(svg, x, ancho, valores, color) {
    if (!valores.length) return;
    const q1 = percentil(valores, 25), q2 = percentil(valores, 50), q3 = percentil(valores, 75);
    const yMax = Math.max(...valores, 1), yMin = 0;
    const y = escalaLineal(yMin, yMax * 1.08, H - M.bottom, M.top);
    svg.appendChild(svgEl("rect", { x: x - ancho / 2, y: y(q3), width: ancho, height: Math.max(1, y(q1) - y(q3)), fill: color + "33", stroke: color }));
    svg.appendChild(svgEl("line", { x1: x - ancho / 2, y1: y(q2), x2: x + ancho / 2, y2: y(q2), stroke: "#1c1917", "stroke-width": 1.3 }));
    valores.forEach((val, i) => {
      const jit = x + ancho * 0.35 * Math.sin(i * 2.399);
      svg.appendChild(svgEl("circle", { cx: jit, cy: y(val), r: 2.1, fill: color, opacity: .85 }));
    });
    return y;
  }

  function dibujarTramos(svg, grupos) {
    const activos = grupos.filter((g) => g.valores && g.valores.length);
    if (!activos.length) return sinDatos(svg);
    limpiar(svg);
    const yMax = Math.max(1, ...activos.flatMap((g) => g.valores));
    const y = escalaLineal(0, yMax * 1.08, H - M.bottom, M.top);
    ejes(svg, 0, 0, 0, yMax, "", "Latencia (ms)");
    const ancho = (W - M.left - M.right) / (activos.length + 1);
    activos.forEach((g, i) => {
      const cx = M.left + ancho * (i + 1);
      caja(svg, cx, ancho * 0.55, g.valores, g.color);
      const t = svgEl("text", { x: cx, y: H - M.bottom + 14, "text-anchor": "middle", "font-size": "10.5", fill: "#1c1917" });
      t.textContent = g.etiqueta;
      svg.appendChild(t);
    });
    for (let f = 0; f <= 4; f++) {
      const val = (yMax * f) / 4;
      const ty = svgEl("text", { x: M.left - 5, y: y(val) + 3, "text-anchor": "end", "font-size": "9", fill: "#57534e" });
      ty.textContent = val.toFixed(0);
      svg.appendChild(ty);
    }
  }

  function dibujarDespeje(svg, grupos) {
    const activos = grupos.filter((g) => g.valores && g.valores.length);
    if (!activos.length) return sinDatos(svg, "sin esperas de despeje registradas");
    limpiar(svg);
    const yMax = Math.max(0.5, ...grupos.flatMap((g) => g.valores || []));
    const y = escalaLineal(-0.1, yMax * 1.15, H - M.bottom, M.top);
    ejes(svg, 0, 0, 0, yMax, "", "T_desp (s)");
    const ancho = (W - M.left - M.right) / (grupos.length + 1);
    grupos.forEach((g, i) => {
      const cx = M.left + ancho * (i + 1);
      const t = svgEl("text", { x: cx, y: H - M.bottom + 14, "text-anchor": "middle", "font-size": "9.5", fill: "#1c1917" });
      t.textContent = g.etiqueta;
      svg.appendChild(t);
      if (!g.valores || !g.valores.length) return;
      g.valores.forEach((val, k) => {
        const jit = cx + 14 * Math.sin(k * 2.399);
        svg.appendChild(svgEl("circle", { cx: jit, cy: y(val), r: 2.4, fill: g.color, opacity: .9 }));
      });
      const med = percentil(g.valores, 50);
      svg.appendChild(svgEl("line", { x1: cx - 16, y1: y(med), x2: cx + 16, y2: y(med), stroke: "#1c1917", "stroke-width": 1.3 }));
    });
  }

  function dibujarSerie(svg, series) {
    if (!series || !series.length) return sinDatos(svg);
    limpiar(svg);
    const largo = Math.max(...series.map((s) => s.length));
    const todos = series.flat();
    const yMax = Math.max(1, ...todos);
    const x = escalaLineal(1, largo, M.left, W - M.right);
    const y = escalaLineal(0, yMax * 1.08, H - M.bottom, M.top);
    ejes(svg, 1, largo, 0, yMax, "Mensaje dentro de la solicitud", "RTT (ms)");
    series.forEach((s) => {
      let d = "";
      s.forEach((v, i) => { d += (i === 0 ? "M" : "L") + ` ${x(i + 1)} ${y(v)}`; });
      svg.appendChild(svgEl("path", { d, fill: "none", stroke: COLOR.azul, "stroke-width": 1, opacity: .35 }));
    });
    const mediana = [];
    for (let i = 0; i < largo; i++) {
      const col = series.filter((s) => s.length > i).map((s) => s[i]);
      mediana.push(percentil(col, 50));
    }
    let d = "";
    mediana.forEach((v, i) => { d += (i === 0 ? "M" : "L") + ` ${x(i + 1)} ${y(v)}`; });
    svg.appendChild(svgEl("path", { d, fill: "none", stroke: "#1c1917", "stroke-width": 1.6 }));
  }

  // CDF superpuesta de varias condiciones (pestana "Comparar condiciones"),
  // con eje x logaritmico (4G puede estar un orden de magnitud por encima
  // de Wi-Fi).
  function dibujarCDFComparada(svg, condiciones) {
    const activas = condiciones.filter((c) => c.valores && c.valores.length);
    if (!activas.length) return sinDatos(svg);
    limpiar(svg);
    const todos = activas.flatMap((c) => c.valores).filter((v) => v > 0);
    const xMin = Math.max(0.1, Math.min(...todos)), xMax = Math.max(...todos);
    const logX = escalaLineal(Math.log10(xMin), Math.log10(xMax), M.left, W - M.right);
    const y = escalaLineal(0, 1, H - M.bottom, M.top);
    ejes(svg, xMin, xMax, 0, 1, "RTT (ms, escala log.)", "Prob. acumulada");
    const paleta = [COLOR.azul, COLOR.naranja, COLOR.aqua, COLOR.violeta];
    activas.forEach((c, idx) => {
      const v = [...c.valores].filter((x) => x > 0).sort((a, b) => a - b);
      const n = v.length;
      let d = `M ${logX(Math.log10(v[0]))} ${y(0)}`;
      v.forEach((val, i) => { d += ` L ${logX(Math.log10(val))} ${y((i + 1) / n)}`; });
      svg.appendChild(svgEl("path", { d, fill: "none", stroke: paleta[idx % paleta.length], "stroke-width": 1.6 }));
      const t = svgEl("text", { x: W - M.right, y: M.top + 10 + idx * 12, "text-anchor": "end", "font-size": "9.5", fill: paleta[idx % paleta.length] });
      t.textContent = `${c.etiqueta} (n=${n})`;
      svg.appendChild(t);
    });
  }

  window.Consola.graficos = {
    COLOR, percentil, dibujarCDF, dibujarTramos, dibujarDespeje, dibujarSerie, dibujarCDFComparada, sinDatos,
  };
})();
