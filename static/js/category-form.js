/* Formulario de categoría: vista previa en vivo, colores sugeridos y selector de iconos. */
(function () {
    const form = document.getElementById("category-form");
    if (!form) return;
    const name = form.querySelector('[name="name"]');
    const color = form.querySelector('[name="color"]');
    const icon = form.querySelector('[name="icon"]');
    const types = form.querySelectorAll('[name="type"]');
    const preview = document.getElementById("cat-preview");
    const prevIcon = document.getElementById("prev-icon");
    const prevName = document.getElementById("prev-name");
    const prevType = document.getElementById("prev-type");
    const hex = document.getElementById("color-hex");
    const swatches = document.getElementById("swatches");
    const grid = document.getElementById("icon-grid");

    const COLORS = ["#ef4444", "#f97316", "#f59e0b", "#eab308", "#22c55e", "#10b981", "#14b8a6", "#06b6d4", "#3b82f6", "#6366f1", "#8b5cf6", "#d946ef", "#ec4899", "#64748b"];
    const ICONS = ["users", "building", "bolt", "receipt", "bullhorn", "car", "utensils", "cart-shopping", "briefcase", "money-bill-trend-up",
        "hand-holding-heart", "piggy-bank", "chart-line", "hand-holding-dollar", "file-invoice-dollar", "laptop", "phone", "wifi", "plane", "gas-pump",
        "shield-halved", "graduation-cap", "stethoscope", "house", "wrench", "box", "gift", "mug-hot", "ellipsis", "plus"].map((n) => "fa-solid fa-" + n);
    const TYPE_TONES = { expense: "danger", income: "success", investment: "info", loan: "warning" };

    function update() {
        const c = /^#[0-9a-f]{6}$/i.test(color.value) ? color.value : "#3b82f6";
        preview.style.setProperty("--color", c);
        hex.textContent = c;
        prevName.textContent = name.value.trim() || "Nombre de la categoría";
        prevIcon.className = (icon.value.trim() || "fa-solid fa-tag");
        const t = [...types].find((r) => r.checked);
        prevType.textContent = t ? t.closest("label").querySelector("span").textContent : "";
        swatches.querySelectorAll(".swatch").forEach((s) => s.classList.toggle("active", s.dataset.c.toLowerCase() === c.toLowerCase()));
        grid.querySelectorAll(".icon-opt").forEach((b) => b.classList.toggle("active", b.dataset.i === icon.value.trim()));
    }

    COLORS.forEach(function (c) {
        const b = document.createElement("button");
        b.type = "button"; b.className = "swatch"; b.dataset.c = c; b.style.setProperty("--c", c); b.title = c;
        b.addEventListener("click", () => { color.value = c; update(); });
        swatches.appendChild(b);
    });
    ICONS.forEach(function (i) {
        const b = document.createElement("button");
        b.type = "button"; b.className = "icon-opt"; b.dataset.i = i; b.title = i.replace("fa-solid fa-", "");
        b.innerHTML = '<i class="' + i + '" aria-hidden="true"></i>';
        b.addEventListener("click", () => { icon.value = i; update(); });
        grid.appendChild(b);
    });

    [name, color, icon].forEach((el) => el.addEventListener("input", update));
    types.forEach((r) => r.addEventListener("change", update));
    update();
})();
