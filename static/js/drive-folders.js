/* Archivo > Mis carpetas: nueva carpeta (formulario en línea), renombrar en línea y eliminar con diálogo.
   Se carga sin defer tras el listado. Sin JS el formulario de creación sigue visible y funcional;
   renombrar y eliminar solo aparecen con JS. Esc cierra lo abierto. */
(function () {
    var ESC = "Escape";

    /* ---- Nueva carpeta ---- */
    var create = document.querySelector("[data-folder-create]");
    if (create) {
        var openBtn = create.querySelector("[data-create-open]");
        var form = create.querySelector("form");
        var cancelBtn = create.querySelector("[data-create-cancel]");
        var nameInput = form.elements.name;

        var setOpen = function (open, restoreFocus) {
            form.hidden = !open;
            openBtn.hidden = open;
            openBtn.setAttribute("aria-expanded", open ? "true" : "false");
            if (open) { nameInput.focus(); }
            else {
                nameInput.value = "";
                if (restoreFocus) openBtn.focus();
            }
        };
        openBtn.hidden = false;
        cancelBtn.hidden = false;
        setOpen(false, false);
        openBtn.addEventListener("click", function () { setOpen(true); });
        cancelBtn.addEventListener("click", function () { setOpen(false, true); });
        form.addEventListener("keydown", function (e) {
            if (e.key === ESC) { e.preventDefault(); setOpen(false, true); }
        });
    }

    /* ---- Renombrar en línea ---- */
    function stopRename(item, restoreFocus) {
        var form = item.querySelector(".folder-rename");
        if (!form || form.hidden) return;
        form.hidden = true;
        form.elements.name.value = form.elements.name.defaultValue;
        item.classList.remove("is-editing");
        if (restoreFocus) {
            var btn = item.querySelector("[data-folder-rename]");
            if (btn) btn.focus();
        }
    }
    function startRename(item) {
        Array.prototype.forEach.call(document.querySelectorAll(".folder-list > li.is-editing"), function (other) {
            stopRename(other, false);
        });
        var form = item.querySelector(".folder-rename");
        if (!form) return;
        form.hidden = false;
        item.classList.add("is-editing");
        form.elements.name.focus();
        form.elements.name.select();
    }

    /* ---- Eliminar con confirmación ---- */
    var dialog = document.getElementById("folder-delete-dialog");
    var canDialog = dialog && typeof dialog.showModal === "function";
    if (canDialog) {
        var idField = document.getElementById("folder-delete-id");
        var title = document.getElementById("folder-delete-title");
        var cancel = dialog.querySelector("[data-dialog-cancel]");
        var opener = null;

        cancel.addEventListener("click", function () { dialog.close(); });
        // Clic en el fondo (fuera de la caja) cierra el diálogo
        dialog.addEventListener("click", function (e) {
            if (e.target !== dialog) return;
            var r = dialog.getBoundingClientRect();
            var outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
            if (outside) dialog.close();
        });
        dialog.addEventListener("close", function () {
            if (opener && document.contains(opener)) opener.focus();
            opener = null;
        });
        document.addEventListener("click", function (e) {
            var btn = e.target.closest("[data-folder-delete]");
            if (!btn) return;
            opener = btn;
            idField.value = btn.getAttribute("data-folder-id");
            title.textContent = "Eliminar «" + btn.getAttribute("data-folder-name") + "»";
            dialog.showModal();
            cancel.focus();   // la opción segura recibe el foco
        });
    }

    /* ---- Acciones por carpeta (se muestran solo si funcionan) ---- */
    Array.prototype.forEach.call(document.querySelectorAll(".folder-actions"), function (box) {
        var del = box.querySelector("[data-folder-delete]");
        if (del && !canDialog) del.hidden = true;
        box.hidden = false;
    });

    document.addEventListener("click", function (e) {
        var item;
        var rename = e.target.closest("[data-folder-rename]");
        if (rename) { item = rename.closest("li"); if (item) startRename(item); return; }
        var cancelRename = e.target.closest("[data-rename-cancel]");
        if (cancelRename) { item = cancelRename.closest("li"); if (item) stopRename(item, true); }
    });
    document.addEventListener("keydown", function (e) {
        if (e.key !== ESC) return;
        var form = e.target.closest && e.target.closest(".folder-rename");
        if (!form) return;
        e.preventDefault();
        stopRename(form.closest("li"), true);
    });
})();
