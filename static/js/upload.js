/* Subida multi-archivo: arrastrar y soltar, vista previa de la selección y validación básica. */
(function () {
    const form = document.getElementById("upload-form");
    if (!form) return;
    const MAX_FILES = parseInt(form.dataset.maxFiles, 10) || 20;
    const MAX_BYTES = (parseInt(form.dataset.maxMb, 10) || 20) * 1024 * 1024;
    const filesInput = form.querySelector('input[name="files"]');
    const photosInput = form.querySelector('input[name="photos"]');
    const dropzone = document.getElementById("dropzone");
    const list = document.getElementById("file-list");
    const submit = document.getElementById("upload-submit");

    const fmt = (n) => (n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");

    // Un <input type=file> sustituye su selección en cada elección y es de solo lectura.
    // Se guarda aquí la lista acumulada y se vuelca al input con DataTransfer.
    const store = new Map([[filesInput, [...filesInput.files]], [photosInput, [...photosInput.files]]]);
    const sameFile = (a, b) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

    function sync(input) {
        const dt = new DataTransfer();
        store.get(input).forEach((f) => dt.items.add(f));
        input.files = dt.files;
    }

    function addFiles(input, incoming) {
        const current = store.get(input);
        [...incoming].forEach((f) => { if (!current.some((c) => sameFile(c, f))) current.push(f); });
        sync(input);
        render();
    }

    function removeFile(input, index) {
        store.get(input).splice(index, 1);
        sync(input);
        render();
    }

    function render() {
        const all = [
            ...[...filesInput.files].map((f, i) => ({ f, input: filesInput, i })),
            ...[...photosInput.files].map((f, i) => ({ f, input: photosInput, i })),
        ];
        list.innerHTML = "";
        let ok = all.length > 0 && all.length <= MAX_FILES;
        all.forEach(({ f, input, i }) => {
            const li = document.createElement("li");
            const tooBig = f.size > MAX_BYTES;
            if (tooBig) { li.className = "invalid"; ok = false; }
            const name = document.createElement("span");
            name.textContent = f.name;
            const size = document.createElement("span");
            size.className = "size";
            size.textContent = tooBig ? "demasiado grande (" + fmt(f.size) + ")" : fmt(f.size);
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "file-remove";
            remove.title = "Quitar de la lista";
            remove.setAttribute("aria-label", "Quitar " + f.name);
            remove.innerHTML = '<i class="fa-solid fa-xmark"></i>';
            remove.addEventListener("click", () => removeFile(input, i));
            li.append(name, size, remove);
            list.appendChild(li);
        });
        if (all.length > MAX_FILES) {
            const li = document.createElement("li");
            li.className = "invalid";
            li.textContent = "Máximo " + MAX_FILES + " archivos por subida.";
            list.appendChild(li);
        }
        submit.disabled = !ok;
    }

    // Al elegir de nuevo, input.files trae solo lo último: se suma a lo ya elegido.
    filesInput.addEventListener("change", () => addFiles(filesInput, filesInput.files));
    photosInput.addEventListener("change", () => addFiles(photosInput, photosInput.files));

    ["dragenter", "dragover"].forEach((ev) =>
        dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("dragover"); }));
    ["dragleave", "drop"].forEach((ev) =>
        dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); }));
    dropzone.addEventListener("drop", (e) => {
        if (e.dataTransfer && e.dataTransfer.files.length) {
            addFiles(filesInput, e.dataTransfer.files);
        }
    });

    form.addEventListener("submit", () => {
        submit.disabled = true;
        submit.innerHTML = 'Subiendo… <i class="fa-solid fa-spinner fa-spin"></i>';
    });
    render();
})();
