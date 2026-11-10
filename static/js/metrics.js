/* Métricas: pestañas, contadores y gráficos con el mismo aspecto que Inicio (ChartKit). */
(function () {
    const K = window.ChartKit;
    K.countUp();

    // --- Pestañas del desglose por origen ---
    document.querySelectorAll("[data-tabs]").forEach(function (box) {
        const tabs = box.querySelectorAll("[data-tab]");
        tabs.forEach(function (btn) {
            btn.addEventListener("click", function () {
                tabs.forEach((b) => {
                    const on = b === btn;
                    b.classList.toggle("active", on);
                    b.setAttribute("aria-selected", on ? "true" : "false");
                });
                box.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== btn.dataset.tab; });
            });
        });
    });

    const dataEl = document.getElementById("metrics-data");
    if (!dataEl || !K.setup()) return;
    const d = JSON.parse(dataEl.textContent);
    const success = K.tone("success"), danger = K.tone("danger"), info = K.tone("info");

    // --- Evolución: ingresos / gastos / beneficio ---
    const evo = document.getElementById("evolutionChart");
    if (evo && d.monthly.length) {
        const ctx = evo.getContext("2d");
        const h = evo.parentElement.clientHeight;
        const line = (label, key, color, extra) => Object.assign({
            label, data: d.monthly.map((r) => r[key]), borderColor: color, backgroundColor: K.gradient(ctx, color, h),
            fill: true, tension: 0.4, borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 6,
        }, extra || {});
        new Chart(ctx, {
            type: "line",
            data: {
                labels: d.monthly.map((r) => r.period),
                datasets: [
                    line("Ingresos", "income", success),
                    line("Gastos", "expense", danger),
                    line("Beneficio", "profit", info, { fill: false, borderDash: [6, 5], borderWidth: 2 }),
                ],
            },
            options: K.cartesian(),
        });
    }

    // --- Por trimestre (barras agrupadas, mismos colores) ---
    const qc = document.getElementById("quartersChart");
    if (qc && d.quarters.length) {
        new Chart(qc.getContext("2d"), {
            type: "bar",
            data: {
                labels: d.quarters.map((q) => q.period),
                datasets: [
                    { label: "Ingresos", data: d.quarters.map((q) => q.income), backgroundColor: success, borderRadius: 6, maxBarThickness: 36 },
                    { label: "Gastos", data: d.quarters.map((q) => q.expense), backgroundColor: danger, borderRadius: 6, maxBarThickness: 36 },
                ],
            },
            options: K.cartesian(),
        });
    }

    // --- Decisiones de revisión (dona con total al centro) ---
    const dc = document.getElementById("decisionsChart");
    if (dc) {
        const center = document.getElementById("donutCenter");
        const values = d.status.map((s) => s.value);
        const total = values.reduce((a, b) => a + b, 0);
        const show = (i) => {
            center.innerHTML = i == null
                ? "<strong>" + K.int.format(total) + "</strong><small>documentos</small>"
                : "<strong>" + K.int.format(values[i]) + "</strong><small>" + d.status[i].label + "</small>";
        };
        show(null);
        new Chart(dc.getContext("2d"), {
            type: "doughnut",
            data: {
                labels: d.status.map((s) => s.label),
                datasets: [{ data: values, backgroundColor: d.status.map((s) => K.tone(s.tone)), borderColor: K.css("--card-bg-color"), borderWidth: 3, hoverOffset: 6 }],
            },
            options: {
                responsive: true, maintainAspectRatio: false, cutout: "72%",
                animation: K.reduce ? false : { duration: 1000, easing: "easeOutCubic" },
                plugins: {
                    legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 14 } },
                    tooltip: K.tooltip({ callbacks: { label: (c) => " " + c.label + ": " + c.parsed + " (" + Math.round(c.parsed / total * 100) + " %)" } }),
                },
                onHover: (evt, els) => show(els.length ? els[0].index : null),
            },
        });
        dc.addEventListener("mouseleave", () => show(null));
    }
})();
