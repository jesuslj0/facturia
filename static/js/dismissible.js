/* Avisos que se pueden cerrar: <div data-dismiss-key="clave"> con un botón [data-dismiss] (oculto sin JS).
   El cierre se recuerda en localStorage; sin almacenamiento, el aviso vuelve a salir en cada visita. */
(function () {
    var PREFIX = "dismissed:";
    Array.prototype.forEach.call(document.querySelectorAll("[data-dismiss-key]"), function (note) {
        var key = PREFIX + note.getAttribute("data-dismiss-key");
        var button = note.querySelector("[data-dismiss]");
        if (!button) return;
        try { if (localStorage.getItem(key) === "1") { note.hidden = true; return; } } catch (e) { /* se muestra */ }
        button.hidden = false;
        button.addEventListener("click", function () {
            note.hidden = true;
            try { localStorage.setItem(key, "1"); } catch (e) { /* no se recuerda */ }
        });
    });
})();
