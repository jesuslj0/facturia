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

    function render() {
        const all = [...filesInput.files, ...photosInput.files];
        list.innerHTML = "";
        let ok = all.length > 0 && all.length <= MAX_FILES;
        all.forEach((f) => {
            const li = document.createElement("li");
            const tooBig = f.size > MAX_BYTES;
            if (tooBig) { li.className = "invalid"; ok = false; }
            const name = document.createElement("span");
            name.textContent = f.name;
            const size = document.createElement("span");
            size.className = "size";
            size.textContent = tooBig ? "demasiado grande (" + fmt(f.size) + ")" : fmt(f.size);
            li.append(name, size);
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

    filesInput.addEventListener("change", render);
    photosInput.addEventListener("change", render);

    ["dragenter", "dragover"].forEach((ev) =>
        dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("dragover"); }));
    ["dragleave", "drop"].forEach((ev) =>
        dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); }));
    dropzone.addEventListener("drop", (e) => {
        if (e.dataTransfer && e.dataTransfer.files.length) {
            filesInput.files = e.dataTransfer.files;
            render();
        }
    });

    form.addEventListener("submit", () => {
        submit.disabled = true;
        submit.innerHTML = 'Subiendo… <i class="fa-solid fa-spinner fa-spin"></i>';
    });
    render();
})();
