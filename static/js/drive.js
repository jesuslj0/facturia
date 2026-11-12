/* Archivo: alterna las carpetas entre lista y cuadrícula (data-view en #folder-view).
   Se carga sin defer justo tras el contenedor para evitar parpadeo. Sin JS queda la lista. */
(function () {
    var KEY = "drive:folder-view";
    var root = document.getElementById("folder-view");
    var bar = document.querySelector(".view-toggle");
    if (!root || !bar) return;
    var buttons = bar.querySelectorAll("[data-view-option]");

    function stored() {
        try { return localStorage.getItem(KEY) === "grid" ? "grid" : "list"; }
        catch (e) { return "list"; }
    }
    function save(view) {
        try { localStorage.setItem(KEY, view); } catch (e) { /* sin almacenamiento: no se recuerda */ }
    }
    function apply(view) {
        root.setAttribute("data-view", view);
        Array.prototype.forEach.call(buttons, function (b) {
            b.setAttribute("aria-pressed", b.getAttribute("data-view-option") === view ? "true" : "false");
        });
    }

    apply(stored());
    bar.hidden = false;
    Array.prototype.forEach.call(buttons, function (b) {
        b.addEventListener("click", function () {
            var view = b.getAttribute("data-view-option");
            apply(view);
            save(view);
        });
    });
})();
