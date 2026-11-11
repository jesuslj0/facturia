/* Listados: panel de filtros desplegable y filas clicables. */
(function () {
    const toggle = document.getElementById("filters-toggle");
    const panel = document.getElementById("filter-panel");
    if (toggle && panel) {
        toggle.addEventListener("click", function () {
            const open = panel.hidden;
            panel.hidden = !open;
            toggle.setAttribute("aria-expanded", open ? "true" : "false");
        });
    }
    document.querySelectorAll(".clickable-row").forEach(function (row) {
        row.addEventListener("click", function (e) {
            if (e.target.closest("a, button, input, select, label")) return;
            window.location = this.dataset.href;
        });
    });
})();
