/* Formulario de movimiento: etiqueta Ingreso/Gasto según la categoría y nombre del recibo elegido. */
(function () {
    const form = document.getElementById("movement-form");
    if (!form) return;

    const select = form.querySelector('[name="category"]');
    const pill = document.getElementById("type-pill");
    const TONES = { "Gasto": "danger", "Ingreso": "success", "Inversión": "info", "Prestamo": "warning", "Préstamo": "warning" };
    function updatePill() {
        const text = select.options[select.selectedIndex] ? select.options[select.selectedIndex].text : "";
        const m = text.match(/\(([^)]+)\)\s*$/);
        pill.className = "type-pill badge-status";
        if (!m || !select.value) { pill.textContent = ""; return; }
        pill.classList.add("show", "tone-" + (TONES[m[1]] || "neutral"));
        pill.textContent = m[1] === "Ingreso" ? "Se sumará a los ingresos" : m[1] === "Gasto" ? "Se sumará a los gastos" : m[1];
    }
    select.addEventListener("change", updatePill);
    updatePill();

    const file = form.querySelector('[name="receipt"]');
    const name = document.getElementById("receipt-name");
    const drop = document.getElementById("receipt-drop");
    if (file && name) {
        file.addEventListener("change", () => { if (file.files[0]) name.textContent = file.files[0].name; });
        ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("dragover"); }));
        ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("dragover"); }));
        drop.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) { file.files = e.dataTransfer.files; file.dispatchEvent(new Event("change")); } });
    }
})();
