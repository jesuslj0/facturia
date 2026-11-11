/* Detalle de documento: al pulsar una incidencia se enfoca el campo afectado. */
(function () {
    // campo de la incidencia -> name del control del formulario
    const FIELD_MAP = {
        counterparty_tax_id: "company", tax_id: "company", company: "company",
        document_type: "document_type", document_number: "document_number",
        issue_date: "issue_date", total_amount: "total_amount",
        base_amount: "base_amount", tax_amount: "tax_amount", tax_percentage: "tax_percentage",
        flow: "flow", category: "category",
    };

    function focusField(field) {
        if (field === "lines" || field === "tax_lines") {
            const panel = document.querySelector(".breakdown");
            if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
            return;
        }
        const name = FIELD_MAP[field] || field;
        const el = document.querySelector('#review-form [name="' + name + '"]');
        if (!el) return;
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.focus({ preventScroll: true });
        const box = el.closest(".field");
        if (box) {
            box.classList.add("flash");
            setTimeout(() => box.classList.remove("flash"), 1600);
        }
    }

    document.querySelectorAll(".issue[data-field]").forEach((li) => {
        li.addEventListener("click", () => focusField(li.dataset.field));
        li.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focusField(li.dataset.field); }
        });
    });

    // ---- Líneas de la factura: se filtran por la página que se está viendo en el visor ----
    const panel = document.getElementById("lines-panel");
    if (panel && panel.dataset.byPage) {
        const rows = [...panel.querySelectorAll("tbody tr[data-page]")];
        const meta = document.getElementById("lines-meta");
        const footLabel = document.getElementById("lines-foot-label");
        const footSum = document.getElementById("lines-foot-sum");
        const buttons = [...panel.querySelectorAll("[data-lines-mode]")];
        const tbody = panel.querySelector("tbody");
        const money = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        let mode = "page";
        let page = 1;

        const empty = document.createElement("tr");
        empty.className = "lines-empty";
        empty.innerHTML = '<td colspan="6">No hay líneas en esta página.</td>';

        function apply() {
            let shown = 0, sum = 0;
            rows.forEach((tr) => {
                const visible = mode === "all" || Number(tr.dataset.page) === page;
                tr.hidden = !visible;
                if (visible) { shown++; sum += parseFloat(tr.dataset.amount) || 0; }
            });
            empty.remove();
            if (shown === 0) tbody.appendChild(empty);
            if (mode === "all") {
                meta.textContent = meta.dataset.all;
                footLabel.textContent = footLabel.dataset.all;
                footSum.textContent = footSum.dataset.all;
            } else {
                meta.textContent = shown + " línea" + (shown === 1 ? "" : "s") + " en la página " + page;
                footLabel.textContent = "Suma de la página " + page;
                footSum.textContent = money.format(sum) + " €";
            }
            buttons.forEach((b) => {
                const on = b.dataset.linesMode === mode;
                b.classList.toggle("active", on);
                b.setAttribute("aria-pressed", on ? "true" : "false");
            });
        }

        // Paginador: reutiliza los botones del visor, que ya saben cambiar de página
        const prevBtn = document.getElementById("lines-prev");
        const nextBtn = document.getElementById("lines-next");
        const pagerLabel = document.getElementById("lines-pager-label");
        const viewerClick = (id) => { const b = document.getElementById(id); if (b) b.click(); };
        prevBtn.addEventListener("click", () => viewerClick("prev-page"));
        nextBtn.addEventListener("click", () => viewerClick("next-page"));

        function updatePager(total) {
            pagerLabel.textContent = page + " / " + total;
            prevBtn.disabled = page <= 1;
            nextBtn.disabled = page >= total;
        }

        buttons.forEach((b) => b.addEventListener("click", () => { mode = b.dataset.linesMode; apply(); }));
        document.addEventListener("viewer:page", (e) => { page = e.detail.page; apply(); updatePager(e.detail.total); });
        apply();
    }

    // ---- "Guardar cambios": activo solo si se ha modificado o añadido algún campo ----
    const reviewForm = document.getElementById("review-form");
    const saveBtn = document.getElementById("save-changes");
    if (reviewForm && saveBtn) {
        const TIP = "Modifica algún campo para poder guardar";

        // Compara cada control con su valor original (el que vino del servidor), así también
        // detecta valores restaurados por el navegador al volver con "atrás".
        function isDirty() {
            return [...reviewForm.elements].some((el) => {
                if (el.name === "csrfmiddlewaretoken") return false;
                if (el.tagName === "SELECT") return [...el.options].some((o) => o.selected !== o.defaultSelected);
                if (el.type === "checkbox" || el.type === "radio") return el.checked !== el.defaultChecked;
                if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") return el.value !== el.defaultValue;
                return false;
            });
        }

        function refresh() {
            const dirty = isDirty();
            saveBtn.disabled = !dirty;
            saveBtn.title = dirty ? "" : TIP;
        }

        // input/change cubren escribir, elegir en un select y borrar; tax-calculator.js
        // recalcula otros campos a partir de un input, que ya dispara el evento.
        reviewForm.addEventListener("input", refresh);
        reviewForm.addEventListener("change", refresh);
        window.addEventListener("pageshow", refresh);
        refresh();
    }
})();
