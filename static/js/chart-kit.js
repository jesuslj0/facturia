/* Utilidades compartidas por los gráficos de Inicio y Métricas: mismo aspecto en todos. */
window.ChartKit = (function () {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const eur = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const int = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 });
    const tone = (name) => css("--color-" + name) || css("--muted-color");

    // Contadores animados: el texto del servidor es el valor final y el respaldo
    function countUp(root) {
        (root || document).querySelectorAll("[data-count]").forEach(function (el) {
            const target = parseFloat(el.dataset.count);
            if (reduce || !isFinite(target) || target === 0) return;
            const fmt = el.dataset.format === "currency" ? (v) => eur.format(v) + " €"
                      : el.dataset.format === "percent" ? (v) => eur.format(v) + " %"
                      : (v) => int.format(v);
            const t0 = performance.now(), dur = 900;
            (function frame(now) {
                const p = Math.min(1, (now - t0) / dur);
                el.textContent = fmt(target * (1 - Math.pow(1 - p, 3)));
                if (p < 1) requestAnimationFrame(frame);
            })(t0);
        });
    }

    function setup() {
        if (!window.Chart) return false;
        Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
        Chart.defaults.color = css("--muted-color");
        return true;
    }

    const gradient = (ctx, color, height) => {
        const g = ctx.createLinearGradient(0, 0, 0, height || 260);
        g.addColorStop(0, color + "55");
        g.addColorStop(1, color + "00");
        return g;
    };

    const tooltip = (extra) => Object.assign({
        backgroundColor: css("--card-bg-color"), borderColor: "rgba(255,255,255,.12)", borderWidth: 1,
        titleColor: css("--body-fg-color"), bodyColor: css("--body-fg-color"), padding: 10,
    }, extra || {});

    // Opciones comunes de ejes/animación/leyenda para todos los gráficos cartesianos
    function cartesian(extra) {
        return Object.assign({
            responsive: true,
            maintainAspectRatio: false,
            animation: reduce ? false : { duration: 1000, easing: "easeOutCubic" },
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 16 } },
                tooltip: tooltip({ callbacks: { label: (c) => " " + c.dataset.label + ": " + eur.format(c.parsed.y) + " €" } }),
            },
            scales: {
                x: { grid: { display: false }, border: { display: false } },
                y: { beginAtZero: true, border: { display: false }, grid: { color: "rgba(255,255,255,.06)" },
                     ticks: { callback: (v) => int.format(v) } },
            },
        }, extra || {});
    }

    return { reduce, css, eur, int, tone, countUp, setup, gradient, tooltip, cartesian };
})();
