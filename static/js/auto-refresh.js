/* Recarga la página mientras haya documentos en procesado: [data-autorefresh="segundos"]. */
(function () {
    const el = document.querySelector("[data-autorefresh]");
    if (!el) return;
    const seconds = Math.max(2, parseInt(el.dataset.autorefresh, 10) || 4);
    setTimeout(function tick() {
        // No interrumpir al usuario si está escribiendo en un formulario
        const a = document.activeElement;
        if (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return setTimeout(tick, seconds * 1000);
        window.location.reload();
    }, seconds * 1000);
})();
