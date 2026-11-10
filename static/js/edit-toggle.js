/* Tarjetas con modo lectura / edición.
   <div data-editable [data-start-editing="panel"]>
     botones [data-edit="panel"] y [data-cancel]; paneles [data-panel="panel"].
   Sin panel activo se ve el bloque de lectura (.view-mode). */
document.querySelectorAll("[data-editable]").forEach(function (card) {
    const set = (panel) => {
        if (panel) card.dataset.mode = panel; else delete card.dataset.mode;
        if (panel) {
            const first = card.querySelector('[data-panel="' + panel + '"] input:not([type=hidden]), [data-panel="' + panel + '"] select');
            if (first) first.focus();
        }
    };
    card.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => set(b.dataset.edit)));
    card.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", () => {
        const form = b.closest("form");
        if (form) form.reset();
        set(null);
    }));
    set(card.dataset.startEditing || null);
});
