/* Inicio: números que cuentan, gráfico de ingresos/gastos y filas clicables. */
(function () {
    const K = window.ChartKit;
    K.countUp();

    const dataEl = document.getElementById("home-chart");
    const canvas = document.getElementById("homeChart");
    if (dataEl && canvas && K.setup()) {
        const d = JSON.parse(dataEl.textContent);
        const ctx = canvas.getContext("2d");
        const success = K.tone("success"), danger = K.tone("danger");
        const h = canvas.parentElement.clientHeight;
        const line = (label, data, color) => ({
            label, data, borderColor: color, backgroundColor: K.gradient(ctx, color, h), fill: true,
            tension: 0.4, borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 6,
        });
        new Chart(ctx, {
            type: "line",
            data: { labels: d.labels, datasets: [line("Ingresos", d.income, success), line("Gastos", d.expense, danger)] },
            options: K.cartesian(),
        });
    }

    document.querySelectorAll(".clickable-row").forEach(function (row) {
        row.addEventListener("click", function (e) {
            if (e.target.closest("a, button")) return;
            window.location = this.dataset.href;
        });
    });
})();
