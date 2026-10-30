(function () {
  function configurarMenu() {
    document.querySelectorAll(".item-menu").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".item-menu").forEach((b) => b.classList.remove("activo"));
        document.querySelectorAll(".vista").forEach((v) => v.classList.remove("activa"));
        btn.classList.add("activo");
        document.getElementById(`vista-${btn.dataset.vista}`).classList.add("activa");
      });
    });
  }

  function relojLocal() {
    setInterval(() => {
      document.getElementById("hora-local").textContent = new Date().toLocaleTimeString("es-PE", { hour12: false });
    }, 1000);
  }

  window.addEventListener("DOMContentLoaded", async () => {
    configurarMenu();
    relojLocal();
    Consola.sse.conectar();
    await Consola.mapa.cargar(["svg-mapa", "svg-mapa-mision"]);
    const demo = await Consola.mision.init();
    await Consola.monitoreo.init();
    // Con varias RSU (lanzador de scripts/demo/), se abre directo en la mision.
    if (demo.modo_multi_rsu) document.querySelector('.item-menu[data-vista="mision"]').click();
    Consola.ensayos.init();
    Consola.comandos.init();
  });
})();
